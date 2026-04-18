"""Meeting management endpoints - upload, transcribe, summarize"""
from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File, Form, Query, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, or_
from sqlalchemy.orm import selectinload
from typing import List, Optional
from datetime import datetime
import tempfile
import os
import logging

from app.database import get_db
from app.models import Meeting, User, ActionItem, MeetingStatus, ActionItemStatus
from app.schemas.meeting import MeetingResponse, MeetingUploadResponse, MeetingUpdate
from app.dependencies import get_current_user, get_current_admin_user
from app.utils.storage import get_storage

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/meetings", tags=["Meetings"])

# Allowed audio file extensions
ALLOWED_EXTENSIONS = {'.mp3', '.wav', '.m4a', '.webm', '.mp4', '.mpeg', '.mpga'}
# Groq Whisper API limit
MAX_FILE_SIZE = 25 * 1024 * 1024  # 25MB (Groq Whisper API limit)


async def process_meeting_background(meeting_id: str):
    """
    Background task to transcribe and summarize meeting using OpenAI Whisper API.
    This runs as an async background task within FastAPI's event loop.
    """
    from app.services.ai_service import transcribe_meeting, summarize_meeting
    from app.database import AsyncSessionLocal

    tmp_file_path = None

    try:
        logger.info(f"[Meeting {meeting_id}] Starting background processing")

        async with AsyncSessionLocal() as db:
            # Get meeting
            result = await db.execute(select(Meeting).where(Meeting.id == meeting_id))
            meeting = result.scalar_one_or_none()

            if not meeting:
                logger.error(f"[Meeting {meeting_id}] Not found")
                return

            if not meeting.recording_url:
                logger.error(f"[Meeting {meeting_id}] No recording URL")
                meeting.status = MeetingStatus.FAILED
                await db.commit()
                return

            # Download audio file
            storage = get_storage()
            recording_url = meeting.recording_url

            # Extract key from URL
            if recording_url.startswith('local://'):
                key = recording_url.replace('local://', '')
            elif '.amazonaws.com/' in recording_url:
                key = recording_url.split('.amazonaws.com/')[-1]
            elif 'cloudinary.com' in recording_url:
                key = recording_url.split('/upload/')[-1]
            else:
                key = recording_url.split('.com/')[-1] if '.com/' in recording_url else recording_url

            # Create temp file
            file_ext = os.path.splitext(key)[1]
            with tempfile.NamedTemporaryFile(delete=False, suffix=file_ext) as tmp_file:
                tmp_file_path = tmp_file.name

            logger.info(f"[Meeting {meeting_id}] Downloading to {tmp_file_path}")

            # Download file
            await storage.download_file(key, tmp_file_path)

            # Check file size
            file_size_mb = os.path.getsize(tmp_file_path) / (1024 * 1024)
            logger.info(f"[Meeting {meeting_id}] File size: {file_size_mb:.2f}MB")

            # Transcribe using OpenAI Whisper API
            logger.info(f"[Meeting {meeting_id}] Starting transcription via OpenAI Whisper API...")
            transcript = await transcribe_meeting(tmp_file_path)

            # Calculate duration from audio file (rough estimation from file size)
            duration_minutes = max(1, int(file_size_mb * 2))

            logger.info(f"[Meeting {meeting_id}] Transcription complete! {len(transcript)} chars, ~{duration_minutes} min")

            # Clean up temp file
            os.unlink(tmp_file_path)
            tmp_file_path = None

            # Save transcript
            meeting.transcript = transcript
            meeting.duration_minutes = duration_minutes
            meeting.status = MeetingStatus.TRANSCRIBED
            await db.commit()

            logger.info(f"[Meeting {meeting_id}] Transcript saved, starting summarization")

            # Summarize
            summary_data = await summarize_meeting(transcript, meeting.title)

            # Save summary
            meeting.summary = summary_data["summary"]

            # Create action items
            action_items_data = summary_data.get("action_items", [])
            created_count = 0

            for item_data in action_items_data:
                confidence = item_data.get("confidence", 0.0)
                if confidence >= 0.6:
                    action_item = ActionItem(
                        meeting_id=meeting_id,
                        description=item_data.get("description", ""),
                        assignee_mentioned=item_data.get("assignee"),
                        deadline_mentioned=item_data.get("deadline"),
                        confidence_score=confidence,
                        status="pending"
                    )
                    db.add(action_item)
                    created_count += 1

            meeting.status = MeetingStatus.COMPLETED
            await db.commit()

            logger.info(f"[Meeting {meeting_id}] Processing complete! {created_count} action items created")

    except Exception as e:
        logger.error(f"[Meeting {meeting_id}] Processing failed: {str(e)}", exc_info=True)

        # Mark as failed
        try:
            from app.database import AsyncSessionLocal as FailSessionLocal
            async with FailSessionLocal() as db:
                result = await db.execute(select(Meeting).where(Meeting.id == meeting_id))
                meeting = result.scalar_one_or_none()
                if meeting:
                    meeting.status = MeetingStatus.FAILED
                    await db.commit()
        except Exception as db_err:
            logger.error(f"[Meeting {meeting_id}] Failed to update status: {str(db_err)}")

        # Clean up temp file
        if tmp_file_path and os.path.exists(tmp_file_path):
            try:
                os.unlink(tmp_file_path)
            except:
                pass


