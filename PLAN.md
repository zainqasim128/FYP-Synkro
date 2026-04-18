# Synkro — Project Plan Document

> AI-powered team productivity platform | Final Year Project
> Last updated: March 2026

---

## Table of Contents

1. [Project Summary](#1-project-summary)
2. [Technology Stack](#2-technology-stack)
3. [Architecture Overview](#3-architecture-overview)
4. [What Has Been Built — Feature-by-Feature](#4-what-has-been-built--feature-by-feature)
   - 4.1 Authentication & User Accounts
   - 4.2 Role-Based Access Control
   - 4.3 Meeting Management & AI Transcription
   - 4.4 Task Management
   - 4.5 Email Integration (Gmail)
   - 4.6 AI Chat Assistant
   - 4.7 Analytics & Reporting
   - 4.8 Admin Panel
   - 4.9 Dashboard Home
   - 4.10 Settings Page
5. [Database Schema](#5-database-schema)
6. [API Endpoints Reference](#6-api-endpoints-reference)
7. [Frontend Pages & Routes](#7-frontend-pages--routes)
8. [State Management](#8-state-management)
9. [Background Processing Pipeline](#9-background-processing-pipeline)
10. [What Still Needs to Be Built](#10-what-still-needs-to-be-built)
11. [Priority Roadmap](#11-priority-roadmap)
12. [Dev Notes & Conventions](#12-dev-notes--conventions)

---

## 1. Project Summary

**Synkro** is a web application built for software development teams. It solves a common problem: team activity is fragmented across meetings, emails, chats, and task boards. Synkro brings all of this into a single AI-powered dashboard.

**Core value proposition:**
- Record a meeting → get an automatic transcript, summary, and action items
- Sync Gmail → see relevant emails alongside tasks
- Ask the AI chat assistant natural language questions about team progress
- Track tasks, deadlines, and individual workload in one place
- Role-based access so admins, managers, and developers see the right things

**Project type**: Final Year Project (FYP)
**Backend**: `localhost:8000`
**Frontend**: `localhost:3000`
**API docs (Swagger)**: `http://localhost:8000/api/docs`

---

## 2. Technology Stack

| Layer | Technology | Version |
|---|---|---|
| Backend framework | FastAPI | 0.109.0 |
| Database | PostgreSQL (async) | asyncpg driver |
| ORM | SQLAlchemy (async) | 2.0.25 |
| Validation | Pydantic | 2.5.3 |
| Server | Uvicorn | latest |
| Auth | JWT (access + refresh tokens) | PyJWT |
| Task queue | Celery + Redis | 5.3.6 / 5.0.1 |
| AI — transcription | Groq Whisper Large v3 Turbo | via Groq API |
| AI — summarisation/chat | Groq Llama 3.3 70B (free) | via Groq API |
| AI — fallback | OpenAI GPT-4 + Whisper | via OpenAI API |
| Storage | Local filesystem (dev) / AWS S3 | boto3 |
| Frontend framework | Next.js (App Router) | 14.1.0 |
| Language | TypeScript | 5.3.3 |
| Styling | Tailwind CSS + Radix UI (shadcn/ui) | 3.4.1 |
| Client state | Zustand | latest |
| Server state | TanStack Query | 5.17.19 |
| Forms | React Hook Form + Zod | 7.49.3 / 3.22.4 |
| Charts | Recharts | 2.10.3 |
| HTTP client | Axios | 1.6.5 |

---

## 3. Architecture Overview

```
Browser (Next.js 14)
        │
        │ HTTPS / REST JSON
        ▼
FastAPI app  (localhost:8000)
        │
        ├── PostgreSQL  ←──  SQLAlchemy async ORM
        │
        ├── Redis  ←──────── Celery broker + result backend
        │
        ├── Groq API  ←───── Whisper (transcription) + Llama (AI)
        │
        └── Local FS / S3 ── Meeting audio file storage
```

### Key architectural decisions

**Team isolation** — every database query is automatically scoped to `current_user.team_id`. No user ever sees another team's data.

**Async everywhere** — FastAPI + asyncpg + async SQLAlchemy means the backend never blocks on I/O. Meeting transcription runs as a background task so the upload response returns immediately.

**AI service abstraction** — a single `ai_service.py` file decides whether to use Groq (free, preferred) or OpenAI (paid, fallback) based on which API keys are present in the environment.

**Storage abstraction** — `utils/storage.py` provides a unified interface. In development it writes to local disk. In production it writes to AWS S3 or Cloudflare R2. The rest of the app never sees the difference.

**JWT with auto-refresh** — Axios intercepts every 401 response, silently fetches a new access token using the stored refresh token, and retries the original request. Users never get logged out mid-session unless the 7-day refresh token has also expired.

---

## 4. What Has Been Built — Feature-by-Feature

### 4.1 Authentication & User Accounts

**What it does:**
Handles user registration, login, session management, and password recovery. Every user belongs to exactly one team.

**How it works — Registration:**
1. User fills in full name, email, password, and selects a role from a dropdown (with descriptions for each role).
2. Frontend sends `POST /api/auth/register`.
3. Backend checks email uniqueness. If the chosen role is `admin`, it also checks that no admin already exists (one admin per system).
4. A team is auto-created for the first user; subsequent users join the same team (currently by default — team invitation flow is not yet built).
5. Password is hashed with bcrypt and stored. A JWT pair is returned immediately — the user is logged in right after registering.

**How it works — Login:**
1. User enters email + password.
2. `POST /api/auth/login` verifies the password hash, returns an access token (30-minute lifespan) and a refresh token (7-day lifespan).
3. Both tokens are stored in `localStorage`.
4. Axios attaches the access token as `Authorization: Bearer <token>` on every subsequent request.

**How it works — Auto token refresh:**
1. The Axios instance has a response interceptor.
2. When any request returns a `401 Unauthorized`, the interceptor automatically calls `POST /api/auth/refresh` with the stored refresh token.
3. If successful, it stores the new access token and retries the original request transparently.
4. If the refresh also fails (token expired or revoked), the user is redirected to `/login`.

**How it works — Forgot password (3-step flow, currently dev-only):**
1. Step 1: User enters their email on the login page → `POST /api/auth/forgot-password` → backend generates a reset token (1-hour expiry), stores its hash in `users.password_reset_token`, and returns the token in the API response (dev mode — no email server needed).
2. Step 2: The token is shown directly on screen. User copies it.
3. Step 3: User pastes the token + enters a new password → `POST /api/auth/reset-password` → backend verifies the token, checks it has not expired, updates the password hash, and clears the reset token fields.

**Files:**
- [backend/app/routers/auth.py](backend/app/routers/auth.py) — all auth endpoints
- [backend/app/utils/security.py](backend/app/utils/security.py) — JWT creation/verification, password hashing
- [frontend/app/login/page.tsx](frontend/app/login/page.tsx) — login + forgot-password UI
- [frontend/app/register/page.tsx](frontend/app/register/page.tsx) — registration form
- [frontend/lib/stores/authStore.ts](frontend/lib/stores/authStore.ts) — Zustand auth state

---

### 4.2 Role-Based Access Control (RBAC)

**What it does:**
Controls what each user can see and do based on their assigned role.

**Role hierarchy:**
```
admin  >  project_manager  >  team_lead  >  senior_developer  >  developer  >  intern
```

**Permission matrix:**

| Feature | admin | All other roles |
|---|---|---|
| Upload meetings | Yes | No (lock notice shown) |
| Delete meetings | Yes | No |
| View meeting transcripts | Yes | Yes |
| Manage users (admin panel) | Yes | No |
| Change user roles | Yes | No |
| Create / edit / delete tasks | Yes | Yes |
| View analytics | Yes | Yes |
| Connect Gmail | Yes | Yes |
| Use AI chat | Yes | Yes |
| See admin banner on dashboard | Yes | No |

**How it works on the backend:**
- Two FastAPI dependency functions in [backend/app/dependencies.py](backend/app/dependencies.py):
  - `get_current_user` — requires a valid JWT; returns the authenticated user.
  - `get_current_admin_user` — calls `get_current_user`, then checks `user.role == "admin"`. Returns `403 Forbidden` if not admin.
- Admin-only endpoints inject `get_current_admin_user` instead of `get_current_user`.

**How it works on the frontend:**
- The auth store exposes the current `user` object including `role`.
- Pages and components read `user.role` to conditionally show/hide UI elements (upload button, admin panel tab, admin banner, etc.).

---

### 4.3 Meeting Management & AI Transcription

**What it does:**
Admins upload meeting recordings. The system automatically transcribes the audio, writes an AI summary, and extracts action items — all in the background. Team members can then read the full transcript, summary, and action items.

**How it works — Upload flow:**
1. Admin navigates to `/dashboard/meetings` and selects an audio/video file (`.mp3`, `.wav`, `.m4a`, `.webm`, `.mp4`, `.mpeg`, `.mpga`; up to 100 MB in the UI, 25 MB enforced by Groq Whisper API).
2. Frontend calls `POST /api/meetings/upload` with the file as multipart form data.
3. Backend saves the file to local storage (or S3 in production) and creates a `Meeting` record in the database with `status = "pending"`.
4. The API response returns immediately (the file is saved; processing happens separately).
5. A background task is triggered that handles transcription asynchronously.

**How it works — Background transcription pipeline:**
1. Background task picks up the meeting.
2. Status is set to `"processing"`.
3. The audio file is sent to **Groq Whisper Large v3 Turbo** for transcription. If Groq fails or is unavailable, **OpenAI Whisper** is used as fallback.
4. The raw transcript text is stored in `meetings.transcript`.
5. The transcript is then sent to **Groq Llama 3.3 70B** (or OpenAI GPT-4) with a structured prompt to produce:
   - Key topics discussed
   - Decisions made
   - Action items (with assignee mentions and deadlines)
   - Blockers raised
   - Next steps
6. The structured summary JSON is stored in `meetings.summary`.
7. Action items are individually saved to the `action_items` table linked to the meeting.
8. Status is set to `"completed"`. On any error, status is set to `"failed"`.

**How it works — Frontend polling:**
- While a meeting is in `"pending"` or `"processing"` status, the meetings list automatically re-fetches every 5 seconds (TanStack Query `refetchInterval`).
- When status changes to `"completed"` or `"failed"`, polling stops.
- The status is shown as a colour-coded badge.

**Meeting detail page (`/dashboard/meetings/[id]`):**
- Shows the full transcript in a scrollable panel.
- Shows the structured AI summary (topics, decisions, action items, blockers, next steps).
- Shows all extracted action items with assignee names and confidence scores.
- Admin can retry a failed transcription from this page.

**Files:**
- [backend/app/routers/meetings.py](backend/app/routers/meetings.py) — upload, list, detail, retry endpoints
- [backend/app/services/ai_service.py](backend/app/services/ai_service.py) — Groq/OpenAI transcription & summarisation
- [backend/app/utils/storage.py](backend/app/utils/storage.py) — file storage abstraction
- [frontend/app/dashboard/meetings/page.tsx](frontend/app/dashboard/meetings/page.tsx) — meeting list + upload form
- [frontend/app/dashboard/meetings/[id]/page.tsx](frontend/app/dashboard/meetings/[id]/page.tsx) — meeting detail

---

### 4.4 Task Management

**What it does:**
Full CRUD for tasks, scoped to the user's team. All roles can create, view, update, and delete tasks. Tasks can be filtered and searched.

**Task fields:**
| Field | Type | Options |
|---|---|---|
| Title | text | required |
| Description | text | optional |
| Status | enum | `todo`, `in_progress`, `done`, `blocked` |
| Priority | enum | `low`, `medium`, `high`, `urgent` |
| Assignee | user reference | any team member |
| Due date | date | optional |
| Source type | enum | `manual`, `meeting`, `message`, `ai` |

**How it works:**
1. User opens `/dashboard/tasks`.
2. Tasks are fetched via `GET /api/tasks` with optional query params for `status`, `priority`, `assignee_id`, `due_date_from`, `due_date_to`, `page`, `per_page`.
3. The task list is filtered and paginated server-side.
4. **Create task**: "Create Task" button opens a dialog (modal). User fills in fields. `POST /api/tasks` creates the task and the list auto-refreshes via TanStack Query cache invalidation.
5. **Update task**: clicking a task opens an edit form. `PATCH /api/tasks/{id}` updates only the fields that changed.
6. **Delete task**: delete button calls `DELETE /api/tasks/{id}` with confirmation. List re-fetches automatically.
7. **Stats endpoint**: `GET /api/tasks/stats` returns task counts by status, counts by priority, overdue task count, and completion rate. Used on the dashboard home and analytics pages.

**Team scoping:**
Every task query in the backend automatically adds `WHERE team_id = :current_user_team_id`. A user can never see or modify another team's tasks.

**Files:**
- [backend/app/routers/tasks.py](backend/app/routers/tasks.py)
- [frontend/app/dashboard/tasks/page.tsx](frontend/app/dashboard/tasks/page.tsx)
- [frontend/components/create-task-dialog.tsx](frontend/components/create-task-dialog.tsx)

---

### 4.5 Email Integration (Gmail)

**What it does:**
Users connect their Gmail account using an app password. The app then syncs their recent emails into Synkro so they can be viewed alongside tasks and meetings.

**How it works — Connection:**
1. User goes to `/dashboard/settings`, clicks "Connect Gmail".
2. A dialog asks for their Gmail address and an app password (generated from Google Account security settings — not their real password).
3. `POST /api/integrations/gmail/connect` stores the credentials in the `integrations` table with `platform = "gmail"`.

**How it works — Sync:**
1. User clicks "Sync Emails" button on `/dashboard/emails`.
2. `POST /api/emails/sync` is called.
3. Backend retrieves the user's Gmail integration record, uses IMAP to connect to Gmail, and fetches up to 50 emails from the last 30 days.
4. For each email, it checks if `(user_id, gmail_message_id)` already exists to avoid duplicates.
5. New emails are saved to the `emails` table with sender, subject, body preview, and received date.
6. The email list re-fetches automatically.

**What users see:**
- List of emails with sender name, subject line, date, and a short body preview.
- Full email body on clicking a row.
- Email statistics (total synced, read/unread, flagged).

**Files:**
- [backend/app/routers/integrations.py](backend/app/routers/integrations.py) — Gmail connect/disconnect
- [backend/app/routers/emails.py](backend/app/routers/emails.py) — sync + list
- [backend/app/services/gmail_service.py](backend/app/services/gmail_service.py) — IMAP client
- [frontend/app/dashboard/emails/page.tsx](frontend/app/dashboard/emails/page.tsx)
- [frontend/app/dashboard/settings/page.tsx](frontend/app/dashboard/settings/page.tsx) — connect form

---

### 4.6 AI Chat Assistant

**What it does:**
Users can ask natural language questions about the team's work and get intelligent answers based on live data from the database.

**Example queries:**
- "What's on my plate this week?"
- "Who is working on the authentication feature?"
- "What did we decide in yesterday's meeting?"
- "Which tasks are overdue?"
- "How is the team's workload distributed?"

**How it works:**
1. User types a message on `/dashboard/chat` and submits.
2. `POST /api/chat/query` is called with the message text.
3. Backend keyword-analyses the query to determine what data is relevant (tasks, meetings, users, emails).
4. It fetches the relevant data from the database (e.g., if the query mentions "tasks", it fetches the team's current tasks).
5. A prompt is assembled containing: the user's question + the fetched context data (formatted as readable text).
6. The prompt is sent to **Groq Llama 3.3 70B** (or OpenAI GPT-4 as fallback).
7. The AI generates a natural language response using only the provided context.
8. The backend returns:
   - `response` — the AI's answer
   - `context_used` — a list of data sources that were included
   - `suggested_actions` — optional follow-up actions the user might want to take

**Frontend:**
- Chat history is displayed as a conversation (user messages on the right, AI responses on the left).
- Suggested queries appear as clickable chips below the input so new users know what to ask.
- After each AI response, suggested actions appear as buttons.

**Files:**
- [backend/app/routers/chat.py](backend/app/routers/chat.py)
- [backend/app/services/ai_service.py](backend/app/services/ai_service.py)
- [frontend/app/dashboard/chat/page.tsx](frontend/app/dashboard/chat/page.tsx)

---

### 4.7 Analytics & Reporting

**What it does:**
Provides visual charts and metrics about team performance, task distribution, and meeting outcomes. Configurable date range (1–365 days).

**Analytics modules:**

**Workload view:**
- Tasks by status (todo / in progress / done / blocked) — bar chart
- Tasks by priority (low / medium / high / urgent) — pie chart
- Overdue task count — stat card
- Per-member task count — horizontal bar chart

**Productivity view:**
- Completion rate (% of tasks in "done") — stat card
- Average task age (days since creation) — stat card
- Productivity trend over selected time window — line chart (daily task completions)

**Team insights view:**
- Per-member breakdown: assigned tasks vs completed tasks
- Meeting conversion rate (action items extracted per meeting)
- Action item completion rate (how many extracted action items became tasks)

**How it works:**
- All analytics endpoints query the database in real time — no pre-computed aggregates.
- `GET /api/analytics/workload` — counts tasks grouped by status and priority for the team.
- `GET /api/analytics/productivity` — calculates rates and averages; accepts a `days` query param.
- `GET /api/analytics/team` — joins users with their tasks to produce per-member stats.
- `GET /api/analytics/team-workload` — detailed per-member breakdown.
- `GET /api/analytics/meeting-insights` — meeting counts, transcription rates, action item extraction rates.
- `GET /api/analytics/productivity-trend` — daily task completions for trend line.

**Files:**
- [backend/app/routers/analytics.py](backend/app/routers/analytics.py)
- [frontend/app/dashboard/analytics/page.tsx](frontend/app/dashboard/analytics/page.tsx)

---

### 4.8 Admin Panel

**What it does:**
The admin sees an extra tab in `/dashboard/settings` with full user management capabilities.

**User management features:**
- List all users: full name, email, role, status (active/inactive), join date
- Change any user's role: dropdown selector, `PATCH /api/admin/users/{id}/role`
- Toggle active status: activate or deactivate a user, `PATCH /api/admin/users/{id}/toggle-active`
- Delete a user: `DELETE /api/admin/users/{id}` with confirmation dialog
- User statistics dashboard: total users, active users, new this month, breakdown by role

**Security:**
- All `/api/admin/*` endpoints use the `get_current_admin_user` dependency which returns `403 Forbidden` if the caller is not an admin.
- The admin panel tab is hidden in the frontend for non-admin users (checked via `user.role === "admin"`).

**Files:**
- [backend/app/routers/admin.py](backend/app/routers/admin.py)
- [frontend/app/dashboard/settings/page.tsx](frontend/app/dashboard/settings/page.tsx) — admin panel section

---

### 4.9 Dashboard Home

**What it does:**
The landing page after login. Shows an at-a-glance summary of the team's current state.

**Admin view:**
- Banner with user count cards (total, new this month, by role)
- "Manage Users" and "Upload Meeting" quick-action buttons

**All users:**
- 4 stat cards: Active Tasks, In Progress, Overdue Tasks, Completion Rate
- Recent tasks list (last 5) with status badges
- Recent meetings list (last 3) with status and date
- "Create Task" quick-action button

**How it works:**
- Stats are fetched from `GET /api/tasks/stats`.
- Recent tasks from `GET /api/tasks?per_page=5`.
- Recent meetings from `GET /api/meetings?per_page=3`.
- All fetched in parallel using TanStack Query on page load.

**Files:**
- [frontend/app/dashboard/page.tsx](frontend/app/dashboard/page.tsx)

---

### 4.10 Settings Page

**What it does:**
User profile management and integration configuration.

**Profile section (all roles):**
- Edit full name
- Edit timezone
- `PATCH /api/auth/me` saves changes

**Integrations section (all roles):**
- Gmail: connect (enter email + app password), view connection status, see last sync time, disconnect
- Slack: OAuth connection, view workspace/team, sync messages, disconnect
- Jira: connect with domain/email/API token, optional project key, sync tasks, disconnect
- Google Calendar & Microsoft Teams still "coming soon"

**Admin panel section (admin only):**
- Appears as an additional tab only for admin users
- Full user management as described in section 4.8

**Files:**
- [frontend/app/dashboard/settings/page.tsx](frontend/app/dashboard/settings/page.tsx)

---

## 5. Database Schema

### Users
```
id                    UUID (PK)
email                 VARCHAR UNIQUE NOT NULL
password_hash         VARCHAR NOT NULL
full_name             VARCHAR NOT NULL
avatar_url            VARCHAR
timezone              VARCHAR DEFAULT 'UTC'
role                  ENUM (admin, project_manager, team_lead, senior_developer, developer, intern)
is_active             BOOLEAN DEFAULT true
is_verified           BOOLEAN DEFAULT false
created_at            TIMESTAMP
updated_at            TIMESTAMP
password_reset_token  VARCHAR
password_reset_expires TIMESTAMP
team_id               UUID FK → teams.id
```

### Teams
```
id          UUID (PK)
name        VARCHAR NOT NULL
plan        ENUM (free, pro, enterprise)
settings    JSONB
created_at  TIMESTAMP
```

### Meetings
```
id               UUID (PK)
title            VARCHAR NOT NULL
scheduled_at     TIMESTAMP
duration_minutes INTEGER
recording_url    VARCHAR
transcript       TEXT
summary          JSONB
status           ENUM (scheduled, processing, transcribed, completed, failed)
created_at       TIMESTAMP
updated_at       TIMESTAMP
team_id          UUID FK → teams.id
created_by_id    UUID FK → users.id
```

### ActionItems
```
id                  UUID (PK)
description         TEXT NOT NULL
assignee_mentioned  VARCHAR
deadline_mentioned  VARCHAR
confidence_score    FLOAT
status              ENUM (pending, converted, rejected)
created_at          TIMESTAMP
meeting_id          UUID FK → meetings.id
task_id             UUID FK → tasks.id (nullable — set when converted to task)
```

### Tasks
```
id             UUID (PK)
title          VARCHAR NOT NULL
description    TEXT
status         ENUM (todo, in_progress, done, blocked)
priority       ENUM (low, medium, high, urgent)
due_date       TIMESTAMP
estimated_hours FLOAT
source_type    ENUM (manual, meeting, message, ai)
source_id      VARCHAR
external_id    VARCHAR
created_at     TIMESTAMP
updated_at     TIMESTAMP
assignee_id    UUID FK → users.id
created_by_id  UUID FK → users.id
team_id        UUID FK → teams.id

Indexes: (status, assignee_id), (team_id, status)
```

### Emails
```
id               UUID (PK)
gmail_message_id VARCHAR NOT NULL
subject          VARCHAR
sender           VARCHAR
to               VARCHAR
body_preview     TEXT
body             TEXT
received_at      TIMESTAMP
is_read          BOOLEAN DEFAULT false
is_flagged       BOOLEAN DEFAULT false
ai_classification VARCHAR
ai_summary       TEXT
user_id          UUID FK → users.id
integration_id   UUID FK → integrations.id
created_at       TIMESTAMP

Unique: (user_id, gmail_message_id)
Index:  (user_id, received_at)
```

### Integrations
```
id                UUID (PK)
platform          ENUM (gmail, slack, google_calendar, jira, microsoft_teams)
access_token      VARCHAR
refresh_token     VARCHAR
expires_at        TIMESTAMP
scope             VARCHAR
is_active         BOOLEAN DEFAULT true
platform_metadata JSONB
last_synced_at    TIMESTAMP
created_at        TIMESTAMP
updated_at        TIMESTAMP
user_id           UUID FK → users.id
```

### Messages
```
id           UUID (PK)
external_id  VARCHAR
platform     VARCHAR
sender_email VARCHAR
sender_name  VARCHAR
content      TEXT
timestamp    TIMESTAMP
thread_id    VARCHAR
processed    BOOLEAN DEFAULT false
intent       ENUM (task_request, blocker, question, information, urgent_issue, casual)
entities     JSONB
created_at   TIMESTAMP
user_id      UUID FK → users.id
```

---

## 6. API Endpoints Reference

### Auth — `/api/auth`
| Method | Path | Access | Description |
|---|---|---|---|
| POST | `/register` | Public | Register with name, email, password, role |
| POST | `/login` | Public | Login; returns JWT access + refresh tokens |
| POST | `/refresh` | Public | Exchange refresh token for new access token |
| POST | `/forgot-password` | Public | Generate and return reset token (dev mode) |
| POST | `/reset-password` | Public | Reset password using token |
| GET | `/roles` | Public | List available role options with descriptions |
| GET | `/me` | Auth | Get current user profile |
| PATCH | `/me` | Auth | Update name, timezone |
| POST | `/logout` | Auth | Client-side logout (clears localStorage) |
| GET | `/admin-exists` | Public | Check if any admin account exists |

### Meetings — `/api/meetings`
| Method | Path | Access | Description |
|---|---|---|---|
| POST | `/upload` | Admin | Upload audio/video file; triggers background transcription |
| GET | `/` | Auth | List team meetings (paginated) |
| GET | `/{id}` | Auth | Meeting detail with transcript, summary, action items |
| GET | `/{id}/transcript` | Auth | Full raw transcript text |
| PATCH | `/{id}` | Admin | Update meeting title / metadata |
| DELETE | `/{id}` | Admin | Delete meeting and file |
| POST | `/{id}/retry` | Admin | Retry failed transcription |

### Tasks — `/api/tasks`
| Method | Path | Access | Description |
|---|---|---|---|
| GET | `/` | Auth | List tasks (filters: status, priority, assignee, due_date) |
| POST | `/` | Auth | Create task |
| GET | `/stats` | Auth | Task statistics (counts, overdue, completion rate) |
| GET | `/{id}` | Auth | Task detail |
| PATCH | `/{id}` | Auth | Update task fields |
| DELETE | `/{id}` | Auth | Delete task |

### Emails — `/api/emails`
| Method | Path | Access | Description |
|---|---|---|---|
| POST | `/sync` | Auth | Fetch latest emails from Gmail via IMAP |
| GET | `/` | Auth | List synced emails (paginated) |
| GET | `/stats` | Auth | Email counts (total, read, flagged) |
| GET | `/{id}` | Auth | Full email detail |

### Integrations — `/api/integrations`
| Method | Path | Access | Description |
|---|---|---|---|
| GET | `/` | Auth | List user's active integrations |
| POST | `/gmail/connect` | Auth | Connect Gmail (email + app password) |
| DELETE | `/gmail/{id}` | Auth | Remove Gmail integration |
| POST | `/gmail/disconnect` | Auth | Disconnect Gmail (alternative endpoint) |

### Analytics — `/api/analytics`
| Method | Path | Access | Description |
|---|---|---|---|
| GET | `/workload` | Auth | Task counts by status/priority, overdue, per-member |
| GET | `/productivity` | Auth | Completion rate, avg task age, velocity |
| GET | `/team` | Auth | Per-member assigned vs completed |
| GET | `/team-workload` | Auth | Detailed per-member workload breakdown |
| GET | `/meeting-insights` | Auth | Meeting transcription and action item rates |
| GET | `/productivity-trend` | Auth | Daily task completions for trend chart |

### Chat — `/api/chat`
| Method | Path | Access | Description |
|---|---|---|---|
| POST | `/query` | Auth | Send natural language query; returns AI response + context + suggestions |

### Admin — `/api/admin`
| Method | Path | Access | Description |
|---|---|---|---|
| GET | `/users` | Admin | List all users |
| GET | `/users/count` | Admin | User count statistics |
| GET | `/users/team` | Admin | Team member list |
| PATCH | `/users/{id}/role` | Admin | Change a user's role |
| PATCH | `/users/{id}/toggle-active` | Admin | Activate or deactivate a user |
| DELETE | `/users/{id}` | Admin | Delete a user |

---

## 7. Frontend Pages & Routes

| Route | Who sees it | What it does |
|---|---|---|
| `/` | Public | Landing page — product description, CTA to register/login |
| `/register` | Public | Registration form with role selector and descriptions |
| `/login` | Public | Login form + 3-step forgot-password flow in one page |
| `/dashboard` | Auth | Home — stats cards, recent tasks, recent meetings, quick actions |
| `/dashboard/tasks` | Auth | Task board with search, filters (status, priority), full CRUD |
| `/dashboard/meetings` | Auth | Meeting list; upload form visible to admin only |
| `/dashboard/meetings/[id]` | Auth | Meeting detail — transcript, AI summary, action items |
| `/dashboard/emails` | Auth | Email inbox synced from Gmail |
| `/dashboard/chat` | Auth | AI chat assistant with suggested queries |
| `/dashboard/analytics` | Auth | Charts: workload, productivity, team insights, meeting metrics |
| `/dashboard/settings` | Auth | Profile editor, Gmail integration, admin panel (admin only) |

### Dashboard layout
The dashboard uses a persistent layout with:
- **Sidebar**: links to all dashboard pages; shows current user name, role badge, and avatar initials; collapsible on mobile
- **Top bar**: page title, theme toggle (light/dark), user avatar with logout button
- **Auth guard**: if no valid token is found on page load, redirects to `/login` immediately

---

## 8. State Management

### Zustand stores (client state)

**Auth store** ([frontend/lib/stores/authStore.ts](frontend/lib/stores/authStore.ts)):
```
State  : user (User | null), isAuthenticated, isLoading, error
Actions: initialize(), login(), register(), logout(), fetchUser(), clearError()
```
- `initialize()` is called once on app startup: reads the token from localStorage, and if valid fetches the current user from `/api/auth/me`.
- Persists to localStorage via the token; store itself is in memory.

**Theme store** ([frontend/lib/stores/themeStore.ts](frontend/lib/stores/themeStore.ts)):
```
State  : theme ('light' | 'dark')
Actions: toggleTheme(), initializeTheme()
```
- Reads from and writes to localStorage.
- Applies the appropriate Tailwind `dark` class to `document.documentElement`.

### TanStack Query (server state)

Manages all data that comes from the API. Provides:
- Automatic caching (data is reused while fresh)
- Background re-fetching (stale data is updated silently)
- Optimistic updates (mutations update the UI before the server confirms)
- Cache invalidation (after a mutation, related queries re-fetch automatically)

Key query keys used throughout the app:
```
'task-stats'         'recent-tasks'        'recent-meetings'
'tasks'              'meetings'            'meeting-[id]'
'emails'             'integrations'        'analytics-workload'
'analytics-team'     'analytics-trend'     'admin-user-count'
'admin-users'
```

---

## 9. Background Processing Pipeline

### Meeting transcription (current implementation)

```
1. Admin POSTs audio file to /api/meetings/upload
2. File saved to local disk / S3
3. Meeting row created with status = "pending"
4. FastAPI BackgroundTasks.add_task(process_meeting, meeting_id)
5. Response returns immediately to the frontend

--- background ---
6. Status updated to "processing"
7. Audio file fetched from storage
8. File sent to Groq Whisper API (25 MB limit)
   └─ fallback: OpenAI Whisper if Groq unavailable
9. Raw transcript saved to meetings.transcript
10. Transcript sent to Groq Llama 3.3 70B with structured prompt
    └─ fallback: OpenAI GPT-4
11. Structured summary saved to meetings.summary (JSONB)
12. Action items extracted from summary, saved to action_items table
13. Status updated to "completed" (or "failed" if any step errors)

--- frontend ---
14. TanStack Query polls /api/meetings every 5 seconds while status is pending/processing
15. Status badge updates automatically when completed/failed
```

### Celery + Redis (planned upgrade)

The current implementation uses FastAPI's built-in `BackgroundTasks`, which processes jobs in the same process as the web server. For production reliability, the architecture is designed to migrate to Celery workers backed by Redis, so meeting processing jobs survive server restarts and can be distributed across multiple worker processes.

---

## 10. What Still Needs to Be Built

### HIGH PRIORITY — Core missing functionality

**Action item tracking UI**
- Action items are extracted from meetings and saved to the database but there is no UI to manage them.
- Need: a dedicated page or section listing all action items across all meetings.
- Each action item should show: description, source meeting, mentioned assignee, mentioned deadline, and status (pending / converted / rejected).
- One-click "Convert to Task" button that creates a task pre-filled with the action item description, assignee, and deadline.
- Mark action items as rejected (not relevant).
- This connects the core meeting → task workflow that is the product's main value proposition.

**Team invitation flow**
- Currently, every new user auto-creates their own team at registration, which means the admin and other team members end up on separate teams.
- Need: admin generates an invite link or invite code; new users register using that code and join the admin's existing team.
- Without this, the multi-user team features (shared tasks, shared meetings, analytics) do not work correctly in a real deployment.

**Email-based password reset**
- Currently the reset token is returned in the API response (visible on screen). This is dev-only.
- Need: integrate an email sending library (e.g. `fastapi-mail` with SendGrid or SMTP) to actually email the token to the user.

### MEDIUM PRIORITY — Important UX improvements

**Real-time notifications**
- Users should be notified when: a meeting finishes processing, a task is assigned to them, a task deadline is approaching.
- Implementation options: WebSockets (`fastapi-websockets`) or Server-Sent Events (simpler, one-directional).
- The notification bell icon is already shown in the sidebar but is not wired up.

**Task comments / discussion threads**
- Team members need to discuss tasks without leaving the platform.
- Need: a new `TaskComment` model with `task_id`, `user_id`, `content`, `created_at`.
- Frontend: a comment thread section on the task detail view.

**Profile picture upload**
- Currently avatar shows initials only.
- Need: file upload endpoint, storage to S3/local, and display in sidebar, task cards, and meeting action items.

**OAuth login (Google / GitHub)**
- Currently only email + password login is supported.
- OAuth infrastructure is partially scaffolded (Google client ID/secret env vars exist, redirect URI configured).
- Need: implement the OAuth callback flow using `authlib` or `python-social-auth`.

### LOWER PRIORITY — Polish and production readiness

**AI enhancements**
- Meeting Q&A: allow users to ask questions about a specific meeting transcript using RAG (retrieval-augmented generation) over the transcript text.
- Sentiment analysis: flag meetings or tasks that appear blocked or have negative tone.
- Weekly AI digest: automated email summary of team activity sent to admin every Monday.

**Analytics improvements**
- Export analytics data as PDF or CSV.
- Custom date-range picker (currently uses a fixed `days` number).
- Individual performance view: each user sees their own productivity metrics.

**Infrastructure / production readiness**
- Migrate `BackgroundTasks` to Celery + Redis for reliable async processing.
- Docker Compose file for production deployment (FastAPI + PostgreSQL + Redis + Celery + Next.js + Nginx).
- SSL/TLS termination with Nginx.
- Rate limiting on public auth endpoints (prevent brute-force attacks).
- Encrypt integration tokens (Gmail app passwords currently stored in plain text in the database).
- Move JWT storage from localStorage to httpOnly cookies (reduces XSS risk).
- Automated tests: unit tests for routers, integration tests for the AI pipeline.

---

## 11. Priority Roadmap

### Phase 1 — Make the core workflow functional (immediate)
1. **Team invitation system** — without this, the multi-user features are broken in real use
2. **Action item → Task conversion UI** — this is the product's main AI value proposition
3. **Email password reset** — basic security requirement for any real user

### Phase 2 — Real-time and collaboration (next)
4. **Real-time notifications** (WebSockets or SSE)
5. **Task comments**
6. **Profile picture upload**

### Phase 3 — AI & analytics depth (after)
7. **Meeting Q&A** (RAG over transcripts)
8. **One-click action item to task** (already partially built — just needs frontend)
9. **Analytics export** (PDF/CSV)
10. **Custom date range picker**

### Phase 4 — Production hardening (final)
11. **Celery + Redis** migration for background jobs
12. **Docker Compose** production setup
13. **Rate limiting** on public endpoints
14. **Token encryption** in database
15. **Automated test suite**
16. **OAuth login**

---

## 12. Dev Notes & Conventions

### Migrations
- Use `python migrate_db.py` from the `backend/` directory. **Do not use Alembic.**
- When adding a new value to a PostgreSQL `ENUM` type, the `ALTER TYPE ... ADD VALUE` statement must be committed in its own transaction **before** inserting rows using the new value. Use separate `engine.begin()` blocks in the migration script.

### Team isolation (non-negotiable)
- Every database query that returns team data must include `WHERE team_id = :current_user_team_id`.
- Never query across teams. The `get_current_user` dependency provides `current_user.team_id`.

### Admin guard
- Use the `get_current_admin_user` dependency (not `get_current_user`) on any endpoint that must be admin-only.
- This handles the `403 Forbidden` response automatically.

### AI service usage
- All AI calls go through [backend/app/services/ai_service.py](backend/app/services/ai_service.py).
- Groq is tried first (free). OpenAI is the fallback (paid). Never call Groq or OpenAI directly from a router.
- Groq Whisper has a 25 MB file size limit. Files larger than this need to be chunked or rejected before sending.

### Storage
- All file operations go through [backend/app/utils/storage.py](backend/app/utils/storage.py).
- In dev, files are saved under `backend/uploads/`. In production, set `AWS_ACCESS_KEY_ID` etc. to use S3.

### Frontend API calls
- All API calls are defined in [frontend/lib/api.ts](frontend/lib/api.ts). No `fetch` or `axios` calls in page components.
- Always use TanStack Query (`useQuery`, `useMutation`) in components — never manage loading/error state manually.

### JWT storage
- Tokens are in `localStorage`. This is acceptable for an FYP but note the XSS risk. For a production system, migrate to `httpOnly` cookies.

### Environment variables
- Backend: copy `backend/.env.example` to `backend/.env` and fill in values.
- Minimum required: `DATABASE_URL`, `SECRET_KEY` (≥32 chars), and either `GROQ_API_KEY` or `OPENAI_API_KEY`.
- Frontend: `NEXT_PUBLIC_API_URL=http://localhost:8000` (already set in dev).
