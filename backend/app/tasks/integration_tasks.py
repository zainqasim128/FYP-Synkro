"""
Celery tasks for integration sync.

sync_task_to_jira
-----------------
Creates a new Jira issue or updates an existing one from an internal Task.
Idempotent: if ``task.external_id`` is already set, it updates the issue
instead of creating a duplicate.

notify_slack_task_created
-------------------------
Posts a formatted Block Kit message to Slack when a new task is created.

Retry strategy
--------------
Both tasks use ``bind=True`` to access ``self.retry()``.  On network errors
or transient Jira/Slack failures the task is retried up to 3 times with
escalating back-off (60s, 120s, 180s).
"""

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Optional

import httpx
from sqlalchemy import select
from sqlalchemy.engine import create_engine
from sqlalchemy.orm import Session

from app.celery_app import celery_app
from app.config import settings
from app.models import Integration, IntegrationPlatform, Task

logger = logging.getLogger(__name__)

# Synchronous SQLAlchemy engine for Celery tasks (Celery does not support asyncio)
_sync_engine = create_engine(settings.database_url_sync, pool_pre_ping=True)


# ── Jira sync ──────────────────────────────────────────────────────────────────


@celery_app.task(
    bind=True,
    name="app.tasks.integration_tasks.sync_task_to_jira",
    max_retries=3,
    default_retry_delay=60,
)
def sync_task_to_jira(self, task_id: str, user_id: str) -> dict:
    """Create or update a Jira issue from an internal Task record.

    Idempotency
    -----------
    - If ``task.external_id`` is ``None``  → create a new Jira issue.
    - If ``task.external_id`` is set       → update the existing issue's
      summary, description, and due date (no duplicate created).

    Args:
        task_id : UUID of the internal :class:`Task`.
        user_id : UUID of the owning user (used to look up Jira integration).

    Returns:
        Dict with ``{"created": <jira_id>}`` or ``{"updated": <jira_id>}``
        on success, or ``{"skipped": ...}`` / ``{"error": ...}`` otherwise.
    """
    from app.services.jira_service import JiraService

    with Session(_sync_engine) as db:
        task: Optional[Task] = db.execute(
            select(Task).where(Task.id == task_id)
        ).scalar_one_or_none()

        if not task:
            logger.error("sync_task_to_jira: Task %s not found", task_id)
            return {"error": "task_not_found", "task_id": task_id}

        jira_int: Optional[Integration] = db.execute(
            select(Integration).where(
                Integration.user_id == user_id,
                Integration.platform == IntegrationPlatform.JIRA,
                Integration.is_active == True,
            )
        ).scalar_one_or_none()

        if not jira_int:
            logger.info(
                "sync_task_to_jira: no active Jira integration for user %s — skipping",
                user_id,
            )
            return {"skipped": "no_jira_integration"}

        jira = JiraService.from_integration(jira_int)
        project_key: str = jira_int.platform_metadata.get("project_key", "PROJ")
        due_str: Optional[str] = (
            task.due_date.strftime("%Y-%m-%d") if task.due_date else None
        )

        try:
            if task.external_id:
                # ── UPDATE existing issue ───────────────────────────────────
                fields = {"summary": task.title}
                if task.description:
                    fields["description"] = task.description  # auto-ADF in service
                if due_str:
                    fields["duedate"] = due_str

                asyncio.run(jira.update_issue_fields(task.external_id, fields))
                logger.info(
                    "sync_task_to_jira: updated Jira issue %s for task %s",
                    task.external_id,
                    task_id,
                )
                return {"updated": task.external_id}

            else:
                # ── CREATE new issue ────────────────────────────────────────
                result = asyncio.run(
                    jira.create_issue(
                        project_key=project_key,
                        summary=task.title,
                        description=task.description,
                        priority=task.priority.value if task.priority else "medium",
                        duedate=due_str,
                    )
                )
                task.external_id = result.get("id")
                db.commit()
                logger.info(
                    "sync_task_to_jira: created Jira issue id=%s key=%s for task %s",
                    task.external_id,
                    result.get("key"),
                    task_id,
                )
                return {
                    "created": task.external_id,
                    "key": result.get("key"),
                }

        except Exception as exc:
            logger.error(
                "sync_task_to_jira: failed for task %s (attempt %d): %s",
                task_id,
                self.request.retries + 1,
                exc,
            )
            try:
                raise self.retry(
                    exc=exc,
                    countdown=60 * (self.request.retries + 1),  # 60s / 120s / 180s
                )
            except self.MaxRetriesExceededError:
                logger.error(
                    "sync_task_to_jira: max retries exceeded for task %s", task_id
                )
                return {"error": str(exc), "task_id": task_id}


