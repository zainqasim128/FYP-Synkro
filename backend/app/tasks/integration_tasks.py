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
from typing import Optional

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
