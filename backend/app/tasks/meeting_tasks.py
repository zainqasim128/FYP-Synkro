"""
Celery tasks for meeting processing.
Handles transcription, summarization, and action item extraction.
"""
import os
import tempfile
import logging
from sqlalchemy import select
from sqlalchemy.orm import Session
from sqlalchemy.engine import create_engine

from app.celery_app import celery_app
from app.config import settings
from app.models import Meeting, ActionItem, MeetingStatus, ActionItemStatus
from app.services.ai_service import (
    transcribe_meeting,
    summarize_meeting,
    extract_action_items_from_summary
)
from app.utils.storage import get_storage

# Configure logging
logger = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)


# Create sync engine for Celery tasks (Celery doesn't support async)
sync_database_url = settings.database_url_sync
engine = create_engine(sync_database_url, pool_pre_ping=True)


@celery_app.task(bind=True, name="app.tasks.meeting_tasks.transcribe_meeting_task")
def transcribe_meeting_task(self, meeting_id: str):
    """
    Transcribe meeting audio using OpenAI Whisper API.

    Steps:
    1. Fetch meeting from database
    2. Download audio from S3/Cloudinary/local storage
    3. Call Whisper API for transcription
    4. Calculate audio duration
    5. Save transcript and duration to database
    6. Update status to "transcribed"
    7. Trigger summarization task

    Args:
        meeting_id: UUID of the meeting to transcribe
    """
    logger.info(f"Starting transcription for meeting {meeting_id}")
    tmp_file_path = None

    with Session(engine) as db:
        try:
            # Fetch meeting
            result = db.execute(select(Meeting).where(Meeting.id == meeting_id))
            meeting = result.scalar_one_or_none()

            if not meeting:
                logger.error(f"Meeting {meeting_id} not found in database")
                raise ValueError(f"Meeting {meeting_id} not found")

            if not meeting.recording_url:
                logger.error(f"Meeting {meeting_id} has no recording URL")
                raise ValueError(f"Meeting {meeting_id} has no recording URL")

            logger.info(f"Meeting {meeting_id}: Recording URL = {meeting.recording_url}")

            # Update status to processing
            meeting.status = MeetingStatus.PROCESSING
            db.commit()
            logger.info(f"Meeting {meeting_id}: Status updated to PROCESSING")

            # Download audio file from storage
            storage = get_storage()

            # Extract key from URL based on storage type
            recording_url = meeting.recording_url
            if recording_url.startswith('local://'):
                # Local storage format: local://meetings/filename.mp3
                key = recording_url.replace('local://', '')
                logger.info(f"Meeting {meeting_id}: Using local storage, key = {key}")
            elif '.amazonaws.com/' in recording_url:
                # S3 format: https://bucket.s3.region.amazonaws.com/meetings/filename.mp3
                key = recording_url.split('.amazonaws.com/')[-1]
                logger.info(f"Meeting {meeting_id}: Using S3 storage, key = {key}")
            elif 'cloudinary.com' in recording_url:
                # Cloudinary format: extract path after /upload/
                key = recording_url.split('/upload/')[-1]
                logger.info(f"Meeting {meeting_id}: Using Cloudinary storage, key = {key}")
            else:
                # Fallback: try to extract path after last .com/
                key = recording_url.split('.com/')[-1] if '.com/' in recording_url else recording_url
                logger.warning(f"Meeting {meeting_id}: Unknown storage format, using fallback key = {key}")

            # Create temp file for download
            file_ext = os.path.splitext(key)[1]
            with tempfile.NamedTemporaryFile(delete=False, suffix=file_ext) as tmp_file:
                tmp_file_path = tmp_file.name

            logger.info(f"Meeting {meeting_id}: Downloading audio to {tmp_file_path}")

            # Download file
            import asyncio
            asyncio.run(storage.download_file(key, tmp_file_path))

            # Check file size
            file_size_mb = os.path.getsize(tmp_file_path) / (1024 * 1024)
            logger.info(f"Meeting {meeting_id}: Downloaded file size = {file_size_mb:.2f}MB")

            if file_size_mb > 25:
                logger.error(f"Meeting {meeting_id}: File size {file_size_mb:.2f}MB exceeds Whisper API limit of 25MB")
                raise ValueError(f"File size {file_size_mb:.2f}MB exceeds Whisper API limit of 25MB")

            # Calculate duration
            try:
                from mutagen import File as MutagenFile
                audio = MutagenFile(tmp_file_path)
                if audio is not None and hasattr(audio.info, 'length'):
                    duration_seconds = audio.info.length
                    duration_minutes = int(duration_seconds / 60)
                    meeting.duration_minutes = duration_minutes
                    logger.info(f"Meeting {meeting_id}: Duration = {duration_minutes} minutes ({duration_seconds:.1f} seconds)")
                else:
                    logger.warning(f"Meeting {meeting_id}: Could not determine audio duration")
            except Exception as duration_error:
                logger.warning(f"Meeting {meeting_id}: Failed to calculate duration: {str(duration_error)}")

            # Transcribe using Whisper
            logger.info(f"Meeting {meeting_id}: Starting Whisper API transcription")
            import asyncio
            transcript = asyncio.run(transcribe_meeting(tmp_file_path))
            logger.info(f"Meeting {meeting_id}: Transcription complete, length = {len(transcript)} characters")

            # Clean up temp file
            os.unlink(tmp_file_path)
            tmp_file_path = None
            logger.info(f"Meeting {meeting_id}: Temporary file cleaned up")

            # Save transcript
            meeting.transcript = transcript
            meeting.status = MeetingStatus.TRANSCRIBED
            db.commit()
            logger.info(f"Meeting {meeting_id}: Status updated to TRANSCRIBED")

            # Trigger summarization task
            summarize_meeting_task.delay(meeting_id)
            logger.info(f"Meeting {meeting_id}: Summarization task triggered")

            return {
                "status": "success",
                "meeting_id": meeting_id,
                "transcript_length": len(transcript),
                "duration_minutes": meeting.duration_minutes
            }

        except Exception as e:
            logger.error(f"Meeting {meeting_id}: Transcription failed - {str(e)}", exc_info=True)

            # Mark meeting as failed
            try:
                result = db.execute(select(Meeting).where(Meeting.id == meeting_id))
                meeting = result.scalar_one_or_none()
                if meeting:
                    meeting.status = MeetingStatus.FAILED
                    db.commit()
                    logger.info(f"Meeting {meeting_id}: Status updated to FAILED")
            except Exception as db_error:
                logger.error(f"Meeting {meeting_id}: Failed to update status to FAILED: {str(db_error)}")

            # Clean up temp file if exists
            if tmp_file_path and os.path.exists(tmp_file_path):
                try:
                    os.unlink(tmp_file_path)
                    logger.info(f"Meeting {meeting_id}: Temporary file cleaned up after error")
                except Exception as cleanup_error:
                    logger.error(f"Meeting {meeting_id}: Failed to clean up temp file: {str(cleanup_error)}")

            raise Exception(f"Transcription failed for meeting {meeting_id}: {str(e)}")


