# Google Meet Auto-Generation for Meeting Tasks — Implementation Plan

> **Status (2026-05-16):** All phases (1–11) implemented and committed. Migration 010 must be run before the backend starts.
> Run: `alembic upgrade head` from the `backend/` directory.
>
> **Phase 12 (2026-05-16):** Meeting fields added to Edit Task Dialog — toggle, date/time, duration, and Meet link display.
> **Phase 13 (2026-05-16):** Meeting time + duration shown on task card ("May 20, 10:00 AM · 60 min") in blue with a video icon.
> **Phase 14 (2026-05-16):** Assignee added as Google Calendar attendee when a meeting task is created, updated, or a Meet link is manually generated.

## Overview

When a task is identified as meeting-related (via keyword detection or explicit flag), Synkro should automatically generate a Google Meet link by creating a Google Calendar event with conference data. The link is stored on the task and surfaced prominently in the UI.

---

## Current State

| Item | Status |
|---|---|
| `meetings.google_meet_link` field | ✅ Exists |
| `tasks.google_meet_link` field | ✅ Added (migration 010) |
| Meet link generation for audio meetings | ✅ Working |
| Meet link generation for tasks | ✅ Implemented |
| Google Calendar OAuth flow | ✅ Complete |
| Task → Calendar event sync | ✅ Working (no conferenceData) |
| Auto-detect banner in Create Task dialog | ✅ Implemented |
| "Schedule as meeting" toggle | ✅ Implemented |
| Meeting date/duration fields | ✅ Implemented |
| "Join Meeting" button on task card | ✅ Implemented |
| Copy Meet link button | ✅ Implemented |
| Manual generate endpoint | ✅ `POST /api/tasks/{id}/generate-meet-link` |
| Celery fallback task | ✅ `generate_meet_link_for_task` |
| Meeting fields in Edit Task Dialog | ✅ Toggle, date/time, duration, Meet link display |
| Meeting time on task card | ✅ Blue "May 20, 10:00 AM · 60 min" chip with video icon |
| Calendar attendees | ✅ Assignee email added to Calendar event on create / update / generate |

---

## Architecture Overview

```
User creates task with "meeting" in title
           │
           ▼
   Keyword / explicit flag detection
           │
           ├─ is_meeting_task = True
           │
           ▼
  Google Calendar connected?
           │
    Yes ───┤
           ▼
  Create Calendar event with conferenceData
  (conferenceSolutionKey: "hangoutsMeet")
           │
           ▼
  Extract hangoutLink from API response
           │
           ▼
  Store google_meet_link + calendar_event_id on task
           │
           ▼
  Return task with Meet link in response
           │
           ▼
  Frontend shows "Join Meeting" button + copy link
```

---

## Phase 1 — Database Migration

**New file:** `backend/alembic/versions/010_add_meeting_fields_to_tasks.py`

Add four columns to the `tasks` table:

| Column | Type | Default | Purpose |
|---|---|---|---|
| `is_meeting_task` | Boolean | False | Flags task as a scheduled meeting |
| `google_meet_link` | VARCHAR(500) | NULL | Auto-generated Google Meet URL |
| `meeting_scheduled_at` | DateTime | NULL | Meeting start time (separate from `due_date`) |
| `meeting_duration_minutes` | Integer | 60 | Meeting length for calendar event |

---

## Phase 2 — Task Model Update

**File:** `backend/app/models/task.py`

Add the four new columns to the `Task` SQLAlchemy model alongside the existing `calendar_event_id` and `calendar_synced_at` fields.

---

## Phase 3 — Schema Updates

**File:** `backend/app/schemas/task.py`

- `CreateTaskRequest`: add `is_meeting_task: bool = False`, `meeting_scheduled_at: Optional[datetime]`, `meeting_duration_minutes: int = 60`
- `UpdateTaskRequest`: add same optional fields
- `TaskResponse`: expose `is_meeting_task`, `google_meet_link`, `meeting_scheduled_at`, `meeting_duration_minutes`

---

## Phase 4 — Meeting Detection Logic