@router.post("/upload", response_model=MeetingUploadResponse, status_code=status.HTTP_201_CREATED)
async def upload_meeting(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    title: str = Form(...),
    current_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Upload a meeting recording for transcription and summarization.

    Supported formats: MP3, WAV, M4A, WebM, MP4
    Maximum size: 25MB (Whisper API limit)

    The file will be:
    1. Validated for format and size
    2. Uploaded to S3/Cloudinary/local storage
    3. Queued for transcription (background job)

    Returns meeting ID and status.
    """
    # Validate file extension
    file_ext = os.path.splitext(file.filename)[1].lower()
    if file_ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported file format. Allowed: {', '.join(ALLOWED_EXTENSIONS)}"
        )

    # Read file content
    content = await file.read()
    file_size = len(content)

    # Validate file size
    if file_size > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File too large. Maximum size: {MAX_FILE_SIZE / (1024*1024)}MB"
        )

    if file_size == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="File is empty"
        )

    try:
        # Upload to storage
        storage = get_storage()

        # Create temporary file
        with tempfile.NamedTemporaryFile(delete=False, suffix=file_ext) as tmp_file:
            tmp_file.write(content)
            tmp_file_path = tmp_file.name

        # Upload to cloud storage
        with open(tmp_file_path, 'rb') as f:
            recording_url = await storage.upload_file(
                f,
                file.filename,
                folder="meetings",
                content_type=file.content_type
            )

        # Clean up temp file
        os.unlink(tmp_file_path)

        # Create meeting record
        new_meeting = Meeting(
            title=title,
            recording_url=recording_url,
            status=MeetingStatus.PROCESSING,
            team_id=current_user.team_id,
            created_by_id=current_user.id,
            duration_minutes=None  # Will be calculated from audio
        )

        db.add(new_meeting)
        await db.commit()
        await db.refresh(new_meeting)

        # Trigger transcription in background using OpenAI Whisper API
        logger.info(f"Scheduling transcription for meeting {new_meeting.id}")
        background_tasks.add_task(process_meeting_background, new_meeting.id)

        return {
            "id": new_meeting.id,
            "title": new_meeting.title,
            "status": new_meeting.status.value,
            "message": "Meeting uploaded successfully! Transcription starting..."
        }

    except Exception as e:
        # Clean up temp file if it exists
        if 'tmp_file_path' in locals() and os.path.exists(tmp_file_path):
            os.unlink(tmp_file_path)

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Upload failed: {str(e)}"
        )


@router.get("", response_model=List[MeetingResponse])
async def get_meetings(
    status: Optional[str] = None,
    date_from: Optional[datetime] = None,
    date_to: Optional[datetime] = None,
    limit: int = Query(default=20, le=100),
    offset: int = Query(default=0, ge=0),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Get meetings with optional filters.

    Query parameters:
    - **status**: Filter by status (scheduled, processing, transcribed, completed, failed)
    - **date_from**: Filter meetings created after this date
    - **date_to**: Filter meetings created before this date
    - **limit**: Maximum number of results (default 20, max 100)
    - **offset**: Number of results to skip for pagination
    """
    # Build query - only show meetings from user's team
    query = select(Meeting).where(Meeting.team_id == current_user.team_id)

    # Apply filters
    if status:
        query = query.where(Meeting.status == status)

    if date_from:
        query = query.where(Meeting.created_at >= date_from)

    if date_to:
        query = query.where(Meeting.created_at <= date_to)

    # Order by created_at descending
    query = query.order_by(Meeting.created_at.desc())

    # Apply pagination
    query = query.limit(limit).offset(offset)

    # Load relationships
    query = query.options(selectinload(Meeting.action_items))

    # Execute query
    result = await db.execute(query)
    meetings = result.scalars().all()

    return meetings


@router.get("/{meeting_id}", response_model=MeetingResponse)
async def get_meeting(
    meeting_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Get a specific meeting by ID.

    Returns full meeting details including:
    - Transcript
    - Summary
    - Action items
    - Recording URL
    """
    result = await db.execute(
        select(Meeting).where(
            and_(
                Meeting.id == meeting_id,
                Meeting.team_id == current_user.team_id
            )
        ).options(selectinload(Meeting.action_items))
    )
    meeting = result.scalar_one_or_none()

    if not meeting:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Meeting not found"
        )

    return meeting


@router.patch("/{meeting_id}", response_model=MeetingResponse)
async def update_meeting(
    meeting_id: str,
    meeting_update: MeetingUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Update meeting details (title, scheduled time, duration).

    Transcript and summary cannot be manually edited.
    """
    # Get existing meeting
    result = await db.execute(
        select(Meeting).where(
            and_(
                Meeting.id == meeting_id,
                Meeting.team_id == current_user.team_id
            )
        )
    )
    meeting = result.scalar_one_or_none()

    if not meeting:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Meeting not found"
        )

    # Update fields
    update_data = meeting_update.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(meeting, field, value)

    await db.commit()
    await db.refresh(meeting)

    # Load relationships
    await db.refresh(meeting, ["action_items"])

    return meeting


@router.delete("/{meeting_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_meeting(
    meeting_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Delete a meeting and its recording.

    This will:
    1. Delete the recording file from storage
    2. Delete the database record (cascade deletes action items)
    """
    result = await db.execute(
        select(Meeting).where(
            and_(
                Meeting.id == meeting_id,
                Meeting.team_id == current_user.team_id
            )
        )
    )
    meeting = result.scalar_one_or_none()

    if not meeting:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Meeting not found"
        )

    # Delete recording from storage
    if meeting.recording_url:
        try:
            storage = get_storage()
            # Extract key from URL based on storage type
            recording_url = meeting.recording_url
            if recording_url.startswith('local://'):
                # Local storage format: local://meetings/filename.mp3
                key = recording_url.replace('local://', '')
            elif '.amazonaws.com/' in recording_url:
                # S3 format: https://bucket.s3.region.amazonaws.com/meetings/filename.mp3
                key = recording_url.split('.amazonaws.com/')[-1]
            elif 'cloudinary.com' in recording_url:
                # Cloudinary format
                key = recording_url.split('/upload/')[-1]
            else:
                # Fallback
                key = recording_url.split('.com/')[-1] if '.com/' in recording_url else recording_url

            await storage.delete_file(key)
        except Exception as e:
            print(f"Failed to delete recording: {str(e)}")
            # Continue with database deletion even if file deletion fails

    # Delete database record
    await db.delete(meeting)
    await db.commit()

    return None


@router.post("/{meeting_id}/retry", status_code=status.HTTP_200_OK)
async def retry_meeting_transcription(
    meeting_id: str,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Retry transcription for a failed or stuck meeting.
    Resets status to PROCESSING and re-queues background job.
    """
    result = await db.execute(
        select(Meeting).where(
            and_(
                Meeting.id == meeting_id,
                Meeting.team_id == current_user.team_id
            )
        )
    )
    meeting = result.scalar_one_or_none()

    if not meeting:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Meeting not found"
        )

    if meeting.status not in (MeetingStatus.FAILED, MeetingStatus.PROCESSING):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only failed or stuck meetings can be retried"
        )

    if not meeting.recording_url:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No recording file found for this meeting"
        )

    # Reset status
    meeting.status = MeetingStatus.PROCESSING
    meeting.transcript = None
    meeting.summary = None
    await db.commit()

    # Re-queue background task
    logger.info(f"Retrying transcription for meeting {meeting.id}")
    background_tasks.add_task(process_meeting_background, meeting.id)

    return {"id": meeting.id, "status": "processing", "message": "Transcription retry started"}


