"""
Google Calendar — preferences, bulk sync, and events endpoints.

Endpoints
---------
GET  /api/calendar/preferences       — get (or auto-create) user's calendar prefs
PUT  /api/calendar/preferences       — update prefs
POST /api/calendar/sync-all          — bulk-sync all user tasks with due dates
POST /api/calendar/sync-task/{id}    — manually sync a single task
GET  /api/calendar/events            — list calendar events in a date range
GET  /api/calendar/availability      — free/busy for a given date
"""

import asyncio
import logging
import uuid
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.dependencies import get_current_user
from app.models import Integration, IntegrationPlatform, Task, User
from app.models.calendar_preference import CalendarPreferences

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/calendar", tags=["Calendar"])


# ── Pydantic schemas ───────────────────────────────────────────────────────────


class CalendarPreferencesResponse(BaseModel):
    id: str
    user_id: str
    auto_sync_tasks: bool
    auto_sync_meetings: bool
    auto_sync_actions: bool
    reminder_urgent_minutes: List[int]
    reminder_high_minutes: List[int]
    reminder_medium_minutes: List[int]
    reminder_low_minutes: List[int]
    daily_digest_enabled: bool
    daily_digest_time: str
    auto_reschedule_overdue: bool

    class Config:
        from_attributes = True


class CalendarPreferencesUpdate(BaseModel):
    auto_sync_tasks: Optional[bool] = None
    auto_sync_meetings: Optional[bool] = None
    auto_sync_actions: Optional[bool] = None
    reminder_urgent_minutes: Optional[List[int]] = None
    reminder_high_minutes: Optional[List[int]] = None
    reminder_medium_minutes: Optional[List[int]] = None
    reminder_low_minutes: Optional[List[int]] = None
    daily_digest_enabled: Optional[bool] = None
    daily_digest_time: Optional[str] = None
    auto_reschedule_overdue: Optional[bool] = None


# ── Helpers ────────────────────────────────────────────────────────────────────


async def _get_or_create_prefs(user_id: str, db: AsyncSession) -> CalendarPreferences:
    result = await db.execute(
        select(CalendarPreferences).where(CalendarPreferences.user_id == user_id)
    )
    prefs = result.scalar_one_or_none()
    if prefs is None:
        prefs = CalendarPreferences(
            id=str(uuid.uuid4()),
            user_id=user_id,
        )
        db.add(prefs)
        await db.commit()
        await db.refresh(prefs)
    return prefs


async def _get_active_gcal(user_id: str, db: AsyncSession) -> Optional[Integration]:
    result = await db.execute(
        select(Integration).where(
            Integration.user_id == user_id,
            Integration.platform == IntegrationPlatform.GOOGLE_CALENDAR,
            Integration.is_active == True,
        )
    )
    return result.scalar_one_or_none()


# ── Preferences ────────────────────────────────────────────────────────────────


