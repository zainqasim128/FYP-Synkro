"""Meeting management endpoints - upload, transcribe, summarize"""
from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File, Form, Query, BackgroundTasks
from fastapi.responses import PlainTextResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, or_
from sqlalchemy.orm import selectinload
from typing import List, Optional
from datetime import datetime, timedelta
import asyncio
import tempfile
import os
import logging

from app.database import get_db
from app.models import Meeting, User, ActionItem, MeetingStatus, Integration, IntegrationPlatform
from app.schemas.meeting import MeetingResponse, MeetingUploadResponse, MeetingUpdate, SpeakerNamesUpdate
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
    Background task: transcribe → diarize → context-analyse → summarise.
    Runs inside FastAPI's async event loop (no Celery needed).
    """
    import json as _json
    from app.services.ai_service import transcribe_meeting_with_segments
    from app.services.diarization_service import diarize_audio, format_diarized_transcript
    from app.services.meeting_analysis_service import analyze_meeting_context, generate_speaker_aware_summary
    from app.database import AsyncSessionLocal

    tmp_file_path = None

    try:
        logger.info(f"[Meeting {meeting_id}] Starting background processing")

        async with AsyncSessionLocal() as db:
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

            # ── Download audio ────────────────────────────────────────
            storage = get_storage()
            recording_url = meeting.recording_url
            if recording_url.startswith('local://'):
                key = recording_url.replace('local://', '')
            elif '.amazonaws.com/' in recording_url:
                key = recording_url.split('.amazonaws.com/')[-1]
            elif 'cloudinary.com' in recording_url:
                key = recording_url.split('/upload/')[-1]
            else:
                key = recording_url.split('.com/')[-1] if '.com/' in recording_url else recording_url

            file_ext = os.path.splitext(key)[1]
            with tempfile.NamedTemporaryFile(delete=False, suffix=file_ext) as tmp_file:
                tmp_file_path = tmp_file.name

            logger.info(f"[Meeting {meeting_id}] Downloading to {tmp_file_path}")
            await storage.download_file(key, tmp_file_path)

            file_size_mb = os.path.getsize(tmp_file_path) / (1024 * 1024)
            logger.info(f"[Meeting {meeting_id}] File size: {file_size_mb:.2f}MB")

            # ── Transcribe (Whisper) ──────────────────────────────────
            logger.info(f"[Meeting {meeting_id}] Transcribing…")
            transcript, whisper_segments = await transcribe_meeting_with_segments(tmp_file_path)
            logger.info(
                f"[Meeting {meeting_id}] Transcription complete — "
                f"{len(transcript)} chars, {len(whisper_segments)} Whisper segments"
            )

            # ── Duration ─────────────────────────────────────────────
            try:
                from mutagen import File as MutagenFile
                audio = MutagenFile(tmp_file_path)
                if audio and hasattr(audio.info, 'length'):
                    meeting.duration_minutes = int(audio.info.length / 60)
                else:
                    meeting.duration_minutes = max(1, int(file_size_mb * 2))
            except Exception:
                meeting.duration_minutes = max(1, int(file_size_mb * 2))

            # ── Speaker diarization ───────────────────────────────────
            logger.info(f"[Meeting {meeting_id}] Diarizing speakers…")
            try:
                diarized_segments = await diarize_audio(
                    audio_file_path=tmp_file_path,
                    raw_transcript=transcript,
                    whisper_segments=whisper_segments or None,
                )
                diarized_text = format_diarized_transcript(diarized_segments)
                unique_speakers = len({s['speaker'] for s in diarized_segments})
                logger.info(
                    f"[Meeting {meeting_id}] Diarization complete — "
                    f"{len(diarized_segments)} segments, {unique_speakers} speakers"
                )
            except Exception as diar_err:
                logger.warning(
                    f"[Meeting {meeting_id}] Diarization failed ({diar_err}), using plain transcript",
                    exc_info=True,
                )
                diarized_segments = []
                diarized_text = transcript

            # Clean up temp file
            os.unlink(tmp_file_path)
            tmp_file_path = None

            meeting.transcript = diarized_text
            meeting.diarized_transcript = _json.dumps(diarized_segments) if diarized_segments else None
            meeting.status = MeetingStatus.TRANSCRIBED
            await db.commit()
            logger.info(f"[Meeting {meeting_id}] Saved transcript → TRANSCRIBED")

            # ── Context analysis ──────────────────────────────────────
            speakers = []
            if diarized_segments:
                try:
                    analysis_result = await analyze_meeting_context(diarized_segments, meeting.title)
                    enriched_segs = analysis_result.get("segments", diarized_segments)
                    speakers = analysis_result.get("speakers", [])
                    meeting.diarized_transcript = _json.dumps(enriched_segs)
                    await db.commit()
                    logger.info(f"[Meeting {meeting_id}] Context analysis done — {len(speakers)} speakers")
                except Exception as ctx_err:
                    logger.warning(f"[Meeting {meeting_id}] Context analysis failed: {ctx_err}", exc_info=True)

            # ── Summarise ─────────────────────────────────────────────
            logger.info(f"[Meeting {meeting_id}] Summarising…")
            try:
                if diarized_segments and speakers:
                    summary_data = await generate_speaker_aware_summary(
                        diarized_transcript=meeting.transcript,
                        meeting_title=meeting.title,
                        speakers=speakers,
                    )
                else:
                    from app.services.ai_service import summarize_meeting
                    summary_data = await summarize_meeting(transcript, meeting.title)
            except Exception as sum_err:
                logger.warning(f"[Meeting {meeting_id}] Summarisation failed: {sum_err}", exc_info=True)
                from app.services.ai_service import summarize_meeting
                summary_data = await summarize_meeting(transcript, meeting.title)

            meeting.summary = summary_data.get("summary", "")

            # ── Action items ──────────────────────────────────────────
            action_items_data = summary_data.get("action_items", [])
            created_count = 0
            for item_data in action_items_data:
                confidence = item_data.get("confidence", 0.0)
                if confidence >= 0.6:
                    deadline = item_data.get("deadline")
                    parsed_deadline = None
                    if deadline:
                        try:
                            import dateparser
                            parsed_deadline = dateparser.parse(
                                str(deadline),
                                settings={"PREFER_DATES_FROM": "future", "RETURN_AS_TIMEZONE_AWARE": False},
                            )
                        except Exception:
                            pass
                    action_item = ActionItem(
                        meeting_id=meeting_id,
                        description=item_data.get("description", ""),
                        assignee_mentioned=item_data.get("assigned_to_name") or item_data.get("assignee"),
                        deadline_mentioned=parsed_deadline,
                        confidence_score=confidence,
                        status="pending",
                        speaker_label=item_data.get("speaker_label"),
                        assigned_by=item_data.get("assigned_by"),
                        context_type=item_data.get("context_type"),
                    )
                    db.add(action_item)
                    created_count += 1

            meeting.status = MeetingStatus.COMPLETED
            await db.commit()
            logger.info(f"[Meeting {meeting_id}] Complete — {created_count} action items")

            # ── Google Calendar + Meet sync (fire-and-forget) ─────────────────────
            if meeting.created_by_id:
                try:
                    from app.config import settings as _settings
                    from app.models.calendar_preference import CalendarPreferences
                    from app.services.google_calendar_service import GoogleCalendarService

                    gcal_q = await db.execute(
                        select(Integration).where(
                            Integration.user_id == meeting.created_by_id,
                            Integration.platform == IntegrationPlatform.GOOGLE_CALENDAR,
                            Integration.is_active == True,
                        )
                    )
                    gcal_int = gcal_q.scalar_one_or_none()

                    if gcal_int:
                        prefs_q = await db.execute(
                            select(CalendarPreferences).where(
                                CalendarPreferences.user_id == meeting.created_by_id
                            )
                        )
                        prefs = prefs_q.scalar_one_or_none()

                        if meeting.scheduled_at and (prefs is None or prefs.auto_sync_meetings):
                            duration_min = meeting.duration_minutes or 60
                            end_dt = meeting.scheduled_at + timedelta(minutes=duration_min)
                            frontend_url = _settings.FRONTEND_URL or "http://localhost:3000"
                            meeting_url = f"{frontend_url}/dashboard/meetings/{meeting.id}"
                            summary_snippet = ""
                            if meeting.summary:
                                summary_snippet = (
                                    meeting.summary[:300] + "..."
                                    if len(meeting.summary) > 300
                                    else meeting.summary
                                )
                            description = (
                                f"{summary_snippet}\n\nView transcript: {meeting_url}"
                                if summary_snippet
                                else f"View transcript: {meeting_url}"
                            )
                            event_body = {
                                "summary": f"[MEETING] {meeting.title}",
                                "description": description,
                                "start": {
                                    "dateTime": meeting.scheduled_at.isoformat(),
                                    "timeZone": "UTC",
                                },
                                "end": {
                                    "dateTime": end_dt.isoformat(),
                                    "timeZone": "UTC",
                                },
                                "reminders": {"useDefault": True},
                                "conferenceData": {
                                    "createRequest": {
                                        "requestId": f"synkro-{meeting.id}",
                                        "conferenceSolutionKey": {"type": "hangoutsMeet"},
                                    }
                                },
                            }
                            gcal_params = {"conferenceDataVersion": 1}
                            svc = GoogleCalendarService.from_integration(gcal_int)
                            try:
                                if meeting.calendar_event_id:
                                    cal_result = await svc.update_event(
                                        "primary",
                                        meeting.calendar_event_id,
                                        event_body,
                                        params=gcal_params,
                                    )
                                else:
                                    cal_result = await svc.create_event(
                                        "primary", event_body, params=gcal_params
                                    )
                                # Google processes conferenceData asynchronously —
                                # hangoutLink may be absent in the create response.
                                if not cal_result.get("hangoutLink") and cal_result.get("id"):
                                    await asyncio.sleep(2)
                                    cal_result = await svc.get_event("primary", cal_result["id"])
                                meeting.calendar_event_id = cal_result.get("id")
                                meet_link = cal_result.get("hangoutLink")
                                if meet_link:
                                    meeting.google_meet_link = meet_link
                                await db.commit()
                                logger.info(
                                    f"[Meeting {meeting_id}] Synced to Google Calendar "
                                    f"event={meeting.calendar_event_id} meet={meet_link}"
                                )
                            finally:
                                await svc.aclose()

                        if prefs and prefs.auto_sync_actions:
                            actions_q = await db.execute(
                                select(ActionItem).where(
                                    ActionItem.meeting_id == meeting_id,
                                    ActionItem.deadline_mentioned.is_not(None),
                                    ActionItem.calendar_event_id.is_(None),
                                )
                            )
                            for item in actions_q.scalars().all():
                                try:
                                    from app.tasks.integration_tasks import sync_action_item_to_calendar
                                    sync_action_item_to_calendar.delay(item.id, meeting.created_by_id)
                                except Exception as item_err:
                                    logger.warning(
                                        f"[Meeting {meeting_id}] Action item {item.id} "
                                        f"calendar sync enqueue failed: {item_err}"
                                    )
                except Exception as cal_err:
                    logger.warning(
                        f"[Meeting {meeting_id}] Calendar sync failed (non-fatal): {cal_err}"
                    )

    except Exception as e:
        logger.error(f"[Meeting {meeting_id}] Processing failed: {str(e)}", exc_info=True)
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

        if tmp_file_path and os.path.exists(tmp_file_path):
            try:
                os.unlink(tmp_file_path)
            except Exception:
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


@router.post("/{meeting_id}/upload", response_model=MeetingUploadResponse)
async def upload_recording_to_meeting(
    meeting_id: str,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Upload a recording file to an existing AWAITING_UPLOAD meeting.

    Attaches the file, transitions the meeting to PROCESSING, and enqueues
    the transcription pipeline. The meeting must belong to the current user's
    team and must be in AWAITING_UPLOAD (or FAILED) status.
    """
    result = await db.execute(
        select(Meeting).where(
            and_(
                Meeting.id == meeting_id,
                Meeting.team_id == current_user.team_id,
            )
        )
    )
    meeting = result.scalar_one_or_none()

    if not meeting:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Meeting not found")

    if meeting.status not in (MeetingStatus.AWAITING_UPLOAD, MeetingStatus.FAILED):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Meeting is in '{meeting.status.value}' status — only awaiting_upload or failed meetings can receive a new file",
        )

    file_ext = os.path.splitext(file.filename or "")[1].lower()
    if file_ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported file format. Allowed: {', '.join(ALLOWED_EXTENSIONS)}",
        )

    content = await file.read()
    if len(content) == 0:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="File is empty")
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File too large. Maximum: {MAX_FILE_SIZE // (1024 * 1024)}MB",
        )

    try:
        storage = get_storage()
        with tempfile.NamedTemporaryFile(delete=False, suffix=file_ext) as tmp:
            tmp.write(content)
            tmp_path = tmp.name

        with open(tmp_path, "rb") as f:
            recording_url = await storage.upload_file(
                f,
                file.filename or f"recording{file_ext}",
                folder="meetings",
                content_type=file.content_type,
            )
        os.unlink(tmp_path)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Upload failed: {exc}",
        )

    meeting.recording_url = recording_url
    meeting.status = MeetingStatus.PROCESSING
    meeting.transcript = None
    meeting.summary = None
    meeting.diarized_transcript = None
    await db.commit()

    logger.info("Recording attached to meeting %s — queuing pipeline", meeting_id)
    background_tasks.add_task(process_meeting_background, meeting_id)

    return {
        "id": meeting.id,
        "title": meeting.title,
        "status": meeting.status.value,
        "message": "Recording uploaded! Transcription starting...",
    }


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

    # Track which fields changed before applying updates
    calendar_relevant = {"scheduled_at", "title", "duration_minutes"}
    update_data = meeting_update.model_dump(exclude_unset=True)
    old_scheduled_at = meeting.scheduled_at
    calendar_fields_changed = bool(calendar_relevant & set(update_data.keys()))

    for field, value in update_data.items():
        setattr(meeting, field, value)

    await db.commit()
    await db.refresh(meeting)

    # Sync to Google Calendar if meeting time/title changed, or if scheduled_at was
    # just set for the first time (creates the initial calendar event with Meet link)
    if calendar_fields_changed and meeting.scheduled_at:
        try:
            gcal_q = await db.execute(
                select(Integration).where(
                    Integration.user_id == current_user.id,
                    Integration.platform == IntegrationPlatform.GOOGLE_CALENDAR,
                    Integration.is_active == True,
                )
            )
            gcal_int = gcal_q.scalar_one_or_none()
            if gcal_int:
                from app.tasks.integration_tasks import sync_meeting_to_calendar
                sync_meeting_to_calendar.delay(meeting.id, current_user.id)
                logger.info(
                    "update_meeting: queued GCal sync for meeting %s (event %s)",
                    meeting.id, meeting.calendar_event_id,
                )
        except Exception as exc:
            logger.error("update_meeting: GCal sync failed for meeting %s: %s", meeting_id, exc)

    # Load relationships
    await db.refresh(meeting, ["action_items"])

    return meeting


