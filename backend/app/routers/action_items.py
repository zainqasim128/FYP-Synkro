"""Action items router — cross-meeting view for the current team."""
from fastapi import APIRouter, Depends, Query, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from typing import Optional

from app.database import get_db
from app.models import ActionItem, Meeting, User
from app.dependencies import get_current_user

router = APIRouter(prefix="/api/action-items", tags=["Action Items"])


@router.get("")
async def list_action_items(
    status: Optional[str] = Query(None, description="pending | converted | rejected"),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return all action items for the current team, newest first.

    Joins through meetings so team isolation is enforced at query level.
    """
    base = (
        select(ActionItem, Meeting.title.label("meeting_title"))
        .join(Meeting, ActionItem.meeting_id == Meeting.id)
        .where(Meeting.team_id == current_user.team_id)
    )

    if status:
        valid = {"pending", "converted", "rejected"}
        if status not in valid:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"status must be one of {valid}",
            )
        base = base.where(ActionItem.status == status)

    count_result = await db.execute(
        select(func.count()).select_from(base.subquery())
    )
    total = count_result.scalar_one()

    offset = (page - 1) * per_page
    rows_result = await db.execute(
        base.order_by(ActionItem.created_at.desc()).offset(offset).limit(per_page)
    )
    rows = rows_result.all()

    items = []
    for row in rows:
        ai: ActionItem = row[0]
        meeting_title: str = row[1]
        items.append({
            "id": ai.id,
            "description": ai.description,
            "assignee_mentioned": ai.assignee_mentioned,
            "deadline_mentioned": (
                ai.deadline_mentioned.isoformat() if ai.deadline_mentioned else None
            ),
            "confidence_score": ai.confidence_score,
            "status": ai.status.value if hasattr(ai.status, "value") else ai.status,
            "task_id": ai.task_id,
            "meeting_id": ai.meeting_id,
            "meeting_title": meeting_title,
            "created_at": ai.created_at.isoformat() if ai.created_at else None,
            "speaker_label": ai.speaker_label,
            "assigned_by": ai.assigned_by,
            "context_type": ai.context_type,
        })

    return {"items": items, "total": total, "page": page, "per_page": per_page}
