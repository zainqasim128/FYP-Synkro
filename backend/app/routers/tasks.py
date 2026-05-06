"""Task management endpoints - CRUD operations and statistics"""
import logging

from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_, or_
from sqlalchemy.orm import selectinload
from typing import List, Optional
from datetime import datetime

from app.database import get_db
from app.models import Task, User, TaskStatus, Integration, IntegrationPlatform
from app.models.user import UserRole
from app.schemas.task import TaskCreate, TaskUpdate, TaskResponse, TaskStats
from app.dependencies import get_current_user

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/tasks", tags=["Tasks"])

MANAGEMENT_ROLES = {UserRole.ADMIN}


def _task_to_dict(task: Task) -> dict:
    return {
        "id": task.id,
        "title": task.title,
        "description": task.description,
        "status": task.status.value,
        "priority": task.priority.value,
        "due_date": task.due_date,
        "estimated_hours": task.estimated_hours,
        "assignee_id": task.assignee_id,
        "created_by_id": task.created_by_id,
        "team_id": task.team_id,
        "source_type": task.source_type.value,
        "source_id": task.source_id,
        "external_id": task.external_id,
        "created_at": task.created_at,
        "updated_at": task.updated_at,
        "assignee": {
            "id": task.assignee.id,
            "full_name": task.assignee.full_name,
            "email": task.assignee.email,
            "avatar_url": task.assignee.avatar_url,
        } if task.assignee else None,
        "creator": {
            "id": task.creator.id,
            "full_name": task.creator.full_name,
            "email": task.creator.email,
        } if task.creator else None,
    }