**File:** `backend/app/services/google_calendar_service.py`

New utility function `is_meeting_related(title: str) -> bool`:

```python
MEETING_KEYWORDS = {
    "meeting", "standup", "stand-up", "sync", "call",
    "review", "demo", "presentation", "interview",
    "conference", "session", "discussion", "1:1", "one-on-one"
}

def is_meeting_related(title: str) -> bool:
    lower = title.lower()
    return any(kw in lower for kw in MEETING_KEYWORDS)
```

Detection priority:
1. **Explicit** — user sets `is_meeting_task=True` in the request body
2. **Auto-detected** — title contains any keyword above (sets `is_meeting_task=True` automatically)
3. **Manual override** — dedicated endpoint to generate a link for any existing task

---

## Phase 5 — Meet Link Generation Service Method

**File:** `backend/app/services/google_calendar_service.py`

New async method `create_task_meeting_event(task, timezone) -> tuple[str, str]`:

```python
async def create_task_meeting_event(self, task, timezone: str) -> tuple[str, str]:
    start = task.meeting_scheduled_at or task.due_date
    end   = start + timedelta(minutes=task.meeting_duration_minutes or 60)

    event = {
        "summary": f"[MEETING] {task.title}",
        "description": task.description or "",
        "start": {"dateTime": start.isoformat(), "timeZone": timezone},
        "end":   {"dateTime": end.isoformat(),   "timeZone": timezone},
        "conferenceData": {
            "createRequest": {
                "requestId": f"synkro-task-{task.id}",
                "conferenceSolutionKey": {"type": "hangoutsMeet"}
            }
        }
    }

    response = await self.create_event(
        "primary", event, params={"conferenceDataVersion": 1}
    )
    event_id  = response.get("id", "")
    meet_link = response.get("hangoutLink", "")

    # Poll once if link not immediately present
    if not meet_link:
        await asyncio.sleep(2)
        updated   = await self.get_event("primary", event_id)
        meet_link = updated.get("hangoutLink", "")

    return event_id, meet_link
```

---

## Phase 6 — Router Updates

**File:** `backend/app/routers/tasks.py`

### `create_task()` changes

```
1. Detect is_meeting_task (explicit flag OR keyword auto-detect on title)
2. If is_meeting_task AND Google Calendar integration active:
   → call create_task_meeting_event()
   → set task.google_meet_link, task.calendar_event_id
3. Else if auto_sync_tasks preference is on:
   → existing task_to_event() flow (no Meet link)
```

### `update_task()` changes

```
1. If task becomes a meeting task (is_meeting_task toggled on):
   → generate Meet link (same as create flow)
2. If already a meeting task + meeting_scheduled_at / duration changed:
   → update existing calendar event
3. If is_meeting_task toggled off:
   → delete calendar event if exists, clear google_meet_link
```

### New endpoint

```
POST /api/tasks/{task_id}/generate-meet-link
```

- Manual trigger for any existing task
- Requires Google Calendar to be connected
- Returns updated task with `google_meet_link`
- Use case: user created a task before connecting Google Calendar, or wants to add a Meet link later

---

## Phase 7 — Celery Fallback Task

**File:** `backend/app/tasks/integration_tasks.py`

New task `generate_meet_link_for_task(task_id, user_id)`:

- Async fallback if inline generation in the router fails (timeout, API flakiness)
- Queued automatically if `create_task_meeting_event()` raises an exception
- Retries up to 3 times with exponential backoff
- On success: updates `task.google_meet_link` and `task.calendar_event_id` in DB

---

## Phase 8 — Frontend Types

**File:** `frontend/types/index.ts`

Add to the `Task` interface:

```typescript
is_meeting_task: boolean
google_meet_link: string | null
meeting_scheduled_at: string | null
meeting_duration_minutes: number
```

---

## Phase 9 — Frontend API Client

**File:** `frontend/lib/api.ts`

- Update `createTask()` and `updateTask()` to pass new fields in request body
- Add new method:

```typescript
generateMeetLink: (taskId: string): Promise<Task> =>
  api.post(`/tasks/${taskId}/generate-meet-link`).then(r => r.data)
```

