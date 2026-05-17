# Synkro — Jira Integration Plan

## What's Already Done

### Backend — Complete
- **`jira_service.py`** — Full Jira Cloud REST API wrapper: create/read/update issues, status transitions, sprint detection, priority mapping, retry logic with exponential backoff
- **`routers/integrations.py`** — Three endpoints: `/jira/connect`, `/jira/test`, `/jira/projects`
- **`tasks.py`** — Auto-syncs task create/update to Jira inline; stores Jira issue key in `task.external_id`
- **`integration_tasks.py`** — Celery background job `sync_task_to_jira` with retries (3x, 60/120/180s backoff)
- **DB** — `integrations` table (encrypted Fernet token, metadata JSON), `tasks.external_id` column

### Frontend — Partial
- **Settings page** — Connect form (domain, email, API token, project key), connected card with sync/disconnect buttons
- **Task card** — Shows `Jira: {external_id}` in blue when linked
- **`api.ts`** — `connectJira()`, `disconnectIntegration()`, `syncIntegration()`

### What's Missing (core admin flow + bi-directional sync)
1. No post-meeting → Jira push UI — the core admin workflow
2. No Jira → Synkro (bi-directional): no webhook endpoint, no inbound sync
3. No user → Jira account mapping — tickets assign to nobody in Jira
4. No project picker dropdown in settings (endpoint exists, UI uses plain text input)
5. No Jira Sync Dashboard — admin can't see sync health, failures, or linked issues

---

## Implementation Plan

### Phase 1 — Settings: Project Picker + User Mapping ✅ DONE (2026-05-16)
**Goal:** Admin selects Jira project from dropdown and maps team members to Jira account IDs.

**Backend (complete):**
- `GET /api/integrations/jira/users` — `search_users()` in `jira_service.py`, endpoint in `routers/integrations.py`
- `PATCH /api/integrations/jira/settings` — saves `project_key` + `user_map` into `integration.metadata`
- Schemas: `JiraUser`, `JiraSettingsRequest` added to `routers/integrations.py`

**Frontend (complete):**
- `frontend/types/index.ts` — `JiraProject` and `JiraUser` interfaces added
- `frontend/lib/api.ts` — `getJiraProjects()`, `getJiraUsers()`, `updateJiraSettings()` in `integrationsApi`
- `frontend/app/dashboard/settings/page.tsx`:
  - State: `showJiraSettings`, `jiraSelectedProject`, `jiraUserMap`
  - Queries: `jira-projects`, `jira-users`, `team-members-jira` (lazy — only fetch when panel is open)
  - `updateJiraSettingsMutation` — PATCH Jira settings and invalidate integrations cache
  - `useEffect` — syncs `project_key` and `user_map` from existing integration metadata on load
  - Chevron toggle button on connected Jira card (between Connected badge and sync button)
  - Expandable Jira Settings Panel: project dropdown + per-member Jira account selects + Save button

---

### Phase 2 — Post-Meeting Jira Push UI ✅ DONE (2026-05-16)
**Goal:** After AI generates tasks from a meeting, admin reviews them and pushes to Jira in one click.

**Admin Workflow:**
```
Meeting ends
  → AI transcribes
  → Tasks generated + converted via Action Items tab
  → Admin opens Action Items tab → sees "Push to Jira" panel
  → Reviews tasks with sync status per row
  → Clicks "Push N to Jira" → all unsynced tasks get Jira issues
  → Each row shows green checkmark + clickable "PROJ-42" key
```

**Backend (complete):**
- `POST /api/integrations/jira/bulk-sync` in `routers/integrations.py`
  - Accepts `{task_ids: List[str]}`
  - Validates team membership for each task (security guard)
  - Skips tasks where `external_id` already set → returns `"already_synced"`
  - Resolves Jira assignee from `user_map[task.assignee_id]` (Phase 1 data)
  - Creates Jira issue; stores KEY (e.g. "PROJ-42") in `task.external_id` (not numeric ID)
  - Returns `List[{task_id, status, jira_key, jira_url, error}]`
- Schemas: `JiraBulkSyncRequest`, `JiraBulkSyncItemResult` added

**Frontend (complete):**
- `frontend/lib/api.ts` — `bulkSyncJira(task_ids)` added to `integrationsApi`
- `frontend/components/JiraSyncPanel.tsx` — new standalone component:
  - Shows only when Jira is connected + there are converted action items with task_ids
  - Blue header with "Push N to Jira" button (disabled when all synced)
  - Per-row: status icon, task description, assignee hint, Jira key link, per-row retry button
  - Local state tracks sync results per task_id; merges on each mutation response
- `frontend/app/dashboard/meetings/[id]/page.tsx`:
  - Added `integrations` query + `jiraIntegration` derived value
  - Embedded `<JiraSyncPanel>` below converted items in the Action Items tab