@router.get("", response_model=List[TaskResponse])
async def get_tasks(
    status: Optional[str] = None,
    priority: Optional[str] = None,
    assignee_id: Optional[str] = None,
    due_before: Optional[datetime] = None,
    due_after: Optional[datetime] = None,
    limit: int = Query(default=20, le=200),
    offset: int = Query(default=0, ge=0),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Get tasks with optional filters.

    Query parameters:
    - **status**: Filter by status (todo, in_progress, done, blocked)
    - **priority**: Filter by priority (low, medium, high, urgent)
    - **assignee_id**: Filter by assignee user ID
    - **due_before**: Filter tasks due before this datetime
    - **due_after**: Filter tasks due after this datetime
    - **limit**: Maximum number of results (default 20, max 100)
    - **offset**: Number of results to skip for pagination
    """
    is_manager = current_user.role in MANAGEMENT_ROLES

    # Build query - only show tasks from user's team
    query = select(Task).where(Task.team_id == current_user.team_id)

    # Non-management roles can only see tasks assigned to them
    if not is_manager:
        query = query.where(Task.assignee_id == current_user.id)
    else:
        # Managers can filter by assignee
        if assignee_id == "unassigned":
            query = query.where(Task.assignee_id == None)
        elif assignee_id:
            query = query.where(Task.assignee_id == assignee_id)

    if status:
        query = query.where(Task.status == status)

    if priority:
        query = query.where(Task.priority == priority)

    if due_before:
        query = query.where(Task.due_date <= due_before)

    if due_after:
        query = query.where(Task.due_date >= due_after)

    # Order by created_at descending
    query = query.order_by(Task.created_at.desc())

    # Apply pagination
    query = query.limit(limit).offset(offset)

    # Load relationships
    query = query.options(
        selectinload(Task.assignee),
        selectinload(Task.creator)
    )

    # Execute query
    result = await db.execute(query)
    tasks = result.scalars().all()

    return [_task_to_dict(t) for t in tasks]


@router.post("", response_model=TaskResponse, status_code=status.HTTP_201_CREATED)
async def create_task(
    task_data: TaskCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Create a new task.

    Required:
    - **title**: Task title

    Optional:
    - **description**: Task description
    - **status**: Task status (default: todo)
    - **priority**: Task priority (default: medium)
    - **assignee_id**: User ID to assign task to
    - **due_date**: Task due date
    - **estimated_hours**: Estimated hours to complete
    """
    # Validate assignee is in same team if provided
    if task_data.assignee_id:
        result = await db.execute(
            select(User).where(
                and_(
                    User.id == task_data.assignee_id,
                    User.team_id == current_user.team_id
                )
            )
        )
        assignee = result.scalar_one_or_none()
        if not assignee:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Assignee not found or not in your team"
            )

    # Strip timezone from due_date — DB column is TIMESTAMP WITHOUT TIME ZONE
    due_date = task_data.due_date
    if due_date is not None and hasattr(due_date, 'tzinfo') and due_date.tzinfo is not None:
        due_date = due_date.replace(tzinfo=None)

    # Create new task
    new_task = Task(
        title=task_data.title,
        description=task_data.description,
        status=task_data.status,
        priority=task_data.priority,
        due_date=due_date,
        estimated_hours=task_data.estimated_hours,
        assignee_id=task_data.assignee_id,
        created_by_id=current_user.id,
        team_id=current_user.team_id,
        source_type=task_data.source_type,
        source_id=task_data.source_id
    )

    db.add(new_task)
    await db.commit()
    await db.refresh(new_task)

    # Sync to Jira directly (async-safe — avoids asyncio.run() nested loop issue)
    try:
        from app.services.jira_service import JiraService
        import logging as _logging
        _jlog = _logging.getLogger(__name__)
        # Find Jira integration for any team member (not just current user)
        team_user_ids_result = await db.execute(
            select(User.id).where(User.team_id == current_user.team_id)
        )
        team_user_ids = [row[0] for row in team_user_ids_result.all()]
        jira_int_result = await db.execute(
            select(Integration).where(
                Integration.user_id.in_(team_user_ids),
                Integration.platform == IntegrationPlatform.JIRA,
                Integration.is_active == True,
            ).limit(1)
        )
        jira_int = jira_int_result.scalar_one_or_none()
        if jira_int:
            project_key = (jira_int.platform_metadata or {}).get("project_key", "PROJ")
            due_str = new_task.due_date.strftime("%Y-%m-%d") if new_task.due_date else None
            jira = JiraService.from_integration(jira_int)
            try:
                sprint_id = await jira.get_active_sprint_id(project_key)
                jira_result = await jira.create_issue(
                    project_key=project_key,
                    summary=new_task.title,
                    description=new_task.description,
                    priority=new_task.priority.value if new_task.priority else "medium",
                    duedate=due_str,
                    sprint_id=sprint_id,
                )
                new_task.external_id = jira_result.get("id")
                await db.commit()
                _jlog.info("Jira issue created: %s for task %s (sprint=%s)", jira_result.get("key"), new_task.id, sprint_id)
            finally:
                await jira.aclose()
    except Exception as _e:
        logger.error("Jira sync failed for task %s: %s", new_task.id, _e)

    # Sync to Google Calendar if user has GCal connected and task has a due date
    if new_task.due_date:
        try:
            from app.config import settings as _s
            gcal_result = await db.execute(
                select(Integration).where(
                    Integration.user_id == current_user.id,
                    Integration.platform == IntegrationPlatform.GOOGLE_CALENDAR,
                    Integration.is_active == True,
                )
            )
            gcal_int = gcal_result.scalar_one_or_none()
            if gcal_int:
                from app.services.google_calendar_service import GoogleCalendarService
                assignee_name = "Unassigned"
                if new_task.assignee:
                    assignee_name = new_task.assignee.full_name
                user_tz = getattr(current_user, 'timezone', None) or "UTC"
                event_body = GoogleCalendarService.task_to_event(new_task, assignee_name, _s.FRONTEND_URL, user_timezone=user_tz)
                svc = GoogleCalendarService.from_integration(gcal_int)
                try:
                    event = await svc.create_event("primary", event_body)
                    new_task.calendar_event_id = event.get("id")
                    new_task.calendar_synced_at = datetime.utcnow()
                    await db.commit()
                    logger.info("create_task: synced task %s → GCal event %s", new_task.id, new_task.calendar_event_id)
                finally:
                    await svc.aclose()
        except Exception as exc:
            logger.error("create_task: GCal sync failed for task %s: %s", new_task.id, exc)

    # Load relationships
    result = await db.execute(
        select(Task).where(Task.id == new_task.id).options(
            selectinload(Task.assignee),
            selectinload(Task.creator)
        )
    )
    new_task = result.scalar_one()

    return _task_to_dict(new_task)