@router.patch("/{meeting_id}/speaker-names", response_model=MeetingResponse)
async def update_speaker_names(
    meeting_id: str,
    body: SpeakerNamesUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Persist custom display names for speakers in a meeting.

    Accepts a mapping of generic labels to human names:
    {"Speaker A": "Alice", "Speaker B": "Bob"}
    """
    import json

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

    meeting.speaker_names = json.dumps(body.speaker_names)
    await db.commit()
    await db.refresh(meeting)
    await db.refresh(meeting, ["action_items"])

    return meeting


@router.get("/{meeting_id}/export", response_class=PlainTextResponse)
async def export_transcript(
    meeting_id: str,
    format: str = Query("txt", pattern="^(txt|summary)$"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Export meeting transcript or summary as plain text.

    - format=txt     (default) — full speaker-labeled transcript
    - format=summary — AI-generated summary
    """
    result = await db.execute(
        select(Meeting).where(
            and_(Meeting.id == meeting_id, Meeting.team_id == current_user.team_id)
        )
    )
    meeting = result.scalar_one_or_none()

    if not meeting:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Meeting not found")

    if format == "summary":
        content = meeting.summary or "No summary available."
        filename = f"{meeting.title}_summary.txt"
    else:
        content = meeting.transcript or "No transcript available."
        filename = f"{meeting.title}_transcript.txt"

    return PlainTextResponse(
        content=content,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


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

    # Delete associated Google Calendar event if one exists
    if meeting.calendar_event_id:
        try:
            gcal_q = await db.execute(
                select(Integration).where(
                    Integration.user_id == current_user.id,
                    Integration.platform == IntegrationPlatform.GOOGLE_CALENDAR,
                    Integration.is_active == True,
                )
            )
            gcal_int = gcal_q.scalar_one_or_none()
            if gcal_int:
                from app.services.google_calendar_service import GoogleCalendarService
                svc = GoogleCalendarService.from_integration(gcal_int)
                try:
                    await svc.delete_event("primary", meeting.calendar_event_id)
                    logger.info("delete_meeting: removed GCal event %s", meeting.calendar_event_id)
                finally:
                    await svc.aclose()
        except Exception as exc:
            logger.warning("delete_meeting: GCal event deletion failed: %s", exc)

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

    if meeting.status == MeetingStatus.PROCESSING:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Meeting is already being processed"
        )

    if not meeting.recording_url:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No recording file found for this meeting"
        )

    # Reset for reprocessing
    meeting.status = MeetingStatus.PROCESSING
    meeting.transcript = None
    meeting.summary = None
    meeting.diarized_transcript = None
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
    from app.models import Task, TaskStatus, TaskPriority, TaskSourceType

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

    if action_item.status.value == "converted":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Action item already converted to task"
        )

    # Create task from action item
    new_task = Task(
        title=action_item.description[:500],  # Truncate if needed
        description=action_item.description,
        status=TaskStatus.TODO,
        priority=TaskPriority.MEDIUM,  # Default priority
        due_date=action_item.deadline_mentioned,
        team_id=current_user.team_id,
        created_by_id=current_user.id,
        source_type=TaskSourceType.MEETING,
        source_id=meeting_id
    )

    # Try to assign to mentioned person
    if action_item.assignee_mentioned:
        # Look up user by name or email
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

    # Update action item status
    action_item.status = "converted"
    action_item.task_id = new_task.id
    await db.commit()

    return {"task_id": new_task.id, "message": "Action item converted to task successfully"}


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


