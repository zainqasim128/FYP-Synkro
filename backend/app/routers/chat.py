"""AI Chat interface - natural language queries about tasks and meetings"""
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, func
from sqlalchemy.orm import selectinload
from pydantic import BaseModel
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional

from app.database import get_db
from app.models import User, Task, Meeting, TaskStatus
from app.models.user import UserRole
from app.dependencies import get_current_user
from app.services.ai_service import chat_query_enhanced

router = APIRouter(prefix="/api/chat", tags=["AI Chat"])

ADMIN_ROLES = {UserRole.ADMIN}


class ChatMessage(BaseModel):
    role: str   # "user" | "assistant"
    content: str


class ChatQueryRequest(BaseModel):
    message: str
    history: List[ChatMessage] = []


class ChatQueryResponse(BaseModel):
    response: str
    context_used: Dict[str, Any]
    suggested_actions: List[Dict[str, str]] = []


def _now() -> datetime:
    return datetime.utcnow()


def _detect_intent(query: str) -> Dict[str, bool]:
    """Score each domain by keyword presence in the query."""
    q = query.lower()

    task_words = [
        "task", "tasks", "work", "working", "assigned", "assign", "todo",
        "to-do", "doing", "progress", "plate", "complete", "done", "blocked",
        "pending", "backlog", "ticket", "issue", "story", "sprint", "feature",
        "bug", "fix", "finish", "deliver", "show", "list", "what is",
        "what are", "has", "have",
    ]
    team_words = [
        "team", "who", "member", "everyone", "all tasks", "workload",
        "balance", "busiest", "most tasks", "least tasks", "assigned to",
        "teammate", "colleague", "everybody",
    ]
    meeting_words = [
        "meeting", "meetings", "decided", "discussed", "summary", "transcript",
        "action item", "standup", "sprint review", "retro", "retrospective",
        "decision", "notes", "recap", "last meeting", "recent meeting",
    ]
    stats_words = [
        "how many", "count", "total", "number", "stats", "statistics",
        "overview", "breakdown", "status", "report", "summary",
    ]

    return {
        "wants_tasks": any(w in q for w in task_words) or any(w in q for w in stats_words),
        "wants_team": any(w in q for w in team_words),
        "wants_meetings": any(w in q for w in meeting_words),
        "wants_stats": any(w in q for w in stats_words),
        "wants_overdue": any(w in q for w in ["overdue", "late", "past due", "missed"]),
        "wants_own": any(w in q for w in ["my ", "mine", " i ", "me ", "plate", "i have", "i need", "i am", "i'm"]),
        "wants_today": "today" in q,
        "wants_week": any(w in q for w in ["week", "this week", "weekly", "7 days"]),
        "wants_high_priority": any(w in q for w in ["high", "urgent", "critical", "important", "asap"]),
        "wants_blocked": any(w in q for w in ["blocked", "blocker", "stuck", "cannot proceed"]),
        "wants_in_progress": any(w in q for w in ["in progress", "in-progress", "working on", "ongoing", "current"]),
    }


async def _detect_mentioned_member(
    query: str, current_user: User, db: AsyncSession
) -> Optional[User]:
    """
    Admin only: detect if the query names a specific team member.
    Matches on first name or full name, case-insensitive.
    Returns the matched User, or None.
    """
    members_result = await db.execute(
        select(User).where(User.team_id == current_user.team_id)
    )
    members = members_result.scalars().all()

    q_lower = query.lower()
    for member in members:
        if member.id == current_user.id:
            continue  # skip self — "my tasks" is handled separately
        first_name = member.full_name.split()[0].lower()
        full_name = member.full_name.lower()
        if first_name in q_lower or full_name in q_lower:
            return member
    return None