@celery_app.task(bind=True, name="app.tasks.meeting_tasks.summarize_meeting_task")
def summarize_meeting_task(self, meeting_id: str):
    """
    Summarize meeting transcript using GPT-4 and extract action items.

    Steps:
    1. Fetch transcript from database
    2. Call GPT-4 for summarization
    3. Extract action items from summary
    4. Save summary and action items
    5. Update status to "completed"
    6. Send notifications (optional)

    Args:
        meeting_id: UUID of the meeting to summarize
    """
    logger.info(f"Starting summarization for meeting {meeting_id}")

    with Session(engine) as db:
        try:
            # Fetch meeting
            result = db.execute(select(Meeting).where(Meeting.id == meeting_id))
            meeting = result.scalar_one_or_none()

            if not meeting:
                logger.error(f"Meeting {meeting_id} not found in database")
                raise ValueError(f"Meeting {meeting_id} not found")

            if not meeting.transcript:
                logger.error(f"Meeting {meeting_id} has no transcript")
                raise ValueError(f"Meeting {meeting_id} has no transcript")

            logger.info(f"Meeting {meeting_id}: Transcript length = {len(meeting.transcript)} characters")

            # Summarize using GPT-4
            logger.info(f"Meeting {meeting_id}: Calling GPT-4 for summarization")
            import asyncio
            summary_data = asyncio.run(
                summarize_meeting(meeting.transcript, meeting.title)
            )

            logger.info(f"Meeting {meeting_id}: Summarization complete")

            # Save summary
            meeting.summary = summary_data["summary"]
            logger.info(f"Meeting {meeting_id}: Summary length = {len(summary_data['summary'])} characters")

            # Create action items
            action_items_data = summary_data.get("action_items", [])
            logger.info(f"Meeting {meeting_id}: Found {len(action_items_data)} action items")

            created_count = 0
            skipped_count = 0

            for item_data in action_items_data:
                confidence = item_data.get("confidence", 0.0)
                description = item_data.get("description", "")

                # Only create action items with sufficient confidence
                if confidence >= 0.6:
                    action_item = ActionItem(
                        meeting_id=meeting_id,
                        description=description,
                        assignee_mentioned=item_data.get("assignee"),
                        deadline_mentioned=item_data.get("deadline"),
                        confidence_score=confidence,
                        status=ActionItemStatus.PENDING
                    )
                    db.add(action_item)
                    created_count += 1
                    logger.info(f"Meeting {meeting_id}: Created action item: {description[:50]}... (confidence: {confidence:.2f})")
                else:
                    skipped_count += 1
                    logger.info(f"Meeting {meeting_id}: Skipped low-confidence action item: {description[:50]}... (confidence: {confidence:.2f})")

            logger.info(f"Meeting {meeting_id}: Created {created_count} action items, skipped {skipped_count} low-confidence items")

            # Update meeting status
            meeting.status = MeetingStatus.COMPLETED
            db.commit()
            logger.info(f"Meeting {meeting_id}: Status updated to COMPLETED")

            # TODO: Send notifications to mentioned assignees
            # This would involve looking up users and sending emails/Slack messages

            return {
                "status": "success",
                "meeting_id": meeting_id,
                "summary_length": len(summary_data["summary"]),
                "action_items_count": created_count,
                "action_items_skipped": skipped_count
            }

        except Exception as e:
            logger.error(f"Meeting {meeting_id}: Summarization failed - {str(e)}", exc_info=True)

            # Mark meeting as failed
            try:
                result = db.execute(select(Meeting).where(Meeting.id == meeting_id))
                meeting = result.scalar_one_or_none()
                if meeting:
                    meeting.status = MeetingStatus.FAILED
                    db.commit()
                    logger.info(f"Meeting {meeting_id}: Status updated to FAILED")
            except Exception as db_error:
                logger.error(f"Meeting {meeting_id}: Failed to update status to FAILED: {str(db_error)}")

            raise Exception(f"Summarization failed for meeting {meeting_id}: {str(e)}")