@router.get("/stats", response_model=TaskStats)
async def get_task_stats(
    assignee_id: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Get task statistics.

    - Managers: team-wide stats by default; can filter by assignee_id.
    - Others: always scoped to their own tasks only.
    """
    is_manager = current_user.role in MANAGEMENT_ROLES
    base_filter = [Task.team_id == current_user.team_id]

    if not is_manager:
        base_filter.append(Task.assignee_id == current_user.id)
    elif assignee_id:
        base_filter.append(Task.assignee_id == assignee_id)

    # Count tasks by status
    result = await db.execute(
        select(
            Task.status,
            func.count(Task.id).label("count")
        ).where(and_(*base_filter)).group_by(Task.status)
    )
    status_counts = {row[0].value: row[1] for row in result}

    # Count overdue tasks
    result = await db.execute(
        select(func.count(Task.id)).where(
            and_(
                *base_filter,
                Task.due_date < datetime.utcnow(),
                Task.status != TaskStatus.DONE
            )
        )
    )
    overdue_count = result.scalar() or 0

    total = sum(status_counts.values())
    todo = status_counts.get("todo", 0)
    in_progress = status_counts.get("in_progress", 0)
    done = status_counts.get("done", 0)
    blocked = status_counts.get("blocked", 0)
    completion_rate = (done / total * 100) if total > 0 else 0.0

    return {
        "total": total,
        "todo": todo,
        "in_progress": in_progress,
        "done": done,
        "blocked": blocked,
        "overdue": overdue_count,
        "completion_rate": round(completion_rate, 2)
    }


@router.get("/{task_id}", response_model=TaskResponse)
async def get_task(
    task_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Get a specific task by ID.

    Returns full task details with assignee and creator information.
    """
    is_manager = current_user.role in MANAGEMENT_ROLES

    conditions = [Task.id == task_id, Task.team_id == current_user.team_id]
    if not is_manager:
        conditions.append(Task.assignee_id == current_user.id)

    result = await db.execute(
        select(Task).where(and_(*conditions)).options(
            selectinload(Task.assignee),
            selectinload(Task.creator)
        )
    )
    task = result.scalar_one_or_none()

    if not task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Task not found"
        )

    return _task_to_dict(task)