---

### Phase 3 — Bi-directional Sync: Jira → Synkro ✅ DONE (2026-05-16)
**Goal:** When a Jira issue is updated (status, assignee, comment), it reflects in Synkro.

**Backend (complete):**
- `POST /api/integrations/jira/webhook` (public, no auth)
  - Secret verified via `?secret=` query param matched to `integration.platform_metadata["webhook_secret"]`
  - `jira:issue_updated` → updates task status (via `_JIRA_STATUS_MAP`), title, assignee (reverse user_map lookup), sets `jira_synced_at`
  - `jira:issue_deleted` → clears `task.external_id`
- `POST /api/integrations/jira/register-webhook`
  - Generates `secrets.token_urlsafe(32)` webhook secret
  - Calls `jira.register_webhook(callback_url)`, stores `webhook_id` + `webhook_secret` in metadata
- `DELETE /api/integrations/jira/deregister-webhook`
  - Calls `jira.delete_webhook(webhook_id)`, clears both fields from metadata
- `disconnect_integration` — auto-deregisters webhook before deletion if `webhook_id` is present
- `backend/app/models/task.py` — added `jira_synced_at = Column(DateTime, nullable=True)`
- `backend/alembic/versions/012_add_jira_synced_at.py` — migration (down_revision = 011)
- `backend/app/config.py` — added `JIRA_WEBHOOK_SECRET` and `BACKEND_URL` settings

**Status Mapping Table (bidirectional):**

| Synkro status | Jira status |
|---------------|-------------|
| `todo` | To Do |
| `in_progress` | In Progress |
| `in_review` | In Review |
| `done` | Done |

**Frontend (complete):**
- `frontend/lib/api.ts` — `registerJiraWebhook()` and `deregisterJiraWebhook()` added to `integrationsApi`
- `frontend/types/index.ts` — `jira_synced_at?: string` added to `Task` interface
- `frontend/app/dashboard/settings/page.tsx` — webhook status pill on Jira connected card:
  - Green "Webhook: Active" badge when `webhook_id` is set
  - Gray "Webhook: Inactive" + "Register" button otherwise (triggers `registerWebhookMutation`)
- `frontend/app/dashboard/tasks/page.tsx` — `jira_synced_at` displayed as `↻ MMM d, HH:mm` next to Jira key

---

### Phase 4 — Jira Sync Dashboard ✅ DONE (2026-05-16)
**Goal:** Admin has full visibility into all Jira-linked tasks, sync failures, and can manually re-trigger.

**Migration:** `013_add_jira_sync_error` — adds `jira_sync_error TEXT` column to tasks table.

**Backend:**
- `backend/app/models/task.py` — `jira_sync_error = Column(Text, nullable=True)` added
- `backend/alembic/versions/013_add_jira_sync_error.py` — migration file
- `backend/app/tasks/integration_tasks.py` — `sync_task_to_jira` now clears `jira_sync_error` on success and persists error string (max 500 chars) on `MaxRetriesExceeded`
- `backend/app/routers/integrations.py` — 3 new schemas (`JiraSyncedTaskItem`, `JiraSyncedTasksResponse`, `JiraReSyncResult`) + 4 new endpoints:
  - `GET /api/integrations/jira/synced-tasks`
  - `POST /api/integrations/jira/re-sync/{task_id}`
  - `DELETE /api/integrations/jira/unlink/{task_id}`
  - `POST /api/integrations/jira/sync-all`

**Frontend:**
- `frontend/types/index.ts` — `jira_sync_error?: string` added to `Task`; 3 new interfaces: `JiraSyncedTaskItem`, `JiraSyncedTasksResponse`, `JiraReSyncResult`
- `frontend/lib/api.ts` — 4 new methods in `integrationsApi`: `getSyncedJiraTasks`, `reSyncJiraTask`, `unlinkJiraTask`, `syncAllJiraTasks`
- `frontend/app/dashboard/layout.tsx` — "Jira Sync" nav item added (RefreshCcw icon) linking to `/dashboard/integrations/jira`
- `frontend/app/dashboard/integrations/jira/page.tsx` — new page with 3 summary stat cards, full linked-tasks table (Re-sync / Unlink per row), Sync All button, error highlighting

---

### Phase 5 — Other Apps → Jira ✅ DONE (2026-05-16)
**Goal:** Tasks imported from Slack, email, or other sources also get Jira tickets automatically.

**Audit findings:**
- `routers/tasks.py:create_task` — already syncs inline unconditionally (existing behaviour, unchanged)
- `tasks/meeting_tasks.py:process_message_for_intent` — Slack intent tasks already sync inline (existing behaviour, unchanged)
- `routers/meetings.py:convert_action_item_to_task` — **was missing Jira sync → fixed**
- `routers/emails.py:sync_emails` — **was missing Jira sync → fixed**
- `sync_task_to_jira` Celery task — dead code; inline sync is the actual pattern used everywhere