# ── Slack notification ─────────────────────────────────────────────────────────


@celery_app.task(
    bind=True,
    name="app.tasks.integration_tasks.notify_slack_task_created",
    max_retries=3,
    default_retry_delay=30,
)
def notify_slack_task_created(
    self,
    task_id: str,
    user_id: str,
    channel: Optional[str] = None,
) -> dict:
    """Post a Slack Block Kit message when a new task is created.

    Uses the workspace's bot token from the user's Slack integration.
    Sends to ``channel`` if provided, otherwise falls back to the
    ``default_channel`` stored in the integration metadata, then ``#general``.

    Args:
        task_id : UUID of the internal :class:`Task`.
        user_id : UUID of the owning user (used to look up Slack integration).
        channel : Optional override channel ID or name.

    Returns:
        ``{"ok": True, "ts": "<message_ts>"}`` on success.
    """
    from app.services.slack_service import SlackService

    with Session(_sync_engine) as db:
        task: Optional[Task] = db.execute(
            select(Task).where(Task.id == task_id)
        ).scalar_one_or_none()

        if not task:
            logger.error("notify_slack_task_created: Task %s not found", task_id)
            return {"error": "task_not_found", "task_id": task_id}

        slack_int: Optional[Integration] = db.execute(
            select(Integration).where(
                Integration.user_id == user_id,
                Integration.platform == IntegrationPlatform.SLACK,
                Integration.is_active == True,
            )
        ).scalar_one_or_none()

        if not slack_int:
            logger.info(
                "notify_slack_task_created: no active Slack integration for user %s — skipping",
                user_id,
            )
            return {"skipped": "no_slack_integration"}

        target_channel: str = (
            channel
            or slack_int.platform_metadata.get("default_channel")
            or "#general"
        )
        svc = SlackService.from_integration(slack_int)

        priority_label = task.priority.value if task.priority else "medium"
        due_label = task.due_date.strftime("%Y-%m-%d") if task.due_date else "No deadline"
        jira_label = f"  Jira: `{task.external_id}`" if task.external_id else ""

        # Fallback plain text (shown in notifications / clients without Block Kit)
        text = f":white_check_mark: New task: *{task.title}*"

        # Rich Block Kit payload
        blocks = [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": ":white_check_mark: New Task Created",
                    "emoji": True,
                },
            },
            {
                "type": "section",
                "fields": [
                    {"type": "mrkdwn", "text": f"*Title*\n{task.title}"},
                    {"type": "mrkdwn", "text": f"*Priority*\n{priority_label.capitalize()}"},
                    {"type": "mrkdwn", "text": f"*Due Date*\n{due_label}"},
                    {
                        "type": "mrkdwn",
                        "text": f"*Status*\n{task.status.value.replace('_', ' ').title()}",
                    },
                ],
            },
        ]

        if task.description:
            blocks.append(
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"*Description*\n{task.description[:500]}",
                    },
                }
            )

        if jira_label:
            blocks.append(
                {
                    "type": "context",
                    "elements": [
                        {"type": "mrkdwn", "text": f":jira:{jira_label}"}
                    ],
                }
            )

        try:
            result = asyncio.run(
                svc.post_message(target_channel, text, blocks=blocks)
            )
            logger.info(
                "notify_slack_task_created: posted to channel=%s ts=%s for task %s",
                target_channel,
                result.get("ts"),
                task_id,
            )
            return {"ok": True, "ts": result.get("ts")}

        except Exception as exc:
            logger.error(
                "notify_slack_task_created: failed for task %s (attempt %d): %s",
                task_id,
                self.request.retries + 1,
                exc,
            )
            try:
                raise self.retry(exc=exc, countdown=30 * (self.request.retries + 1))
            except self.MaxRetriesExceededError:
                logger.error(
                    "notify_slack_task_created: max retries exceeded for task %s",
                    task_id,
                )
                return {"error": str(exc), "task_id": task_id}