@router.post("/query", response_model=ChatQueryResponse)
async def send_chat_query(
    request: ChatQueryRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Send a natural language query to the Synkro AI assistant.

    - Admins see all team tasks and can query any team member by name.
    - Non-admin users see only their own tasks.
    - Supports multi-turn conversation via the `history` field.
    """
    intent = _detect_intent(request.message)
    is_admin = current_user.role in ADMIN_ROLES

    # Admin: check if the query names a specific team member
    mentioned_member: Optional[User] = None
    if is_admin:
        mentioned_member = await _detect_mentioned_member(
            request.message, current_user, db
        )

    context = await build_context(
        request.message, intent, current_user, db, is_admin, mentioned_member
    )
    response_text = await chat_query_enhanced(
        request.message, context, request.history, current_user
    )
    suggested = build_suggested_actions(intent, context, is_admin)

    return {
        "response": response_text,
        "context_used": context,
        "suggested_actions": suggested,
    }


# ---------------------------------------------------------------------------
# Context builders
# ---------------------------------------------------------------------------

async def build_context(
    raw_query: str,
    intent: Dict[str, bool],
    user: User,
    db: AsyncSession,
    is_admin: bool,
    mentioned_member: Optional[User],
) -> Dict[str, Any]:
    ctx: Dict[str, Any] = {
        "requesting_user": {
            "id": user.id,
            "name": user.full_name,
            "email": user.email,
            "role": user.role.value,
            "is_admin": is_admin,
        }
    }

    # Always include a lightweight personal snapshot (counts only)
    ctx["my_task_snapshot"] = await get_my_task_snapshot(user, db)

    wants_task_detail = (
        intent["wants_tasks"]
        or intent["wants_stats"]
        or intent["wants_overdue"]
        or intent["wants_blocked"]
        or intent["wants_in_progress"]
        or intent["wants_today"]
        or intent["wants_week"]
        or intent["wants_high_priority"]
        or mentioned_member is not None  # any name mention implies task query
    )

    # ── Admin: query about a specific named team member ──────────────────────
    if is_admin and mentioned_member is not None:
        # Fetch that member's tasks directly — this is the primary context
        ctx["specific_member_tasks"] = await get_member_tasks(
            mentioned_member, db, intent
        )
        # Also load team workload so admin can compare
        ctx["team_workload"] = await get_team_workload(user, db)

    # ── Admin: general team-wide query (no specific name, but "team" keyword) ─
    elif is_admin and intent["wants_team"]:
        ctx["team_workload"] = await get_team_workload(user, db)
        if wants_task_detail:
            ctx["all_team_tasks"] = await get_all_team_tasks(user, db, intent)

    # ── Admin: task query not scoped to self and no specific name mentioned ───
    elif is_admin and wants_task_detail and not intent["wants_own"]:
        ctx["all_team_tasks"] = await get_all_team_tasks(user, db, intent)

    # ── Personal task detail (admin asking about self, or any non-admin) ─────
    if wants_task_detail and (intent["wants_own"] or not is_admin):
        ctx["my_tasks"] = await get_my_tasks_detailed(user, db, intent)

    # ── Meetings context (available to everyone) ──────────────────────────────
    if intent["wants_meetings"]:
        ctx["meetings"] = await get_meetings_context(user, db)

    return ctx


# ---------------------------------------------------------------------------
# Data fetchers
# ---------------------------------------------------------------------------

async def get_my_task_snapshot(user: User, db: AsyncSession) -> Dict[str, Any]:
    """Quick count of the current user's tasks by status."""
    counts_result = await db.execute(
        select(Task.status, func.count(Task.id))
        .where(Task.assignee_id == user.id)
        .group_by(Task.status)
    )
    counts = {row[0].value: row[1] for row in counts_result}

    overdue_result = await db.execute(
        select(func.count(Task.id)).where(
            and_(
                Task.assignee_id == user.id,
                Task.due_date < _now(),
                Task.status != TaskStatus.DONE,
            )
        )
    )
    overdue = overdue_result.scalar() or 0

    return {
        "todo": counts.get("todo", 0),
        "in_progress": counts.get("in_progress", 0),
        "done": counts.get("done", 0),
        "blocked": counts.get("blocked", 0),
        "overdue": overdue,
        "total_active": (
            counts.get("todo", 0)
            + counts.get("in_progress", 0)
            + counts.get("blocked", 0)
        ),
    }


async def get_my_tasks_detailed(
    user: User, db: AsyncSession, intent: Dict[str, bool]
) -> Dict[str, Any]:
    """Detailed personal task list, filtered by intent keywords."""
    filters = [Task.assignee_id == user.id]
    _apply_intent_filters(filters, intent)

    q = (
        select(Task)
        .where(and_(*filters))
        .options(selectinload(Task.creator))
        .order_by(Task.due_date.asc().nullslast(), Task.created_at.desc())
        .limit(30)
    )
    result = await db.execute(q)
    tasks = result.scalars().all()

    task_list = [_format_task(t, show_assignee=False) for t in tasks]
    if intent["wants_high_priority"] and not intent["wants_blocked"] and not intent["wants_in_progress"]:
        task_list = [t for t in task_list if t["priority"] in ("high", "urgent")]

    return {
        "tasks": task_list,
        "count": len(task_list),
        "filter_applied": _describe_filter(intent),
    }


async def get_member_tasks(
    member: User, db: AsyncSession, intent: Dict[str, bool]
) -> Dict[str, Any]:
    """
    Admin use: fetch all tasks for a specific named team member.
    Includes a per-status snapshot so the AI can give counts too.
    """
    filters = [Task.assignee_id == member.id]
    _apply_intent_filters(filters, intent)

    q = (
        select(Task)
        .where(and_(*filters))
        .options(selectinload(Task.creator))
        .order_by(Task.due_date.asc().nullslast(), Task.created_at.desc())
        .limit(50)
    )
    result = await db.execute(q)
    tasks = result.scalars().all()

    task_list = [_format_task(t, show_assignee=False) for t in tasks]
    if intent["wants_high_priority"] and not intent["wants_blocked"] and not intent["wants_in_progress"]:
        task_list = [t for t in task_list if t["priority"] in ("high", "urgent")]

    # Status snapshot for this member
    counts_result = await db.execute(
        select(Task.status, func.count(Task.id))
        .where(Task.assignee_id == member.id)
        .group_by(Task.status)
    )
    counts = {row[0].value: row[1] for row in counts_result}

    overdue_result = await db.execute(
        select(func.count(Task.id)).where(
            and_(
                Task.assignee_id == member.id,
                Task.due_date < _now(),
                Task.status != TaskStatus.DONE,
            )
        )
    )

    return {
        "member_name": member.full_name,
        "member_email": member.email,
        "member_role": member.role.value,
        "snapshot": {
            "todo": counts.get("todo", 0),
            "in_progress": counts.get("in_progress", 0),
            "done": counts.get("done", 0),
            "blocked": counts.get("blocked", 0),
            "overdue": overdue_result.scalar() or 0,
            "total_active": (
                counts.get("todo", 0)
                + counts.get("in_progress", 0)
                + counts.get("blocked", 0)
            ),
        },
        "tasks": task_list,
        "count": len(task_list),
        "filter_applied": _describe_filter(intent),
    }


async def get_all_team_tasks(
    user: User, db: AsyncSession, intent: Dict[str, bool]
) -> Dict[str, Any]:
    """Admin only: all team tasks with assignee names, filtered by intent."""
    filters = [Task.team_id == user.team_id]
    _apply_intent_filters(filters, intent)

    q = (
        select(Task)
        .where(and_(*filters))
        .options(selectinload(Task.assignee), selectinload(Task.creator))
        .order_by(Task.due_date.asc().nullslast(), Task.created_at.desc())
        .limit(50)
    )
    result = await db.execute(q)
    tasks = result.scalars().all()

    task_list = [_format_task(t, show_assignee=True) for t in tasks]
    if intent["wants_high_priority"] and not intent["wants_blocked"] and not intent["wants_in_progress"]:
        task_list = [t for t in task_list if t["priority"] in ("high", "urgent")]

    # Group by assignee for easier reading by the AI
    by_assignee: Dict[str, list] = {}
    for t in task_list:
        name = t.get("assignee") or "Unassigned"
        by_assignee.setdefault(name, []).append(t)

    return {
        "tasks": task_list,
        "count": len(task_list),
        "by_assignee": by_assignee,
        "filter_applied": _describe_filter(intent),
    }


async def get_team_workload(user: User, db: AsyncSession) -> List[Dict[str, Any]]:
    """Admin only: per-member active task count and overdue count."""
    members_result = await db.execute(
        select(User).where(User.team_id == user.team_id)
    )
    members = members_result.scalars().all()

    workload = []
    for m in members:
        active_res = await db.execute(
            select(func.count(Task.id)).where(
                and_(Task.assignee_id == m.id, Task.status != TaskStatus.DONE)
            )
        )
        overdue_res = await db.execute(
            select(func.count(Task.id)).where(
                and_(
                    Task.assignee_id == m.id,
                    Task.due_date < _now(),
                    Task.status != TaskStatus.DONE,
                )
            )
        )
        workload.append({
            "name": m.full_name,
            "email": m.email,
            "role": m.role.value,
            "active_tasks": active_res.scalar() or 0,
            "overdue_tasks": overdue_res.scalar() or 0,
        })

    workload.sort(key=lambda x: x["active_tasks"], reverse=True)
    return workload


async def get_meetings_context(user: User, db: AsyncSession) -> Dict[str, Any]:
    """Recent completed team meetings with summaries and action items."""
    meetings_result = await db.execute(
        select(Meeting)
        .where(
            and_(
                Meeting.team_id == user.team_id,
                Meeting.status == "completed",
            )
        )
        .options(selectinload(Meeting.action_items))
        .order_by(Meeting.created_at.desc())
        .limit(5)
    )
    meetings = meetings_result.scalars().all()

    meeting_list = []
    for m in meetings:
        action_items = [
            {
                "description": ai.description,
                "assignee": ai.assignee_mentioned,
                "deadline": (
                    ai.deadline_mentioned.strftime("%Y-%m-%d")
                    if ai.deadline_mentioned
                    else None
                ),
                "status": ai.status.value,
                "context_type": ai.context_type,
            }
            for ai in (m.action_items or [])
        ]
        meeting_list.append({
            "id": m.id,
            "title": m.title,
            "date": m.created_at.strftime("%Y-%m-%d"),
            "duration_minutes": m.duration_minutes,
            "summary": m.summary[:1200] if m.summary else None,
            "action_items": action_items,
            "action_items_count": len(action_items),
        })

    return {
        "recent_meetings": meeting_list,
        "total": len(meeting_list),
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _apply_intent_filters(filters: list, intent: Dict[str, bool]) -> None:
    """Mutate a filters list with time/status constraints from intent."""
    if intent["wants_overdue"]:
        filters.append(Task.due_date < _now())
        filters.append(Task.status != TaskStatus.DONE)
    elif intent["wants_today"]:
        today_end = _now().replace(hour=23, minute=59, second=59)
        filters.append(Task.due_date <= today_end)
        filters.append(Task.status != TaskStatus.DONE)
    elif intent["wants_week"]:
        week_end = _now() + timedelta(days=7)
        filters.append(Task.due_date <= week_end)
        filters.append(Task.status != TaskStatus.DONE)

    if intent["wants_blocked"]:
        filters.append(Task.status == TaskStatus.BLOCKED)
    elif intent["wants_in_progress"]:
        filters.append(Task.status == TaskStatus.IN_PROGRESS)


def _format_task(task: Task, show_assignee: bool) -> Dict[str, Any]:
    now = _now()
    is_overdue = (
        task.due_date is not None
        and task.due_date < now
        and task.status != TaskStatus.DONE
    )
    d: Dict[str, Any] = {
        "id": task.id,
        "title": task.title,
        "description": task.description[:200] if task.description else None,
        "status": task.status.value,
        "priority": task.priority.value,
        "due_date": task.due_date.strftime("%Y-%m-%d") if task.due_date else None,
        "is_overdue": is_overdue,
        "source": task.source_type.value,
        "created_by": task.creator.full_name if task.creator else None,
    }
    if show_assignee:
        d["assignee"] = task.assignee.full_name if task.assignee else "Unassigned"
        d["assignee_email"] = task.assignee.email if task.assignee else None
    return d


def _describe_filter(intent: Dict[str, bool]) -> str:
    parts = []
    if intent["wants_overdue"]:
        parts.append("overdue")
    elif intent["wants_today"]:
        parts.append("due today")
    elif intent["wants_week"]:
        parts.append("due this week")
    if intent["wants_blocked"]:
        parts.append("blocked")
    elif intent["wants_in_progress"]:
        parts.append("in-progress")
    if intent["wants_high_priority"]:
        parts.append("high/urgent priority")
    return ", ".join(parts) if parts else "all statuses"


def build_suggested_actions(
    intent: Dict[str, bool],
    context: Dict[str, Any],
    is_admin: bool,
) -> List[Dict[str, str]]:
    suggestions = []
    snapshot = context.get("my_task_snapshot", {})

    if snapshot.get("overdue", 0) > 0:
        suggestions.append({
            "action": "view_overdue",
            "label": f"View my {snapshot['overdue']} overdue task(s)",
            "url": "/dashboard/tasks",
        })

    if snapshot.get("in_progress", 0) > 0:
        suggestions.append({
            "action": "view_in_progress",
            "label": f"View my {snapshot['in_progress']} in-progress task(s)",
            "url": "/dashboard/tasks",
        })

    if snapshot.get("blocked", 0) > 0:
        suggestions.append({
            "action": "view_blocked",
            "label": f"View my {snapshot['blocked']} blocked task(s)",
            "url": "/dashboard/tasks",
        })

    if is_admin:
        suggestions.append({
            "action": "view_analytics",
            "label": "Team workload analytics",
            "url": "/dashboard/analytics",
        })

    if "meetings" in context and context["meetings"]["total"] > 0:
        latest = context["meetings"]["recent_meetings"][0]
        suggestions.append({
            "action": "view_meeting",
            "label": f"Open: {latest['title'][:35]}",
            "url": f"/dashboard/meetings/{latest['id']}",
        })

    suggestions.append({
        "action": "create_task",
        "label": "Create a new task",
        "url": "/dashboard/tasks?action=create",
    })

    return suggestions[:4]