@router.post("/{meeting_id}/generate-meet-link", response_model=MeetingResponse)
async def generate_meet_link(
    meeting_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create (or refresh) a Google Meet link for a meeting via Google Calendar."""
    result = await db.execute(
        select(Meeting).where(
            and_(Meeting.id == meeting_id, Meeting.team_id == current_user.team_id)
        )
    )
    meeting = result.scalar_one_or_none()
    if not meeting:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Meeting not found")

    gcal_q = await db.execute(
        select(Integration).where(
            Integration.user_id == current_user.id,
            Integration.platform == IntegrationPlatform.GOOGLE_CALENDAR,
            Integration.is_active == True,
        )
    )
    gcal_int = gcal_q.scalar_one_or_none()
    if not gcal_int:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Google Calendar is not connected. Connect it in Settings first.",
        )

    from app.services.google_calendar_service import GoogleCalendarService
    from app.config import settings as _settings

    # Use scheduled_at if set, otherwise now + 1 h as a placeholder
    start_dt = meeting.scheduled_at or datetime.utcnow()
    duration_min = meeting.duration_minutes or 60
    end_dt = start_dt + timedelta(minutes=duration_min)
    frontend_url = _settings.FRONTEND_URL or "http://localhost:3000"
    meeting_url = f"{frontend_url}/dashboard/meetings/{meeting.id}"

    event_body = {
        "summary": f"[MEETING] {meeting.title}",
        "description": f"View in Synkro: {meeting_url}",
        "start": {"dateTime": start_dt.isoformat(), "timeZone": "UTC"},
        "end": {"dateTime": end_dt.isoformat(), "timeZone": "UTC"},
        "reminders": {"useDefault": True},
        "conferenceData": {
            "createRequest": {
                "requestId": f"synkro-{meeting.id}",
                "conferenceSolutionKey": {"type": "hangoutsMeet"},
            }
        },
    }
    gcal_params = {"conferenceDataVersion": 1}
    svc = GoogleCalendarService.from_integration(gcal_int)
    try:
        if meeting.calendar_event_id:
            cal_result = await svc.update_event(
                "primary", meeting.calendar_event_id, event_body, params=gcal_params
            )
        else:
            cal_result = await svc.create_event("primary", event_body, params=gcal_params)

        if not cal_result.get("hangoutLink") and cal_result.get("id"):
            await asyncio.sleep(2)
            cal_result = await svc.get_event("primary", cal_result["id"])

        meeting.calendar_event_id = cal_result.get("id") or meeting.calendar_event_id
        meet_link = cal_result.get("hangoutLink")
        if meet_link:
            meeting.google_meet_link = meet_link
        await db.commit()
    finally:
        await svc.aclose()

    if not meeting.google_meet_link:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Google Calendar created the event but did not return a Meet link. Try again in a moment.",
        )

    await db.refresh(meeting, ["action_items"])
    return meeting


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