# ── Google Calendar sync ───────────────────────────────────────────────────────


@celery_app.task(
    bind=True,
    name="app.tasks.integration_tasks.sync_task_to_calendar",
    max_retries=3,
    default_retry_delay=60,
)
def sync_task_to_calendar(self, task_id: str, user_id: str) -> dict:
    """Create or update a Google Calendar event for a task with a due date."""
    from app.models.user import User as UserModel
    from app.services.google_calendar_service import GoogleCalendarService

    with Session(_sync_engine) as db:
        task = db.execute(select(Task).where(Task.id == task_id)).scalar_one_or_none()
        if not task:
            return {"error": "task_not_found", "task_id": task_id}
        if not task.due_date:
            return {"skipped": "no_due_date", "task_id": task_id}

        gcal_int = db.execute(
            select(Integration).where(
                Integration.user_id == user_id,
                Integration.platform == IntegrationPlatform.GOOGLE_CALENDAR,
                Integration.is_active == True,
            )
        ).scalar_one_or_none()
        if not gcal_int:
            return {"skipped": "no_gcal_integration"}

        assignee_name = "Unassigned"
        if task.assignee_id:
            assignee = db.execute(select(UserModel).where(UserModel.id == task.assignee_id)).scalar_one_or_none()
            if assignee:
                assignee_name = assignee.full_name

        cal_owner = db.execute(select(UserModel).where(UserModel.id == user_id)).scalar_one_or_none()
        user_timezone = (cal_owner.timezone if cal_owner and hasattr(cal_owner, 'timezone') and cal_owner.timezone else "UTC")

        event_body = GoogleCalendarService.task_to_event(task, assignee_name, settings.FRONTEND_URL, user_timezone=user_timezone)
        existing_event_id = task.calendar_event_id

        async def _do_sync() -> dict:
            svc = GoogleCalendarService.from_integration(gcal_int)
            try:
                if existing_event_id:
                    try:
                        return await svc.update_event("primary", existing_event_id, event_body)
                    except httpx.HTTPStatusError as exc:
                        if exc.response.status_code == 404:
                            return await svc.create_event("primary", event_body)
                        raise
                else:
                    return await svc.create_event("primary", event_body)
            finally:
                await svc.aclose()

        try:
            result = asyncio.run(_do_sync())
            task.calendar_event_id = result.get("id")
            task.calendar_synced_at = datetime.utcnow()
            db.commit()
            return {"synced": task.calendar_event_id}
        except Exception as exc:
            logger.error("sync_task_to_calendar: failed for task %s: %s", task_id, exc)
            try:
                raise self.retry(exc=exc, countdown=60 * (self.request.retries + 1))
            except self.MaxRetriesExceededError:
                return {"error": str(exc), "task_id": task_id}


@celery_app.task(
    bind=True,
    name="app.tasks.integration_tasks.delete_calendar_event",
    max_retries=2,
    default_retry_delay=30,
)
def delete_calendar_event(self, calendar_event_id: str, user_id: str, task_id: Optional[str] = None) -> dict:
    """Delete a Google Calendar event and clear calendar_event_id on the task."""
    from app.services.google_calendar_service import GoogleCalendarService

    with Session(_sync_engine) as db:
        gcal_int = db.execute(
            select(Integration).where(
                Integration.user_id == user_id,
                Integration.platform == IntegrationPlatform.GOOGLE_CALENDAR,
                Integration.is_active == True,
            )
        ).scalar_one_or_none()
        if not gcal_int:
            return {"skipped": "no_gcal_integration"}

        async def _do_delete() -> None:
            svc = GoogleCalendarService.from_integration(gcal_int)
            try:
                await svc.delete_event("primary", calendar_event_id)
            finally:
                await svc.aclose()

        try:
            asyncio.run(_do_delete())
            if task_id:
                task = db.execute(select(Task).where(Task.id == task_id)).scalar_one_or_none()
                if task:
                    task.calendar_event_id = None
                    task.calendar_synced_at = None
                    db.commit()
            return {"deleted": calendar_event_id}
        except Exception as exc:
            try:
                raise self.retry(exc=exc, countdown=30 * (self.request.retries + 1))
            except self.MaxRetriesExceededError:
                return {"error": str(exc), "event_id": calendar_event_id}


# ── Meeting calendar sync ──────────────────────────────────────────────────────