@celery_app.task(name="app.tasks.meeting_tasks.process_message_for_intent")
def process_message_for_intent(message_id: str):
    """
    Process a message to classify intent and extract entities.

    This task runs for new messages from integrations (Gmail, Slack).

    Args:
        message_id: UUID of the message to process
    """
    from app.models import Message

    with Session(engine) as db:
        try:
            # Fetch message
            result = db.execute(select(Message).where(Message.id == message_id))
            message = result.scalar_one_or_none()

            if not message:
                raise ValueError(f"Message {message_id} not found")

            # Classify intent
            import asyncio
            from app.services.ai_service import classify_intent, extract_task_entities

            intent_data = asyncio.run(classify_intent(message.content))
            message.intent = intent_data["intent"]

            # If it's a task request, extract entities and create a real task
            if intent_data["intent"] == "task_request":
                entities = asyncio.run(extract_task_entities(message.content))
                message.entities = entities

                # create internal Task record from entities (Slack messages only)
                if message.platform == "slack":
                    from app.models import Integration, IntegrationPlatform, Task, TaskStatus, TaskPriority, TaskSourceType
                    from app.utils.security import decrypt_value
                    from dateutil import parser as date_parser

                    title = entities.get("title") or message.content[:100]
                    description = entities.get("description")
                    priority = entities.get("priority") or TaskPriority.MEDIUM
                    due_date = None
                    if entities.get("deadline"):
                        try:
                            due_date = date_parser.parse(entities.get("deadline"))
                        except Exception:
                            logger.warning("unable to parse deadline %s", entities.get("deadline"))

                    # Look up the user separately — Message has no .user relationship
                    from app.models.user import User as UserModel
                    msg_user = db.execute(
                        select(UserModel).where(UserModel.id == message.user_id)
                    ).scalar_one_or_none()
                    if msg_user is None or not msg_user.team_id:
                        logger.warning(
                            "Cannot create task from message %s: user %s has no team",
                            message_id, message.user_id,
                        )
                        message.processed = True
                        db.commit()
                        return {"status": "skipped", "message_id": message_id, "reason": "no_team"}

                    task = Task(
                        title=title,
                        description=description,
                        priority=priority,
                        due_date=due_date,
                        source_type=TaskSourceType.MESSAGE,
                        source_id=message.id,
                        team_id=msg_user.team_id,
                        created_by_id=message.user_id,
                    )
                    db.add(task)
                    db.flush()  # get task.id

                    # if user has an active Jira integration, sync immediately
                    jira_integration = db.execute(
                        select(Integration).where(
                            Integration.user_id == message.user_id,
                            Integration.platform == IntegrationPlatform.JIRA,
                            Integration.is_active == True,
                        )
                    ).scalar_one_or_none()

                    if jira_integration:
                        try:
                            from app.services.jira_service import JiraService, PRIORITY_MAP

                            # Decrypt the stored API token before use
                            raw_token = jira_integration.access_token
                            try:
                                raw_token = decrypt_value(raw_token)
                            except Exception:
                                pass  # fall back to raw if not encrypted

                            jira = JiraService(
                                domain=jira_integration.platform_metadata.get("domain"),
                                email=jira_integration.platform_metadata.get("email"),
                                api_token=raw_token,
                            )
                            # Map internal priority → Jira priority name
                            jira_priority = PRIORITY_MAP.get(
                                (task.priority.value if task.priority else "medium").lower(),
                                "Medium",
                            )
                            jira_payload = asyncio.run(jira.create_issue(
                                project_key=jira_integration.platform_metadata.get("project_key", "PROJ"),
                                summary=task.title,
                                description=task.description,
                                priority=task.priority.value if task.priority else "medium",
                                duedate=task.due_date.strftime("%Y-%m-%d") if task.due_date else None,
                            ))
                            task.external_id = jira_payload.get("id")
                            logger.info(
                                "Jira issue created for task %s: jira_id=%s key=%s",
                                task.id,
                                jira_payload.get("id"),
                                jira_payload.get("key"),
                            )
                        except Exception as jerr:
                            logger.error("Jira sync error for task %s: %s", task.id, jerr)

                # Create action item if confidence is high enough
                if entities.get("confidence", 0) > 0.6:
                    action_item = ActionItem(
                        message_id=message_id,
                        description=entities.get("description", message.content[:500]),
                        assignee_mentioned=entities.get("assignee"),
                        deadline_mentioned=entities.get("deadline"),
                        confidence_score=entities["confidence"],
                        status=ActionItemStatus.PENDING
                    )
                    db.add(action_item)

            # Mark as processed
            message.processed = True
            db.commit()

            return {
                "status": "success",
                "message_id": message_id,
                "intent": intent_data["intent"]
            }

        except Exception as e:
            raise Exception(f"Message processing failed for {message_id}: {str(e)}")
