"""Task comment endpoints with bidirectional Jira sync.

Routes:
  GET  /api/tasks/{task_id}/comments            — list comments
  POST /api/tasks/{task_id}/comments            — add comment (+ push to Jira if linked)
  DELETE /api/tasks/{task_id}/comments/{id}     — delete comment (author or admin only)
"""

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_user
from app.models import Integration, IntegrationPlatform, User
from app.models.task import Task as TaskModel
from app.models.task_comment import TaskComment, CommentSource

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/tasks", tags=["Comments"])


class CommentCreateRequest(BaseModel):
    body: str


def _serialize(comment: TaskComment, author_name: Optional[str] = None) -> Dict[str, Any]:
    return {
        "id": comment.id,
        "task_id": comment.task_id,
        "body": comment.body,
        "author_id": comment.author_id,
        "author_name": author_name or comment.jira_author_name,
        "jira_comment_id": comment.jira_comment_id,
        "jira_author_name": comment.jira_author_name,
        "source": comment.source.value if hasattr(comment.source, "value") else str(comment.source),
        "created_at": comment.created_at.isoformat(),
        "updated_at": comment.updated_at.isoformat() if comment.updated_at else None,
    }


async def _get_task_or_404(task_id: str, team_id: str, db: AsyncSession) -> TaskModel:
    q = await db.execute(
        select(TaskModel).where(TaskModel.id == task_id, TaskModel.team_id == team_id)
    )
    task = q.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return task


@router.get("/{task_id}/comments")
async def list_comments(
    task_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> List[Dict[str, Any]]:
    await _get_task_or_404(task_id, current_user.team_id, db)

    q = await db.execute(
        select(TaskComment)
        .where(TaskComment.task_id == task_id)
        .order_by(TaskComment.created_at)
    )
    comments = q.scalars().all()

    # Batch-load author names
    author_ids = [c.author_id for c in comments if c.author_id]
    name_map: Dict[str, str] = {}
    if author_ids:
        uq = await db.execute(select(User).where(User.id.in_(author_ids)))
        for u in uq.scalars().all():
            name_map[u.id] = u.full_name

    return [_serialize(c, name_map.get(c.author_id)) for c in comments]


@router.post("/{task_id}/comments", status_code=201)
async def add_comment(
    task_id: str,
    payload: CommentCreateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    if not payload.body.strip():
        raise HTTPException(status_code=400, detail="Comment body cannot be empty")

    task = await _get_task_or_404(task_id, current_user.team_id, db)

    comment = TaskComment(
        task_id=task_id,
        body=payload.body.strip(),
        author_id=current_user.id,
        source=CommentSource.SYNKRO,
    )
    db.add(comment)
    await db.flush()

    # Push to Jira if the task has an external_id and Jira is connected
    if task.external_id:
        int_q = await db.execute(
            select(Integration).where(
                Integration.team_id == current_user.team_id,
                Integration.platform == IntegrationPlatform.JIRA,
                Integration.is_active == True,
            )
        )
        integration = int_q.scalar_one_or_none()
        if integration:
            from app.services.jira_service import JiraService
            jira = JiraService.from_integration(integration)
            try:
                result = await jira.add_comment(task.external_id, payload.body.strip())
                comment.jira_comment_id = str(result.get("id", "")) or None
                logger.info(
                    "Comment pushed to Jira: issue=%s jira_id=%s",
                    task.external_id,
                    comment.jira_comment_id,
                )
            except Exception as exc:
                logger.warning(
                    "Failed to push comment to Jira for task %s: %s", task_id, exc
                )
            finally:
                await jira.aclose()

    await db.commit()
    await db.refresh(comment)

    # Notify task assignee and creator about the new comment (skip the commenter)
    try:
        from app.services.notification_service import create_notification
        from app.models.notification import NotificationType
        recipients = set()
        if task.assignee_id and task.assignee_id != current_user.id:
            recipients.add(task.assignee_id)
        if task.created_by_id and task.created_by_id != current_user.id:
            recipients.add(task.created_by_id)
        if recipients:
            snippet = payload.body.strip()[:100]
            for recipient_id in recipients:
                await create_notification(
                    db=db,
                    user_id=recipient_id,
                    type=NotificationType.COMMENT_ADDED,
                    title="New comment on a task",
                    body=f"{current_user.full_name}: {snippet}",
                    link="/dashboard/tasks",
                )
            await db.commit()
    except Exception as _ne:
        logger.warning("Failed to create comment notification: %s", _ne)

    return _serialize(comment, current_user.full_name)


@router.delete("/{task_id}/comments/{comment_id}", status_code=204)
async def delete_comment(
    task_id: str,
    comment_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    await _get_task_or_404(task_id, current_user.team_id, db)

    q = await db.execute(
        select(TaskComment).where(
            TaskComment.id == comment_id,
            TaskComment.task_id == task_id,
        )
    )
    comment = q.scalar_one_or_none()
    if not comment:
        raise HTTPException(status_code=404, detail="Comment not found")

    is_admin = getattr(current_user, "role", "") == "admin"
    if not is_admin and comment.author_id != current_user.id:
        raise HTTPException(status_code=403, detail="Cannot delete another user's comment")

    await db.delete(comment)
    await db.commit()