@celery_app.task(
    bind=True,
    name="app.tasks.integration_tasks.sync_meeting_to_calendar",
    max_retries=2,
    default_retry_delay=60,
)
def sync_meeting_to_calendar(self, meeting_id: str, user_id: str) -> dict:
    """Create or update a Google Calendar event for a meeting (with Google Meet link)."""
    from app.models.meeting import Meeting
    from app.services.google_calendar_service import GoogleCalendarService

    with Session(_sync_engine) as db:
        meeting = db.execute(select(Meeting).where(Meeting.id == meeting_id)).scalar_one_or_none()
        if not meeting:
            return {"error": "meeting_not_found"}
        if not meeting.scheduled_at:
            return {"skipped": "no_scheduled_at"}

        gcal_int = db.execute(
            select(Integration).where(
                Integration.user_id == user_id,
                Integration.platform == IntegrationPlatform.GOOGLE_CALENDAR,
                Integration.is_active == True,
            )
        ).scalar_one_or_none()
        if not gcal_int:
            return {"skipped": "no_gcal_integration"}

        duration_min = meeting.duration_minutes or 60
        end_dt = meeting.scheduled_at + timedelta(minutes=duration_min)
        meeting_url = f"{settings.FRONTEND_URL}/dashboard/meetings/{meeting.id}"
        summary_snippet = (meeting.summary[:300] + "...") if meeting.summary and len(meeting.summary) > 300 else (meeting.summary or "")
        description = f"{summary_snippet}\n\nView transcript: {meeting_url}" if summary_snippet else f"View transcript: {meeting_url}"

        event_body = {
            "summary": f"[MEETING] {meeting.title}",
            "description": description,
            "start": {"dateTime": meeting.scheduled_at.isoformat(), "timeZone": "UTC"},
            "end": {"dateTime": end_dt.isoformat(), "timeZone": "UTC"},
            "reminders": {"useDefault": True},
            "conferenceData": {
                "createRequest": {
                    "requestId": f"synkro-{meeting_id}",
                    "conferenceSolutionKey": {"type": "hangoutsMeet"},
                }
            },
        }

        existing_event_id = meeting.calendar_event_id

        async def _do_sync() -> dict:
            svc = GoogleCalendarService.from_integration(gcal_int)
            gcal_params = {"conferenceDataVersion": 1}
            try:
                if existing_event_id:
                    try:
                        result = await svc.update_event("primary", existing_event_id, event_body, params=gcal_params)
                    except httpx.HTTPStatusError as exc:
                        if exc.response.status_code == 404:
                            result = await svc.create_event("primary", event_body, params=gcal_params)
                        else:
                            raise
                else:
                    result = await svc.create_event("primary", event_body, params=gcal_params)
                if not result.get("hangoutLink") and result.get("id"):
                    await asyncio.sleep(2)
                    result = await svc.get_event("primary", result["id"])
                return result
            finally:
                await svc.aclose()

        try:
            result = asyncio.run(_do_sync())
            meeting.calendar_event_id = result.get("id")
            meet_link = result.get("hangoutLink")
            if meet_link:
                meeting.google_meet_link = meet_link
            db.commit()
            return {"synced": meeting.calendar_event_id, "meet_link": meet_link}
        except Exception as exc:
            logger.error("sync_meeting_to_calendar: failed for meeting %s: %s", meeting_id, exc)
            try:
                raise self.retry(exc=exc, countdown=60 * (self.request.retries + 1))
            except self.MaxRetriesExceededError:
                return {"error": str(exc), "meeting_id": meeting_id}


# ── Action item calendar sync ──────────────────────────────────────────────────


