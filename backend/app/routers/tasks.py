"""Task management endpoints - CRUD operations and statistics"""
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_, or_
from sqlalchemy.orm import selectinload
from typing import List, Optional
from datetime import datetime

from app.database import get_db
from app.models import Task, User, TaskStatus, Integration, IntegrationPlatform
from app.schemas.task import TaskCreate, TaskUpdate, TaskResponse, TaskStats
from app.dependencies import get_current_user

router = APIRouter(prefix="/api/tasks", tags=["Tasks"])


@router.get("", response_model=List[TaskResponse])
async def get_tasks(
    status: Optional[str] = None,
    priority: Optional[str] = None,
    assignee_id: Optional[str] = None,
    due_before: Optional[datetime] = None,
    due_after: Optional[datetime] = None,
    limit: int = Query(default=20, le=100),
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
    # Build query - only show tasks from user's team
    query = select(Task).where(Task.team_id == current_user.team_id)

    # Apply filters
    if status:
        query = query.where(Task.status == status)

    if priority:
        query = query.where(Task.priority == priority)

    if assignee_id:
        query = query.where(Task.assignee_id == assignee_id)

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

    # Convert to response model with nested objects
    task_responses = []
    for task in tasks:
        task_dict = {
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
                "avatar_url": task.assignee.avatar_url
            } if task.assignee else None,
            "creator": {
                "id": task.creator.id,
                "full_name": task.creator.full_name,
                "email": task.creator.email
            } if task.creator else None
        }
        task_responses.append(task_dict)

    return task_responses


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

    # Fire-and-forget: sync to Jira if the user has an active integration
    try:
        from app.tasks.integration_tasks import sync_task_to_jira, notify_slack_task_created
        jira_result = await db.execute(
            select(Integration).where(
                Integration.user_id == current_user.id,
                Integration.platform == IntegrationPlatform.JIRA,
                Integration.is_active == True,
            )
        )
        if jira_result.scalar_one_or_none():
            sync_task_to_jira.delay(new_task.id, current_user.id)
        notify_slack_task_created.delay(new_task.id, current_user.id)
    except Exception:
        pass  # Don't fail task creation if background tasks can't be queued

    # Load relationships
    await db.refresh(new_task, ["assignee", "creator"])

    return new_task


@router.get("/stats", response_model=TaskStats)
async def get_task_stats(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Get task statistics for the current user's team.

    Returns counts by status, overdue count, and completion rate.
    """
    # Count tasks by status
    result = await db.execute(
        select(
            Task.status,
            func.count(Task.id).label("count")
        ).where(
            Task.team_id == current_user.team_id
        ).group_by(Task.status)
    )
    status_counts = {row[0].value: row[1] for row in result}

    # Count overdue tasks
    result = await db.execute(
        select(func.count(Task.id)).where(
            and_(
                Task.team_id == current_user.team_id,
                Task.due_date < datetime.utcnow(),
                Task.status != TaskStatus.DONE
            )
        )
    )
    overdue_count = result.scalar() or 0

    # Calculate totals
    total = sum(status_counts.values())
    todo = status_counts.get("todo", 0)
    in_progress = status_counts.get("in_progress", 0)
    done = status_counts.get("done", 0)
    blocked = status_counts.get("blocked", 0)

    # Calculate completion rate
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
    result = await db.execute(
        select(Task).where(
            and_(
                Task.id == task_id,
                Task.team_id == current_user.team_id
            )
        ).options(
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

    return task


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
    """
    # Get existing task
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
        # Task not yet in Jira — enqueue creation
        try:
            from app.tasks.integration_tasks import sync_task_to_jira
            sync_task_to_jira.delay(task.id, current_user.id)
        except Exception:
            pass

    # Load relationships
    await db.refresh(task, ["assignee", "creator"])

    return task


@router.delete("/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_task(
    task_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Delete a task.

    Only tasks from the user's team can be deleted.
    """
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

    await db.delete(task)
    await db.commit()

    return None