**Changes made:**
- `backend/app/routers/integrations.py` — `JiraSettingsRequest` adds `auto_jira_sync: Optional[bool]`; `update_jira_settings` persists it to `integration.platform_metadata["auto_jira_sync"]`
- `backend/app/routers/meetings.py:convert_action_item_to_task` — after task commit, if team has Jira connected + `auto_jira_sync=True`, creates Jira issue and stores key in `task.external_id`
- `backend/app/routers/emails.py:sync_emails` — tracks `created_tasks` list; after batch commit, if team has Jira connected + `auto_jira_sync=True`, syncs each new task to Jira (per-task error isolation, single `aclose()`)
- `frontend/lib/api.ts` — `updateJiraSettings` type extended with `auto_jira_sync?: boolean`
- `frontend/app/dashboard/settings/page.tsx` — `autoJiraSync` state; initialized from `jiraIntegration.metadata.auto_jira_sync` in useEffect; toggle switch rendered in Jira Settings Panel; included in Save Settings mutation

---

---

### Phase 6 — Sprint Assignment + Extended Webhook Sync ✅ DONE (2026-05-16)
**Goal:** Place Jira issues into the active sprint at creation time; sync priority and due date back from Jira via webhook.

**Bug fixes:**
- `routers/tasks.py:create_task` and `update_task` — stored `jira_result.get("id")` (numeric) instead of `"key"` (PROJ-42); fixed to `.get("key")` in both paths

**Backend:**
- `routers/integrations.py` — `JiraSettingsRequest` adds `assign_to_sprint: Optional[bool]`; `update_jira_settings` persists it; `_JIRA_PRIORITY_MAP` dict added (Jira priority name → Synkro TaskPriority)
- `jira_bulk_sync` — calls `get_active_sprint_id(project_key)` once before the task loop if `assign_to_sprint` is set; passes `sprint_id` to each `create_issue`
- `jira:issue_updated` webhook handler — now also reverse-syncs:
  - `fields.priority.name` → `task.priority` via `_JIRA_PRIORITY_MAP`
  - `fields.duedate` → `task.due_date` (present + non-null → parse `YYYY-MM-DD`; present + null → clear)
- `routers/meetings.py:convert_action_item_to_task` — calls `get_active_sprint_id` if `assign_to_sprint`; passes `sprint_id` to `create_issue`
- `routers/emails.py:sync_emails` — calls `get_active_sprint_id` once before the task loop if `assign_to_sprint`; passes `sprint_id` to each `create_issue`
- `routers/tasks.py:create_task` — `get_active_sprint_id` now gated on `assign_to_sprint` flag (previously unconditional)
- `routers/tasks.py:update_task` — same gate applied

**Frontend:**
- `frontend/lib/api.ts` — `updateJiraSettings` type gains `assign_to_sprint?: boolean`
- `frontend/app/dashboard/settings/page.tsx` — `assignToSprint` state; initialized from `integration.metadata.assign_to_sprint`; "Assign to Active Sprint" toggle in Jira Settings Panel; included in Save Settings mutation

---

### Phase 7 — Jira Comments Sync ✅ DONE (2026-05-16)
**Goal:** Bidirectional comment sync between Synkro tasks and Jira issues — comments posted in Synkro push to Jira, and comments added directly in Jira flow back via webhook.

**Migration:** `014_add_task_comments` — new `task_comments` table.

**Backend:**
- `backend/app/models/task_comment.py` — new `TaskComment` model (`id`, `task_id`, `body`, `author_id`, `jira_comment_id`, `jira_author_name`, `source: synkro|jira`, `created_at`, `updated_at`)
- `backend/app/models/task.py` — `comments = relationship("TaskComment", ...)` added
- `backend/app/models/__init__.py` — `TaskComment`, `CommentSource` exported
- `backend/alembic/versions/014_add_task_comments.py` — migration (down_revision = 013)
- `backend/app/services/jira_service.py` — two new methods: `add_comment(issue_key, body)` and `get_comments(issue_key)`
- `backend/app/routers/comments.py` — new router with 3 endpoints:
  - `GET  /api/tasks/{task_id}/comments` — list, team-guarded, batch-loads author names
  - `POST /api/tasks/{task_id}/comments` — create + push to Jira if task has `external_id`; stores returned `jira_comment_id`
  - `DELETE /api/tasks/{task_id}/comments/{comment_id}` — author or admin only
- `backend/app/routers/integrations.py` — `_extract_adf_text()` helper added; `jira_webhook` now handles two new events:
  - `comment_created` — parse ADF body → create `TaskComment(source=JIRA)`, idempotent on `jira_comment_id`
  - `comment_deleted` — delete local comment by `jira_comment_id`