@router.get("/preferences", response_model=CalendarPreferencesResponse)
async def get_calendar_preferences(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CalendarPreferences:
    """Return the current user's Google Calendar sync preferences (auto-created on first call)."""
    return await _get_or_create_prefs(current_user.id, db)


@router.put("/preferences", response_model=CalendarPreferencesResponse)
async def update_calendar_preferences(
    updates: CalendarPreferencesUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CalendarPreferences:
    """Update one or more calendar preference fields."""
    prefs = await _get_or_create_prefs(current_user.id, db)
    data = updates.model_dump(exclude_unset=True)
    for field, value in data.items():
        setattr(prefs, field, value)
    prefs.updated_at = datetime.utcnow()
    await db.commit()
    await db.refresh(prefs)
    logger.info("Updated calendar preferences for user %s", current_user.id)
    return prefs


# ── Bulk sync ──────────────────────────────────────────────────────────────────


@router.post("/sync-all", summary="Bulk-sync all tasks with due dates to Google Calendar")
async def sync_all_tasks(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """Directly sync every task with a due date to Google Calendar (no Celery required)."""
    from app.models.user import User as UserModel
    from app.services.google_calendar_service import GoogleCalendarService
    from app.utils.security import encrypt_value
    import httpx

    gcal_int = await _get_active_gcal(current_user.id, db)
    if not gcal_int:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Google Calendar is not connected. Go to Settings to connect.",
        )

    # Build service and refresh token upfront (before loading tasks) so no
    # mid-loop DB commits expire the task ORM objects.
    svc = GoogleCalendarService.from_integration(gcal_int)
    try:
        await svc.verify_connection()
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 401 and svc.refresh_token:
            try:
                await svc.refresh_access_token()
                gcal_int.access_token = encrypt_value(svc.access_token)
                await db.commit()
                logger.info("sync-all: refreshed token for integration %s", gcal_int.id)
            except Exception as refresh_exc:
                await svc.aclose()
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail=f"Google Calendar token expired and refresh failed. Please reconnect in Settings. ({refresh_exc})",
                )
        elif exc.response.status_code == 403:
            await svc.aclose()
            try:
                body = exc.response.json()
                err = body.get("error", {})
                reason = err.get("errors", [{}])[0].get("reason", "")
                google_msg = err.get("message", "")
            except Exception:
                reason, google_msg = "", ""

            if reason == "accessNotConfigured":
                detail = (
                    "Google Calendar API is not enabled for this project. "
                    "Go to console.cloud.google.com → APIs & Services → Library → "
                    "search 'Google Calendar API' → Enable."
                )
            else:
                detail = (
                    f"Google Calendar API returned 403 Forbidden"
                    f"{f' (reason: {reason})' if reason else ''}"
                    f"{f': {google_msg}' if google_msg else ''}. "
                    "Ensure the Google Calendar API is enabled in your Google Cloud Console "
                    "and your Google account is added as a Test User in the OAuth consent screen."
                )
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=detail)
        else:
            await svc.aclose()
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Google Calendar API error: {exc.response.status_code}. Please reconnect in Settings.",
            )
    except Exception as exc:
        await svc.aclose()
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"Google Calendar unreachable: {exc}")

    # Load tasks AFTER any token-refresh commit so ORM objects are fresh.
    result = await db.execute(
        select(Task).where(
            Task.team_id == current_user.team_id,
            Task.due_date.is_not(None),
        )
    )
    tasks = result.scalars().all()

    # Build assignee name lookup (one query, keyed by user_id)
    user_ids = {t.assignee_id for t in tasks if t.assignee_id}
    assignee_map: dict = {}
    if user_ids:
        users_result = await db.execute(
            select(UserModel).where(UserModel.id.in_(list(user_ids)))
        )
        for u in users_result.scalars().all():
            assignee_map[u.id] = u.full_name

    synced = 0
    failed = 0
    last_error = ""

    try:
        for task in tasks:
            try:
                assignee_name = assignee_map.get(task.assignee_id, "Unassigned") if task.assignee_id else "Unassigned"
                event_body = GoogleCalendarService.task_to_event(task, assignee_name, settings.FRONTEND_URL)

                if task.calendar_event_id:
                    try:
                        await svc.update_event("primary", task.calendar_event_id, event_body)
                    except httpx.HTTPStatusError as e:
                        if e.response.status_code == 404:
                            event = await svc.create_event("primary", event_body)
                            task.calendar_event_id = event.get("id")
                        else:
                            raise
                else:
                    event = await svc.create_event("primary", event_body)
                    task.calendar_event_id = event.get("id")

                task.calendar_synced_at = datetime.utcnow()
                synced += 1

            except Exception as exc:
                last_error = str(exc)
                logger.error("sync-all: failed for task %s: %s", task.id, exc)
                failed += 1

        await db.commit()
    finally:
        await svc.aclose()

    logger.info("sync-all: synced=%d failed=%d for user %s", synced, failed, current_user.id)
    msg = f"Synced {synced} task(s) to Google Calendar."
    if failed:
        msg += f" {failed} failed — last error: {last_error}"
    return {"synced": synced, "failed": failed, "message": msg}