@router.post("/{meeting_id}/action-items/{action_item_id}/convert", status_code=status.HTTP_201_CREATED)
async def convert_action_item_to_task(
    meeting_id: str,
    action_item_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Convert an action item to a task.

    Creates a new task from the action item and marks it as converted.
    """
    from app.models import Task, TaskStatus, TaskPriority, TaskSourceType, Integration, IntegrationPlatform

    # Get action item
    result = await db.execute(
        select(ActionItem).where(ActionItem.id == action_item_id)
    )
    action_item = result.scalar_one_or_none()

    if not action_item:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Action item not found"
        )

    if action_item.meeting_id != meeting_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Action item does not belong to this meeting"
        )

    if action_item.status == ActionItemStatus.CONVERTED:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Action item already converted to task"
        )

    # Create task from action item
    new_task = Task(
        title=action_item.description[:500],
        description=action_item.description,
        status=TaskStatus.TODO,
        priority=TaskPriority.MEDIUM,
        due_date=action_item.deadline_mentioned,
        team_id=current_user.team_id,
        created_by_id=current_user.id,
        source_type=TaskSourceType.MEETING,
        source_id=meeting_id
    )

    # Try to assign to mentioned person
    if action_item.assignee_mentioned:
        result = await db.execute(
            select(User).where(
                and_(
                    User.team_id == current_user.team_id,
                    or_(
                        User.full_name.ilike(f"%{action_item.assignee_mentioned}%"),
                        User.email.ilike(f"%{action_item.assignee_mentioned}%")
                    )
                )
            )
        )
        assignee = result.scalar_one_or_none()
        if assignee:
            new_task.assignee_id = assignee.id

    db.add(new_task)
    await db.commit()
    await db.refresh(new_task)

    # Mark action item as converted using the proper enum value
    action_item.status = ActionItemStatus.CONVERTED
    action_item.task_id = new_task.id
    await db.commit()

    # Queue Jira sync if user has an active Jira integration
    try:
        from app.tasks.integration_tasks import sync_task_to_jira
        jira_q = await db.execute(
            select(Integration).where(
                Integration.user_id == current_user.id,
                Integration.platform == IntegrationPlatform.JIRA,
                Integration.is_active == True,
            )
        )
        if jira_q.scalar_one_or_none():
            sync_task_to_jira.delay(new_task.id, current_user.id)
    except Exception:
        pass  # Don't fail task creation if Jira sync can't be queued

    return {
        "task_id": new_task.id,
        "task_title": new_task.title,
        "message": "Action item converted to task successfully",
    }


@router.post("/{meeting_id}/action-items/{action_item_id}/reject", status_code=status.HTTP_200_OK)
async def reject_action_item(
    meeting_id: str,
    action_item_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Reject an action item (mark as not relevant).
    """
    # Get action item
    result = await db.execute(
        select(ActionItem).where(ActionItem.id == action_item_id)
    )
    action_item = result.scalar_one_or_none()

    if not action_item:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Action item not found"
        )

    if action_item.meeting_id != meeting_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Action item does not belong to this meeting"
        )

    # Update status
    action_item.status = "rejected"
    await db.commit()

    return {"message": "Action item rejected successfully"}


@router.get("/whisper-status", status_code=status.HTTP_200_OK)
async def check_whisper_status():
    """
    Check if FREE local Whisper is available and ready for transcription.

    Returns system info and installation status.
    """
    from app.services.whisper_local import check_whisper_availability

    status_info = check_whisper_availability()

    return {
        "whisper": status_info,
        "transcription_method": "FREE Local Whisper (no API key needed!)",
        "setup_guide": "See backend/WHISPER_SETUP.md for installation instructions"
    }