- `backend/app/main.py` — `comments` router included

**Frontend:**
- `frontend/types/index.ts` — `TaskComment` interface added
- `frontend/lib/api.ts` — `commentsApi` added (`getComments`, `addComment`, `deleteComment`)
- `frontend/components/TaskCommentSection.tsx` — new component: comment list with Jira icon badge on inbound comments, Textarea + "Post" (Ctrl+Enter) button, delete on own comments
- `frontend/app/dashboard/tasks/page.tsx` — `TaskCommentSection` embedded in `EditTaskDialog` scrollable div below meeting fields, separated by a border-top

---

---

## Real-Time Notifications Plan

### Phase 1 — Notification Model + REST Polling ✅ DONE (2026-05-16)
**Goal:** Persist in-app notifications to DB; frontend polls every 30 s and shows a bell badge.

**Backend (complete):**
- `backend/app/models/notification.py` — `Notification` model (`id`, `user_id`, `type`, `title`, `body`, `link`, `is_read`, `created_at`)
- `backend/alembic/versions/015_add_notifications.py` — migration (down_revision = 014)
- `backend/app/services/notification_service.py` — `create_notification()` helper (adds to session, caller commits)
- `backend/app/routers/notifications.py` — 3 endpoints:
  - `GET  /api/notifications` — list with `unread_count`, optional `unread_only` filter
  - `PATCH /api/notifications/{id}/read` — mark one read
  - `POST  /api/notifications/mark-all-read`
- `backend/app/models/__init__.py` — `Notification`, `NotificationType` exported
- `backend/app/main.py` — notifications router included
- Emitters added:
  - `tasks.py:create_task` — notifies assignee (if different from creator) with type `task_assigned`
  - `tasks.py:update_task` — notifies new assignee on reassign with type `task_assigned`
  - `meetings.py:process_meeting_background` — notifies meeting uploader on `COMPLETED` with type `meeting_completed`
  - `comments.py:add_comment` — notifies task assignee + creator (excluding commenter) with type `comment_added`

**Frontend (complete):**
- `frontend/types/index.ts` — `NotificationType` union and `Notification` interface
- `frontend/lib/api.ts` — `notificationsApi` (`list`, `markRead`, `markAllRead`)
- `frontend/components/NotificationBell.tsx` — bell icon + unread badge + dropdown; polls every 30 s; click marks read and navigates to link; "Mark all read" button
- `frontend/app/dashboard/layout.tsx` — `<NotificationBell />` embedded in top header

---

### Phase 2 — WebSocket Real-time Push (next)
**Goal:** Replace 30-second polling with instant server-push via WebSocket so the badge updates the moment an event fires.

**Backend plan:**
- `backend/app/services/ws_manager.py` — `ConnectionManager` tracks `{user_id → WebSocket}` in a dict; exposes `connect`, `disconnect`, `send_to_user`
- `backend/app/routers/notifications.py` — add `GET /api/notifications/ws` WebSocket endpoint; on connect authenticate via `?token=` query param; each new `Notification` row is serialised and pushed
- `notification_service.create_notification()` — after `db.add`, call `await ws_manager.send_to_user(user_id, payload)` (non-fatal if user offline)

**Frontend plan:**
- `frontend/hooks/useNotificationSocket.ts` — open WebSocket on mount; on message push into React Query cache via `queryClient.setQueryData`; reconnect with exponential back-off
- `NotificationBell.tsx` — drop `refetchInterval`, use the hook instead; REST poll becomes fallback only

---

### Phase 3 — Notification Preferences (future)
**Goal:** Users opt in/out of notification types; admin gets a digest.

- `user_notification_prefs` table — per-user per-type toggle
- Settings page panel — toggles for each notification type
- Weekly digest — background Celery job emails admin a markdown summary

---

## Priority Order — Core Features

| Phase | Feature | Effort | Impact |
|-------|---------|--------|--------|
| N1-1 | Notification model + REST polling | Low | High — task/meeting/comment awareness |
| N1-2 | WebSocket real-time push | Medium | High — instant delivery |
| N1-3 | Notification preferences | Low | Medium — user control |

---

## Priority Order — Jira Integration (historical)

| Phase | Feature | Effort | Impact |
|-------|---------|--------|--------|
| 1 | Project picker + user mapping | Low | High — fixes assignee blank in Jira |
| 2 | Post-meeting Jira push UI | Medium | **Critical** — core admin use case |
| 3 | Jira → Synkro webhook | High | High — true bi-directional sync |
| 4 | Sync dashboard | Low | Medium — visibility & admin control |
| 5 | Other apps → Jira | Low | Medium — completeness |
| 6 | Sprint assignment + extended webhook sync | Low | Medium — sprint hygiene + richer inbound sync |
| 7 | Jira Comments Sync | Medium | Medium — closes the communication loop |