---

## Phase 10 — Task Creation Dialog

**File:** `frontend/app/dashboard/tasks/page.tsx`

### Changes

1. **Auto-detect banner** — as the user types the task title, check against meeting keywords client-side. If matched, show a non-intrusive banner:
   > _"This looks like a meeting — generate a Google Meet link?"_ `[Yes]` `[No]`

2. **Explicit toggle** — "Schedule as Meeting" checkbox always visible in the form

3. **Conditional meeting fields** — revealed when meeting mode is on:
   - Meeting date + time picker → `meeting_scheduled_at`
   - Duration dropdown: 15 / 30 / 45 / 60 / 90 / 120 min → `meeting_duration_minutes`

4. **Google Calendar gating** — if the user has not connected Google Calendar, show:
   > _"Connect Google Calendar in Settings to auto-generate a Meet link"_

5. **Post-submit loading state** — spinner with label _"Generating Meet link..."_ while the API request resolves

---

## Phase 11 — Task Card / Detail Display

**Files:** Task card component + task detail/modal view

### Task card

- Show a green **"Join Meeting"** button (video camera icon) on any task where `google_meet_link` is populated
- Button opens the Meet URL in a new tab

### Task detail / modal

- Prominent Meet link section at the top of the detail pane
- Clickable URL label
- Copy-to-clipboard button
- If `is_meeting_task` is true but `google_meet_link` is null (Calendar not connected or generation failed):
  - Show a muted **"Generate Meet Link"** button that calls `POST /api/tasks/{id}/generate-meet-link`

---

## Phase 12 — Meeting Fields in Edit Task Dialog

**File:** `frontend/app/dashboard/tasks/page.tsx` (`EditTaskDialog` component)

The original Edit Task Dialog had no meeting-related fields. Phase 12 closes this gap:

1. **State initialisation** — `isMeetingTask`, `meetingScheduledAt`, `meetingDuration` seeded from the task prop so existing values are shown on open.

2. **"Schedule as meeting" checkbox** — lets users toggle `is_meeting_task` on an existing task. Toggling **on** will trigger Meet link generation via the existing backend logic in `update_task()`; toggling **off** deletes the calendar event and clears the link.

3. **Existing Meet link banner** — if `task.google_meet_link` is populated, a green read-only info bar shows at the bottom of the form with an **Open** link and a **Copy** clipboard button.

4. **Meeting date/time + duration fields** — the same blue panel used in `CreateTaskDialog`, revealed when the checkbox is checked. Fields: `datetime-local` input for `meeting_scheduled_at` and a duration dropdown (15 / 30 / 45 / 60 / 90 / 120 min).

5. **Scrollable dialog** — dialog now uses `max-h-[90vh] flex flex-col` + `overflow-y-auto` on the content area, matching `CreateTaskDialog`, so it doesn't overflow on small screens with all fields visible.

6. **Payload** — `handleSubmit` sends `is_meeting_task`, `meeting_duration_minutes`, and `meeting_scheduled_at` (null when meeting mode is off) on every save.

---

## Phase 13 — Meeting Time on Task Card

**File:** `frontend/app/dashboard/tasks/page.tsx` (task card metadata row)

Before this phase, a meeting task with a scheduled time showed only the Meet link — there was no way to see *when* the meeting was from the task list.

### Logic (three cases)

| Condition | Display |
|---|---|
| `meeting_scheduled_at` is set | Blue video icon + `"May 20, 10:00 AM · 60 min"` |
| `is_meeting_task` true but no `meeting_scheduled_at`, has `due_date` | Blue video icon + `"May 20 · 60 min"` (falls back to due date) |
| Not a meeting task, has `due_date` | Original due date display (overdue-aware, red if past) |

The meeting time chip is blue (`text-blue-600`) with a `Video` icon so it's visually distinct from the regular due-date chip. Duration is only appended when `meeting_duration_minutes` is non-null.

Also added: `import { format } from 'date-fns'` to the page for the `MMM d, h:mm a` format pattern.

---