@celery_app.task(
    bind=True,
    name="app.tasks.integration_tasks.sync_action_item_to_calendar",
    max_retries=2,
    default_retry_delay=60,
)
def sync_action_item_to_calendar(self, action_item_id: str, user_id: str) -> dict:
    """Create a Google Calendar event for an action item that has a deadline."""
    from app.models.action_item import ActionItem
    from app.services.google_calendar_service import GoogleCalendarService

    with Session(_sync_engine) as db:
        item = db.execute(select(ActionItem).where(ActionItem.id == action_item_id)).scalar_one_or_none()
        if not item:
            return {"error": "action_item_not_found"}
        if not item.deadline_mentioned:
            return {"skipped": "no_deadline"}
        if item.calendar_event_id:
            return {"skipped": "already_synced", "event_id": item.calendar_event_id}

        gcal_int = db.execute(
            select(Integration).where(
                Integration.user_id == user_id,
                Integration.platform == IntegrationPlatform.GOOGLE_CALENDAR,
                Integration.is_active == True,
            )
        ).scalar_one_or_none()
        if not gcal_int:
            return {"skipped": "no_gcal_integration"}

        deadline_date = item.deadline_mentioned.strftime("%Y-%m-%d")
        next_day = (item.deadline_mentioned + timedelta(days=1)).strftime("%Y-%m-%d")
        meeting_ref = f"\nSource meeting: {settings.FRONTEND_URL}/dashboard/meetings/{item.meeting_id}" if item.meeting_id else ""
        event_body = {
            "summary": f"[ACTION] {item.description[:80]}",
            "description": f"Action item extracted from meeting.{meeting_ref}",
            "start": {"date": deadline_date},
            "end": {"date": next_day},
            "reminders": {"useDefault": False, "overrides": [{"method": "email", "minutes": 1440}]},
        }

        async def _do_sync() -> dict:
            svc = GoogleCalendarService.from_integration(gcal_int)
            try:
                return await svc.create_event("primary", event_body)
            finally:
                await svc.aclose()

        try:
            result = asyncio.run(_do_sync())
            item.calendar_event_id = result.get("id")
            db.commit()
            return {"synced": item.calendar_event_id}
        except Exception as exc:
            try:
                raise self.retry(exc=exc, countdown=60 * (self.request.retries + 1))
            except self.MaxRetriesExceededError:
                return {"error": str(exc), "action_item_id": action_item_id}


# ── Overdue task rescheduler ───────────────────────────────────────────────────


@celery_app.task(
    bind=True,
    name="app.tasks.integration_tasks.reschedule_overdue_tasks",
    max_retries=1,
    default_retry_delay=300,
)
def reschedule_overdue_tasks(self) -> dict:
    """Move overdue task calendar events to today for opted-in users.

    Runs daily at 07:00 UTC via Celery beat.
    Only acts on users with auto_reschedule_overdue=True in CalendarPreferences.
    """
    from app.models.calendar_preference import CalendarPreferences
    from app.services.google_calendar_service import GoogleCalendarService

    today = datetime.utcnow().date()
    today_str = today.strftime("%Y-%m-%d")
    tomorrow_str = (today + timedelta(days=1)).strftime("%Y-%m-%d")
    moved = 0
    skipped = 0

    with Session(_sync_engine) as db:
        opted_in = db.execute(
            select(CalendarPreferences).where(CalendarPreferences.auto_reschedule_overdue == True)
        ).scalars().all()

        for prefs in opted_in:
            try:
                gcal_int = db.execute(
                    select(Integration).where(
                        Integration.user_id == prefs.user_id,
                        Integration.platform == IntegrationPlatform.GOOGLE_CALENDAR,
                        Integration.is_active == True,
                    )
                ).scalar_one_or_none()
                if not gcal_int:
                    skipped += 1
                    continue

                overdue_tasks = db.execute(
                    select(Task).where(
                        Task.assignee_id == prefs.user_id,
                        Task.due_date < datetime.utcnow(),
                        Task.status != "done",
                        Task.calendar_event_id.is_not(None),
                    )
                ).scalars().all()

                if not overdue_tasks:
                    continue

                async def _move_events(tasks=overdue_tasks, integration=gcal_int) -> int:
                    svc = GoogleCalendarService.from_integration(integration)
                    count = 0
                    try:
                        for task in tasks:
                            try:
                                await svc.update_event("primary", task.calendar_event_id, {
                                    "start": {"date": today_str},
                                    "end": {"date": tomorrow_str},
                                })
                                count += 1
                            except Exception as exc:
                                logger.warning("reschedule_overdue_tasks: skipped task %s: %s", task.id, exc)
                    finally:
                        await svc.aclose()
                    return count

                moved += asyncio.run(_move_events())

            except Exception as exc:
                logger.error("reschedule_overdue_tasks: failed for user %s: %s", prefs.user_id, exc)

    logger.info("reschedule_overdue_tasks: moved=%d skipped=%d", moved, skipped)
    return {"moved": moved, "skipped": skipped}