@router.patch("/{task_id}", response_model=TaskResponse)
async def update_task(
    task_id: str,
    task_update: TaskUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Update a task (partial update).

    Any field can be updated independently.
    Only provided fields will be updated.
    Managers can update any team task; others can only update tasks assigned to them.
    """
    is_manager = current_user.role in MANAGEMENT_ROLES

    # Get existing task
    conditions = [Task.id == task_id, Task.team_id == current_user.team_id]
    if not is_manager:
        conditions.append(Task.assignee_id == current_user.id)

    result = await db.execute(select(Task).where(and_(*conditions)))
    task = result.scalar_one_or_none()

    if not task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Task not found"
        )

    # Non-managers cannot reassign tasks
    if not is_manager and task_update.model_dump(exclude_unset=True).get("assignee_id") is not None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only managers can reassign tasks"
        )

    # Validate assignee if being updated
    if task_update.assignee_id is not None:
        result = await db.execute(
            select(User).where(
                and_(
                    User.id == task_update.assignee_id,
                    User.team_id == current_user.team_id
                )
            )
        )
        assignee = result.scalar_one_or_none()
        if not assignee:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Assignee not found or not in your team"
            )

    # Update fields
    update_data = task_update.model_dump(exclude_unset=True)
    old_status = task.status
    for field, value in update_data.items():
        setattr(task, field, value)

    await db.commit()
    await db.refresh(task)

    # After commit, sync changes to Jira if integration is active
    if task.external_id:
        jira_result = await db.execute(
            select(Integration).where(
                Integration.user_id == current_user.id,
                Integration.platform == IntegrationPlatform.JIRA,
                Integration.is_active == True,
            )
        )
        jira_integration = jira_result.scalar_one_or_none()
        if jira_integration:
            from app.services.jira_service import JiraService
            import logging as _logging
            _logger = _logging.getLogger(__name__)
            jira = JiraService.from_integration(jira_integration)
            try:
                # Sync field changes (title, description, due_date)
                field_keys = set(update_data.keys()) - {"status"}
                if field_keys:
                    fields = {}
                    if "title" in field_keys:
                        fields["summary"] = task.title
                    if "description" in field_keys and task.description:
                        fields["description"] = task.description
                    if "due_date" in field_keys:
                        fields["duedate"] = (
                            task.due_date.strftime("%Y-%m-%d") if task.due_date else None
                        )
                        if fields["duedate"] is None:
                            fields.pop("duedate")
                    if fields:
                        await jira.update_issue_fields(task.external_id, fields)

                # Sync status change via dynamic transition lookup
                if task.status != old_status:
                    # Map internal status → likely Jira status name
                    STATUS_NAME_MAP = {
                        "todo": ["to do", "open", "backlog"],
                        "in_progress": ["in progress", "in development", "start"],
                        "done": ["done", "closed", "resolved", "complete"],
                        "blocked": ["blocked", "on hold", "impediment"],
                    }
                    target_names = STATUS_NAME_MAP.get(task.status.value, [])
                    transitions = await jira.get_transitions(task.external_id)
                    transition_id = None
                    for t in transitions:
                        t_name = t.get("name", "").lower()
                        if any(n in t_name for n in target_names):
                            transition_id = t["id"]
                            break
                    if transition_id:
                        await jira.update_issue_status(task.external_id, transition_id)
                    else:
                        _logger.info(
                            "No matching Jira transition for status %s on issue %s",
                            task.status.value,
                            task.external_id,
                        )
            except Exception as sync_err:
                _logger.error(
                    "Failed to sync Jira for task %s: %s", task.id, sync_err
                )
            finally:
                await jira.aclose()
    elif update_data:
        # Task not yet in Jira — create issue now (async-safe)
        try:
            from app.services.jira_service import JiraService
            team_uids2 = await db.execute(select(User.id).where(User.team_id == current_user.team_id))
            team_uid_list2 = [r[0] for r in team_uids2.all()]
            jira_int2_result = await db.execute(
                select(Integration).where(
                    Integration.user_id.in_(team_uid_list2),
                    Integration.platform == IntegrationPlatform.JIRA,
                    Integration.is_active == True,
                ).limit(1)
            )
            jira_int2 = jira_int2_result.scalar_one_or_none()
            if jira_int2:
                project_key2 = (jira_int2.platform_metadata or {}).get("project_key", "PROJ")
                due_str2 = task.due_date.strftime("%Y-%m-%d") if task.due_date else None
                jira2 = JiraService.from_integration(jira_int2)
                try:
                    sprint_id2 = await jira2.get_active_sprint_id(project_key2)
                    r2 = await jira2.create_issue(
                        project_key=project_key2,
                        summary=task.title,
                        description=task.description,
                        priority=task.priority.value if task.priority else "medium",
                        duedate=due_str2,
                        sprint_id=sprint_id2,
                    )
                    task.external_id = r2.get("id")
                    await db.commit()
                finally:
                    await jira2.aclose()
        except Exception:
            pass

    # Sync to Google Calendar
    try:
        from app.config import settings as _s
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
            assignee_name = "Unassigned"
            if task.assignee:
                assignee_name = task.assignee.full_name
            user_tz = getattr(current_user, 'timezone', None) or "UTC"
            if task.due_date:
                event_body = GoogleCalendarService.task_to_event(task, assignee_name, _s.FRONTEND_URL, user_timezone=user_tz)
                svc = GoogleCalendarService.from_integration(gcal_int)
                try:
                    if task.calendar_event_id:
                        await svc.update_event("primary", task.calendar_event_id, event_body)
                        logger.info("update_task: updated GCal event %s for task %s", task.calendar_event_id, task.id)
                    else:
                        event = await svc.create_event("primary", event_body)
                        task.calendar_event_id = event.get("id")
                        task.calendar_synced_at = datetime.utcnow()
                        await db.commit()
                        logger.info("update_task: created GCal event %s for task %s", task.calendar_event_id, task.id)
                finally:
                    await svc.aclose()
            elif task.calendar_event_id:
                # due_date was removed — delete the calendar event
                svc = GoogleCalendarService.from_integration(gcal_int)
                try:
                    await svc.delete_event("primary", task.calendar_event_id)
                    task.calendar_event_id = None
                    await db.commit()
                    logger.info("update_task: deleted GCal event for task %s (due_date removed)", task.id)
                finally:
                    await svc.aclose()
    except Exception as exc:
        logger.error("update_task: GCal sync failed for task %s: %s", task.id, exc)

    # Load relationships
    result = await db.execute(
        select(Task).where(Task.id == task.id).options(
            selectinload(Task.assignee),
            selectinload(Task.creator)
        )
    )
    task = result.scalar_one()

    return _task_to_dict(task)


@router.delete("/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_task(
    task_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Delete a task. Only admin can delete tasks.
    """
    if current_user.role not in MANAGEMENT_ROLES:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only managers can delete tasks"
        )

    result = await db.execute(
        select(Task).where(
            and_(
                Task.id == task_id,
                Task.team_id == current_user.team_id
            )
        )
    )
    task = result.scalar_one_or_none()

    if not task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Task not found"
        )

    # Delete associated Google Calendar event if one exists
    if task.calendar_event_id:
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
                    await svc.delete_event("primary", task.calendar_event_id)
                finally:
                    await svc.aclose()
        except Exception as exc:
            logger.warning("delete_task: GCal event deletion failed: %s", exc)

    await db.delete(task)
    await db.commit()

    return None