## Phase 14 — Calendar Attendees

**Files:** `backend/app/services/google_calendar_service.py`, `backend/app/routers/tasks.py`

Before this phase, Google Calendar events were created with no attendees — the assignee never received an invite.

### Service change (`google_calendar_service.py`)

`create_task_meeting_event()` gains an optional `attendee_emails: Optional[List[str]] = None` parameter. When non-empty, an `"attendees"` array is added to the event body before the API call:

```python
if attendee_emails:
    event_body["attendees"] = [{"email": e} for e in attendee_emails]
```

Google Calendar automatically sends an invite email to each attendee.

### Router changes (`tasks.py`)

Three call sites updated:

| Endpoint | How email is resolved |
|---|---|
| `create_task()` | `assignee` User object already fetched during validation — `assignee.email` used directly |
| `update_task()` | `SELECT User.email WHERE User.id = task.assignee_id` query added before the GCal sync block |
| `generate_meet_link()` | Task loaded with `selectinload(Task.assignee)` — `task.assignee.email` used directly |

The inline `update_event` path inside `update_task()` (when the event already exists and time changes) also gains `"attendees"` in its event body for consistency.

All three paths are no-ops when the task has no assignee.

---

## End-to-End Flow

```
1. User types "Sprint planning meeting" in Create Task dialog
2. Client-side keyword detection fires →
   banner: "This looks like a meeting — generate a Google Meet link?"
3. User clicks Yes; sets meeting time: May 20, 10:00 AM, 60 min
4. User submits form → POST /api/tasks
5. Backend:
   a. is_meeting_task auto-detected = True (or set explicitly)
   b. Checks for active Google Calendar integration
   c. Calls GoogleCalendarService.create_task_meeting_event()
   d. Google Calendar API creates event with conferenceData
   e. Response includes hangoutLink
   f. Stores task.calendar_event_id + task.google_meet_link
6. API response: { ...task, google_meet_link: "https://meet.google.com/abc-xyz-123" }
7. Frontend:
   a. Task card shows green "Join Meeting" button
   b. Click → opens Meet in new tab
   c. Copy button → URL in clipboard
```

---

## File Change Summary

| File | Change | Status |
|---|---|---|
| `backend/alembic/versions/010_add_meeting_fields_to_tasks.py` | New migration — 4 columns on tasks | ✅ Done |
| `backend/app/models/task.py` | 4 new SQLAlchemy model fields + Boolean import | ✅ Done |
| `backend/app/schemas/task.py` | New request/response fields + meeting_scheduled_at validators | ✅ Done |
| `backend/app/services/google_calendar_service.py` | `is_meeting_related()` + `create_task_meeting_event()` | ✅ Done |
| `backend/app/routers/tasks.py` | Detection in create/update + `POST /{id}/generate-meet-link` endpoint | ✅ Done |
| `backend/app/tasks/integration_tasks.py` | `generate_meet_link_for_task` Celery fallback task | ✅ Done |
| `frontend/types/index.ts` | Extended `Task` interface with 4 new fields | ✅ Done |
| `frontend/lib/api.ts` | `generateMeetLink()` method added to `taskApi` | ✅ Done |
| `frontend/components/create-task-dialog.tsx` | Auto-detect banner, meeting toggle, date/duration fields, loading state | ✅ Done |
| `frontend/app/dashboard/tasks/page.tsx` | "Join Meeting" green button, copy button, "Generate Meet Link" fallback | ✅ Done |
| `frontend/app/dashboard/tasks/page.tsx` | **Phase 12:** Meeting toggle, date/time, duration + Meet link display in Edit Task Dialog | ✅ Done |
| `frontend/app/dashboard/tasks/page.tsx` | **Phase 13:** Meeting time + duration chip on task card (blue, video icon) | ✅ Done |
| `backend/app/services/google_calendar_service.py` | **Phase 14:** `attendee_emails` param on `create_task_meeting_event()` | ✅ Done |
| `backend/app/routers/tasks.py` | **Phase 14:** Assignee email resolved + passed at all three call sites | ✅ Done |