@router.post("/sync-task/{task_id}", summary="Manually sync a single task to Google Calendar")
async def sync_single_task(
    task_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """Force a calendar sync for a specific task."""
    gcal_int = await _get_active_gcal(current_user.id, db)
    if not gcal_int:
        raise HTTPException(
            status_code=400,
            detail="Google Calendar is not connected.",
        )

    result = await db.execute(
        select(Task).where(Task.id == task_id, Task.team_id == current_user.team_id)
    )
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    if not task.due_date:
        raise HTTPException(status_code=400, detail="Task has no due date — cannot sync to calendar")

    try:
        from app.tasks.integration_tasks import sync_task_to_calendar
        sync_task_to_calendar.delay(task.id, current_user.id)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to queue sync: {exc}")

    return {"queued": True, "task_id": task_id}


# ── Read calendar events ───────────────────────────────────────────────────────


@router.get("/events", summary="List Google Calendar events in a date range")
async def list_calendar_events(
    start: str = Query(..., description="ISO 8601 datetime, e.g. 2026-05-01T00:00:00Z"),
    end: str = Query(..., description="ISO 8601 datetime, e.g. 2026-05-31T23:59:59Z"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> List[Dict[str, Any]]:
    """Fetch events from the user's primary Google Calendar for the given range."""
    gcal_int = await _get_active_gcal(current_user.id, db)
    if not gcal_int:
        raise HTTPException(
            status_code=400,
            detail="Google Calendar is not connected.",
        )

    from app.services.google_calendar_service import GoogleCalendarService

    svc = GoogleCalendarService.from_integration(gcal_int)
    try:
        events = await svc.list_events(time_min=start, time_max=end)
    except Exception as exc:
        logger.error("list_calendar_events: error for user %s: %s", current_user.id, exc)
        raise HTTPException(status_code=500, detail=f"Failed to fetch events: {exc}")
    finally:
        await svc.aclose()

    return events


# ── Free/busy ──────────────────────────────────────────────────────────────────


@router.get("/availability", summary="Get free/busy slots for a date")
async def get_availability(
    date: str = Query(..., description="Date in YYYY-MM-DD format"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """Return busy intervals for the user's primary calendar on a given day."""
    gcal_int = await _get_active_gcal(current_user.id, db)
    if not gcal_int:
        raise HTTPException(
            status_code=400,
            detail="Google Calendar is not connected.",
        )

    try:
        day = datetime.fromisoformat(date)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date format. Use YYYY-MM-DD.")

    time_min = day.strftime("%Y-%m-%dT00:00:00Z")
    time_max = (day + timedelta(days=1)).strftime("%Y-%m-%dT00:00:00Z")

    from app.services.google_calendar_service import GoogleCalendarService

    svc = GoogleCalendarService.from_integration(gcal_int)
    try:
        freebusy = await svc.get_freebusy(time_min=time_min, time_max=time_max)
    except Exception as exc:
        logger.error("get_availability: error for user %s: %s", current_user.id, exc)
        raise HTTPException(status_code=500, detail=f"Failed to fetch free/busy: {exc}")
    finally:
        await svc.aclose()

    calendars = freebusy.get("calendars", {})
    busy_slots = calendars.get("primary", {}).get("busy", [])
    return {"date": date, "busy": busy_slots}


# ── Slot suggestions ───────────────────────────────────────────────────────────


@router.get("/suggest-slots", summary="Suggest free time slots for scheduling a task")
async def suggest_slots(
    duration_hours: float = Query(default=1.0, ge=0.25, le=8.0, description="Required slot duration in hours"),
    days_ahead: int = Query(default=7, ge=1, le=14, description="How many days ahead to search"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """Find the next 3 free time slots in the user's Google Calendar.

    Searches the 09:00–18:00 window for each day in the next ``days_ahead`` days
    and returns up to 3 slots where no existing event conflicts with the
    requested ``duration_hours``.
    """
    gcal_int = await _get_active_gcal(current_user.id, db)
    if not gcal_int:
        raise HTTPException(
            status_code=400,
            detail="Google Calendar is not connected.",
        )

    from app.services.google_calendar_service import GoogleCalendarService

    svc = GoogleCalendarService.from_integration(gcal_int)
    suggestions: List[Dict[str, Any]] = []
    duration_delta = timedelta(hours=duration_hours)
    work_start_hour = 9
    work_end_hour = 18

    try:
        base = datetime.utcnow().replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)

        for day_offset in range(days_ahead):
            if len(suggestions) >= 3:
                break

            day = (base + timedelta(days=day_offset)).date()
            day_start = datetime(day.year, day.month, day.day, work_start_hour)
            day_end = datetime(day.year, day.month, day.day, work_end_hour)

            time_min = day_start.strftime("%Y-%m-%dT%H:%M:%SZ")
            time_max = day_end.strftime("%Y-%m-%dT%H:%M:%SZ")

            try:
                freebusy = await svc.get_freebusy(time_min=time_min, time_max=time_max)
            except Exception:
                continue

            busy = freebusy.get("calendars", {}).get("primary", {}).get("busy", [])

            # Build list of busy intervals as datetime pairs
            busy_intervals = []
            for slot in busy:
                try:
                    s = datetime.fromisoformat(slot["start"].replace("Z", "+00:00")).replace(tzinfo=None)
                    e = datetime.fromisoformat(slot["end"].replace("Z", "+00:00")).replace(tzinfo=None)
                    busy_intervals.append((s, e))
                except Exception:
                    continue
            busy_intervals.sort()

            # Walk through the work window looking for a free gap
            cursor = max(day_start, base) if day_offset == 0 else day_start
            # Round cursor up to next 30-min boundary
            if cursor.minute % 30 != 0:
                cursor += timedelta(minutes=30 - cursor.minute % 30)
            cursor = cursor.replace(second=0, microsecond=0)

            while cursor + duration_delta <= day_end and len(suggestions) < 3:
                slot_end = cursor + duration_delta
                conflict = any(s < slot_end and e > cursor for s, e in busy_intervals)
                if not conflict:
                    suggestions.append({
                        "start": cursor.strftime("%Y-%m-%dT%H:%M:00"),
                        "end": slot_end.strftime("%Y-%m-%dT%H:%M:00"),
                        "label": cursor.strftime("%A, %b %d at %I:%M %p"),
                    })
                    cursor = slot_end  # skip past this slot to avoid overlapping suggestions
                else:
                    cursor += timedelta(minutes=30)

    finally:
        await svc.aclose()

    return {
        "duration_hours": duration_hours,
        "suggestions": suggestions,
        "message": (
            f"Found {len(suggestions)} free slot(s) in the next {days_ahead} days."
            if suggestions
            else "No free slots found — your calendar is fully booked in this window."
        ),
    }
