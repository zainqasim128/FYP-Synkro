# Synkro — Project Context & Complete Technical Reference

**Final Year Project (FYP)**
An AI-Powered Workspace Orchestration System for software development teams.

---

## Table of Contents

1. [Project Overview](#1-project-overview)
2. [Technology Stack](#2-technology-stack)
3. [Repository Structure](#3-repository-structure)
4. [Backend — Routers & Endpoints](#4-backend--routers--endpoints)
5. [Backend — Database Models](#5-backend--database-models)
6. [Backend — Services](#6-backend--services)
7. [Backend — Celery Background Tasks](#7-backend--celery-background-tasks)
8. [Backend — Configuration & Environment Variables](#8-backend--configuration--environment-variables)
9. [Backend — Authentication System](#9-backend--authentication-system)
10. [Database Relationships](#10-database-relationships)
11. [Alembic Migrations](#11-alembic-migrations)
12. [Frontend — Pages & Routes](#12-frontend--pages--routes)
13. [Frontend — Components](#13-frontend--components)
14. [Frontend — API Modules](#14-frontend--api-modules)
15. [Frontend — Stores](#15-frontend--stores)
16. [Frontend — TypeScript Types](#16-frontend--typescript-types)
17. [Third-Party Integrations](#17-third-party-integrations)
18. [AI Pipeline — Meeting Transcription](#18-ai-pipeline--meeting-transcription)
19. [Feature Implementation Log](#19-feature-implementation-log)

---

## 1. Project Overview

**Synkro** is a centralised team productivity platform designed for software development teams. It connects all the tools a team uses — meetings, tasks, Slack, Gmail, Jira, and Zoom — into one AI-augmented dashboard.

### Core Capabilities

| Area | What It Does |
|------|-------------|
| **Meeting Intelligence** | Upload or auto-import Zoom recordings; AI transcribes, identifies speakers, classifies every utterance (task assignment, warning, decision, etc.), and extracts action items with deadlines and assignees |
| **Task Management** | Create, assign, and track tasks across statuses and priorities; auto-convert meeting action items into assigned tasks; sync bidirectionally with Jira |
| **Messaging** | View and search Slack channel messages; send/receive Slack DMs from within Synkro; native in-app DM system with unread count badge |
| **Email** | Sync and read Gmail emails via IMAP App Password (no Google Cloud OAuth required) |
| **Analytics** | Team workload charts, per-member task balance, overdue tracking, meeting insights, productivity trend |
| **AI Chat** | Natural-language interface to query team data (tasks, meetings, workload) with suggested actions |
| **Integrations** | Slack OAuth, Jira Cloud, Zoom OAuth + webhooks, Gmail IMAP |

---

## 2. Technology Stack

### Backend
| Component | Technology |
|-----------|-----------|
| Framework | FastAPI (Python 3.11) |
| Database | PostgreSQL (async via asyncpg) |
| ORM | SQLAlchemy 2.x (async) |
| Migrations | Alembic |
| Background Tasks | FastAPI BackgroundTasks (primary) + Celery (legacy) |
| Message Broker | Redis (for Celery) |
| Auth | JWT (PyJWT) + bcrypt (passlib) |
| AI — Transcription | Groq Whisper `whisper-large-v3-turbo` (free, primary) / OpenAI `whisper-1` (paid, fallback) |
| AI — Analysis | Groq `llama-3.3-70b-versatile` (free, primary) / OpenAI `gpt-4` (paid, fallback) |
| Speaker Diarization | pyannote.audio (Tier 1) → AssemblyAI (Tier 2) → LLM inference (Tier 3 fallback) |
| File Storage | AWS S3 / Cloudinary / local filesystem |
| Token Encryption | Fernet (cryptography library) for OAuth tokens at rest |
| Deadline Parsing | dateparser library |

### Frontend
| Component | Technology |
|-----------|-----------|
| Framework | Next.js 14 (App Router) |
| Language | TypeScript |
| State Management | Zustand (auth store, theme store) |
| Server State | TanStack Query (React Query v5) |
| HTTP Client | Axios |
| Styling | Tailwind CSS v3 |
| UI Components | Radix UI primitives (shadcn/ui pattern) |
| Icons | Lucide React |

---

## 3. Repository Structure

```
fypsynkro/
├── README.md                     Project overview and setup guide
├── PLAN.md                       Feature roadmap (39KB)
├── CLAUDE.md                     Claude Code context file
├── PROJECT_CONTEXT.md            This file
├── .gitignore
├── Recording 2026-01-04 *.mp3/4  Sample meeting recordings for testing
├── meeting demo .mp3             Demo audio file
│
├── backend/
│   ├── .env                      Active environment variables (not committed)
│   ├── .env.example              Template for all env vars
│   ├── Dockerfile
│   ├── Procfile                  Railway/Heroku start command
│   ├── alembic.ini
│   ├── requirements.txt
│   ├── railway.json
│   ├── docker-compose.yml        Postgres + Redis + backend
│   ├── pytest.ini
│   ├── QUICK_START.md
│   ├── WHISPER_SETUP.md
│   │
│   ├── alembic/
│   │   ├── env.py                Async SQLAlchemy Alembic env
│   │   ├── script.py.mako
│   │   └── versions/             7 migration files (see §11)
│   │
│   ├── app/
│   │   ├── main.py               FastAPI app factory, middleware, router registration, lifespan
│   │   ├── config.py             Pydantic Settings — all env vars
│   │   ├── database.py           Async engine, session factory, Base, init_db
│   │   ├── dependencies.py       get_current_user, get_current_admin_user
│   │   ├── celery_app.py         Celery instance
│   │   │
│   │   ├── models/               SQLAlchemy ORM models (see §5)
│   │   ├── routers/              FastAPI route handlers (see §4)
│   │   ├── schemas/              Pydantic request/response models
│   │   ├── services/             Business logic + external API wrappers (see §6)
│   │   ├── tasks/                Celery tasks (see §7)
│   │   └── utils/
│   │       ├── security.py       Password hashing, JWT, Fernet encrypt/decrypt
│   │       └── storage.py        S3 / Cloudinary / local storage abstraction
│   │
│   ├── scripts/                  Utility scripts
│   ├── tests/                    pytest test suite
│   ├── uploads/                  Local upload directory (dev)
│   ├── create_test_user.py
│   ├── debug_frontend.py
│   ├── init_db.py
│   ├── migrate_db.py
│   └── migrate_email_constraint.py
│
└── frontend/
    ├── .env.local                NEXT_PUBLIC_API_URL=http://localhost:8000
    ├── next.config.js
    ├── tailwind.config.ts
    ├── tsconfig.json
    ├── package.json
    │
    ├── app/                      Next.js App Router pages (see §12)
    ├── components/               Shared React components (see §13)
    ├── lib/                      API client, utilities, Zustand stores (see §14, §15)
    └── types/
        └── index.ts              All TypeScript type definitions (see §16)
```

---

## 4. Backend — Routers & Endpoints

### `auth.py` — `/api/auth`

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| POST | `/register` | — | Register user; creates or joins Team; auto-provisions Slack in demo mode |
| POST | `/login` | — | OAuth2 password login; returns `access_token` + `refresh_token` |
| POST | `/refresh` | — | Exchange refresh token for new access token |
| GET | `/me` | Bearer | Get current user profile |
| PATCH | `/me` | Bearer | Update `full_name`, `avatar_url`, `timezone` |
| POST | `/logout` | — | Stateless client-side logout |
| POST | `/forgot-password` | — | Generate reset token (returned in response in dev mode) |
| POST | `/reset-password` | — | Reset password with token |
| GET | `/roles` | — | List all roles with descriptions |
| GET | `/admin-exists` | — | Check if an admin is already registered |
| GET | `/team-members` | Bearer | List all users in the current user's team |
| POST | `/invite` | Admin Bearer | Generate a one-time team invite token |
| GET | `/invite/validate` | — | Validate an invite token; returns team name + role |
| GET | `/invitations` | Admin Bearer | List all invitations for the admin's team |
| DELETE | `/invitations/{id}` | Admin Bearer | Revoke an unused invitation |

### `tasks.py` — `/api/tasks`

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `` | Bearer | List tasks with filters: `status`, `priority`, `assignee_id` (`unassigned` supported), `due_before`, `due_after`; limit up to 200 |
| POST | `` | Bearer | Create task; fires Celery: Jira sync + Slack notification |
| GET | `/stats` | Bearer | Counts by status, overdue count, completion rate |
| GET | `/{task_id}` | Bearer | Get single task |
| PATCH | `/{task_id}` | Bearer | Update task; syncs to Jira inline if `external_id` set |
| DELETE | `/{task_id}` | Bearer | Delete task |

### `meetings.py` — `/api/meetings`

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| POST | `/upload` | Admin | Upload audio file; store to S3/Cloudinary/local; queue background pipeline |
| POST | `/{id}/upload` | Bearer | Attach recording to AWAITING_UPLOAD meeting (Zoom Track B) |
| GET | `` | Bearer | List meetings (team-scoped) with filters |
| GET | `/{id}` | Bearer | Get meeting with `action_items` eager-loaded |
| PATCH | `/{id}` | Bearer | Update meeting title/metadata |
| PATCH | `/{id}/speaker-names` | Bearer | Save speaker name mappings; **auto-assigns** pending action items to matched team members as tasks |
| GET | `/{id}/pending-assignments` | Bearer | Return pending action items with `suggested_assignee_id` pre-computed |
| POST | `/{id}/bulk-assign` | Bearer | Batch-convert action items to tasks with explicit assignees |
| GET | `/{id}/export` | Bearer | Download transcript or summary as plain text attachment |
| DELETE | `/{id}` | Bearer | Delete meeting + recording file |
| POST | `/{id}/retry` | Bearer | Re-queue failed/stuck transcription |
| POST | `/{id}/action-items/{ai_id}/convert` | Bearer | Convert single action item → task |
| POST | `/{id}/action-items/{ai_id}/reject` | Bearer | Reject action item |
| GET | `/whisper-status` | — | Check local Whisper availability |

### `integrations.py` — `/api/integrations`

| Method | Path | Description |
|--------|------|-------------|
| GET | `` | List all integrations for current user |
| POST | `/gmail/connect` | Connect Gmail via IMAP App Password |
| GET | `/gmail/emails` | Fetch recent emails via IMAP |
| POST | `/slack/demo-connect` | Provision Slack from `DEMO_SLACK_TOKEN` env var |
| GET | `/slack/start` | Start Slack OAuth flow; return authorisation URL |
| GET | `/slack/callback` | Slack OAuth callback; exchange code, store encrypted token |
| GET | `/oauth/slack/callback` | Legacy alias |
| POST | `/jira/connect` | Connect Jira Cloud (email + API token); validates via `/myself` |
| GET | `/jira/test` | Verify Jira credentials |
| GET | `/jira/projects` | List Jira projects |
| GET | `/zoom/start` | Start Zoom OAuth flow |
| GET | `/zoom/callback` | Zoom OAuth callback |
| GET | `/zoom/test` | Test Zoom connection |
| POST | `/zoom/webhook` | Zoom webhook: url_validation, meeting.ended, recording.completed |
| POST | `/{id}/sync` | Trigger manual sync (Slack channel messages) |
| DELETE | `/{id}` | Disconnect integration |

### `analytics.py` — `/api/analytics`

| Method | Path | Description |
|--------|------|-------------|
| GET | `/workload` | Tasks by status/priority, overdue, completion rate |
| GET | `/team-workload` | Per-member: active tasks, completed (30d), overdue, estimated hours |
| GET | `/meeting-insights` | Meeting counts, action item stats, avg duration |
| GET | `/productivity-trend` | Daily created/completed task counts |

### `messages.py` — `/api/messages`

| Method | Path | Description |
|--------|------|-------------|
| GET | `` | List Slack/platform channel messages |
| GET | `/stats` | Total, Slack, DM counts |
| GET | `/dms` | Slack DM conversations grouped by sender |
| POST | `/dms/send` | Send Slack DM via Slack API; mirrors to recipient Synkro user |
| GET | `/dms/users` | List Slack workspace users available to DM |

### `direct_messages.py` — `/api/dm`

| Method | Path | Description |
|--------|------|-------------|
| GET | `/users` | Team members available to DM |
| GET | `/conversations` | List conversation threads (most recent first) |
| GET | `/{user_id}` | Full message thread with a user; marks as read |
| POST | `/send` | Send native DM; also sends Slack bot notification |
| GET | `/unread-count` | Count unread DMs for current user |
| POST | `/sync-slack` | Import last 24h of Slack DMs using user OAuth token |
| DELETE | `/message/{id}` | Delete single sent message |
| DELETE | `/clear-all` | Delete all DMs for current user |
| DELETE | `/clear-synced` | Delete all Slack-synced DMs |

### `admin.py` — `/api/admin`

| Method | Path | Description |
|--------|------|-------------|
| GET | `/users` | All users (admin only) |
| GET | `/users/count` | Counts by role, active/inactive, new in 30d |
| GET | `/users/team` | All users in admin's team |
| PATCH | `/users/{id}/role` | Change a user's role |
| PATCH | `/users/{id}/toggle-active` | Activate/deactivate a user |
| DELETE | `/users/{id}` | Delete user |
| DELETE | `/users` | Delete all users except requesting admin |

### `emails.py` — `/api/emails`

| Method | Path | Description |
|--------|------|-------------|
| POST | `/sync` | Pull emails from Gmail IMAP into DB (deduplicates) |
| GET | `` | List synced emails with filters and pagination |
| GET | `/stats` | Total, unread, flagged counts |
| POST | `/seed-demo` | Insert 5 demo emails for testing |
| GET | `/{id}` | Get single email with full body |

### `chat.py` — `/api/chat`

| Method | Path | Description |
|--------|------|-------------|
| POST | `/query` | Natural-language query; gathers context, calls LLM, returns response + suggested actions |

### `slack_webhooks.py` — `/api/webhooks/slack/events`

| Method | Path | Description |
|--------|------|-------------|
| POST | `/events` | Handle Slack Events API: url_verification challenge, message persistence, DM creation, Celery intent classification |

---

## 5. Backend — Database Models

### `users` table (`app/models/user.py`)

| Field | Type | Notes |
|-------|------|-------|
| `id` | String(36) UUID PK | Auto-generated |
| `email` | String(255) UNIQUE | Indexed |
| `password_hash` | String(255) | bcrypt |
| `full_name` | String(255) | |
| `avatar_url` | String(500) | nullable |
| `timezone` | String(50) | Default: UTC |
| `role` | Enum | `admin` / `project_manager` / `team_lead` / `senior_developer` / `developer` / `intern` |
| `is_active` | Boolean | |
| `is_verified` | Boolean | |
| `password_reset_token` | String(255) | nullable |
| `password_reset_expires` | DateTime | nullable |
| `team_id` | FK → `teams.id` | |
| `created_at` / `updated_at` | DateTime | |

Relationships: `team`, `assigned_tasks`, `created_tasks`, `integrations`, `messages`, `emails`, `sent_dms`, `received_dms`

---

### `teams` table (`app/models/team.py`)

| Field | Type | Notes |
|-------|------|-------|
| `id` | String(36) UUID PK | |
| `name` | String(255) | |
| `plan` | Enum | `free` / `pro` / `enterprise` |
| `settings` | JSON | |
| `created_at` | DateTime | |

---

### `tasks` table (`app/models/task.py`)

| Field | Type | Notes |
|-------|------|-------|
| `id` | String(36) UUID PK | |
| `title` | String(500) | |
| `description` | Text | nullable |
| `status` | Enum | `todo` / `in_progress` / `done` / `blocked` |
| `priority` | Enum | `low` / `medium` / `high` / `urgent` |
| `due_date` | DateTime | nullable |
| `estimated_hours` | Integer | nullable |
| `source_type` | Enum | `manual` / `meeting` / `message` / `ai` |
| `source_id` | String(36) | nullable — ID of originating meeting/message |
| `external_id` | String(255) | nullable — Jira issue key |
| `assignee_id` | FK → `users.id` | nullable, indexed |
| `created_by_id` | FK → `users.id` | nullable |
| `team_id` | FK → `teams.id` | |
| `created_at` / `updated_at` | DateTime | |

Composite indexes: `(status, assignee_id)`, `(team_id, status)`

---

### `meetings` table (`app/models/meeting.py`)

| Field | Type | Notes |
|-------|------|-------|
| `id` | String(36) UUID PK | |
| `title` | String(500) | |
| `scheduled_at` | DateTime | nullable |
| `duration_minutes` | Integer | nullable |
| `recording_url` | String(1000) | S3/Cloudinary/local URL |
| `transcript` | Text | Plain or speaker-labeled transcript |
| `diarized_transcript` | Text | JSON array of `{speaker, start, end, text, context_type}` |
| `speaker_names` | Text | JSON mapping `{"Speaker A": "Alice"}` |
| `summary` | Text | AI-generated summary |
| `status` | Enum | `awaiting_upload` / `scheduled` / `processing` / `transcribed` / `completed` / `failed` |
| `zoom_meeting_id` | String(100) | nullable, indexed |
| `zoom_recording_id` | String(100) | nullable — dedup guard |
| `team_id` | FK → `teams.id` | |
| `created_by_id` | FK → `users.id` | nullable |
| `created_at` / `updated_at` | DateTime | |

Composite index: `(team_id, status)` | Relationship: `action_items` (cascade delete-orphan)

---

### `action_items` table (`app/models/action_item.py`)

| Field | Type | Notes |
|-------|------|-------|
| `id` | String(36) UUID PK | |
| `description` | Text | AI-extracted task description |
| `assignee_mentioned` | String(255) | nullable — name or email extracted from transcript |
| `deadline_mentioned` | DateTime | nullable — parsed via `dateparser` |
| `confidence_score` | Float | AI confidence 0–1 |
| `status` | Enum | `pending` / `converted` / `rejected` |
| `speaker_label` | String(50) | nullable — e.g. `"Speaker A"` (added Migration 007) |
| `assigned_by` | String(255) | nullable — speaker who gave the assignment |
| `context_type` | String(30) | nullable — `task_assignment`, `warning`, etc. |
| `meeting_id` | FK → `meetings.id` | nullable |
| `message_id` | FK → `messages.id` | nullable |
| `task_id` | FK → `tasks.id` | nullable — linked when converted (SET NULL on delete) |
| `created_at` | DateTime | |

---

### `messages` table (`app/models/message.py`)

| Field | Type | Notes |
|-------|------|-------|
| `id` | String(36) UUID PK | |
| `external_id` | String(255) UNIQUE | Slack `ts` or platform message ID |
| `platform` | String(50) | `gmail`, `slack`, etc. |
| `sender_email` / `sender_name` | String | nullable |
| `content` | Text | |
| `timestamp` | DateTime | |
| `thread_id` | String(255) | nullable |
| `channel_id` | String(255) | nullable (Migration 001) |
| `channel_type` | String(50) | nullable — `channel` / `im` / `mpim` |
| `processed` | Boolean | |
| `intent` | Enum | `task_request` / `blocker` / `question` / `information` / `urgent_issue` / `casual` |
| `entities` | JSON | Extracted entities + DM `direction` (sent/received) |
| `user_id` | FK → `users.id` | |
| `created_at` | DateTime | |

---

### `direct_messages` table (`app/models/direct_message.py`)

| Field | Type | Notes |
|-------|------|-------|
| `id` | String(36) UUID PK | |
| `sender_id` | FK → `users.id` | |
| `recipient_id` | FK → `users.id` | |
| `content` | Text | |
| `read_at` | DateTime | nullable |
| `slack_ts` | String(32) | nullable, indexed — Slack timestamp for dedup |
| `created_at` | DateTime | |

---

### `emails` table (`app/models/email.py`)

| Field | Type | Notes |
|-------|------|-------|
| `id` | String(36) UUID PK | |
| `gmail_message_id` | String(500) | Unique per user (`uq_emails_user_gmail_id`) |
| `subject` | String(1000) | |
| `sender` / `to` | String(500) | |
| `body_preview` | String(500) | |
| `body` | Text | |
| `received_at` | DateTime | nullable |
| `is_read` / `is_flagged` | Boolean | |
| `ai_classification` | String(50) | nullable — `task_request`, `urgent`, `fyi`, etc. |
| `ai_summary` | Text | nullable |
| `user_id` | FK → `users.id` | |
| `integration_id` | FK → `integrations.id` | nullable |
| `created_at` | DateTime | |

Composite index: `(user_id, received_at)` | Unique: `(user_id, gmail_message_id)`

---

### `integrations` table (`app/models/integration.py`)

| Field | Type | Notes |
|-------|------|-------|
| `id` | String(36) UUID PK | |
| `platform` | Enum | `gmail` / `slack` / `google_calendar` / `jira` / `microsoft_teams` / `zoom` |
| `access_token` | String(1000) | **Fernet-encrypted at rest** |
| `refresh_token` | String(1000) | nullable, Fernet-encrypted |
| `expires_at` | DateTime | nullable |
| `scope` | String(500) | nullable |
| `is_active` | Boolean | |
| `platform_metadata` | JSON | Slack: `{team_id, bot_user_id, authed_user_id}` · Jira: `{domain, email, account_id}` · Zoom: `{zoom_user_id, email}` |
| `last_synced_at` | DateTime | nullable |
| `user_id` | FK → `users.id` | |
| `created_at` / `updated_at` | DateTime | |

---

## 6. Backend — Services

### `ai_service.py`
Central AI service using Groq (free, preferred) with OpenAI as paid fallback.

- `transcribe_meeting_with_segments(file_path)` — Calls `whisper-large-v3-turbo` (Groq) / `whisper-1` (OpenAI) with `verbose_json` format to get per-segment timestamps + plain text transcript
- `summarize_meeting(transcript, diarized_transcript)` — Calls Llama-3.3-70b to generate structured meeting summary with key decisions, action items overview, and next steps
- `extract_action_items(transcript)` — Extracts action items with assignee, deadline, and confidence score
- `classify_message_intent(content)` — Classifies Slack message as `task_request`, `blocker`, `question`, `information`, `urgent_issue`, or `casual`
- `extract_entities(content)` — NER: people, dates, projects, priorities
- `generate_chat_response(query, context)` — Answers natural-language queries about team data

### `diarization_service.py`
3-tier speaker diarization with automatic fallback:

| Tier | Method | Requirement | Output |
|------|--------|-------------|--------|
| 1 | pyannote.audio (local) | `HUGGINGFACE_TOKEN` + accepted model license | Speaker segments with timestamps |
| 2 | AssemblyAI (cloud) | `ASSEMBLYAI_API_KEY` (5h/month free) | Speaker segments with timestamps |
| 3 | LLM inference (Groq) | Just `GROQ_API_KEY` — always available | LLM infers speaker turns from conversation patterns |

Output: JSON array of `{speaker: "Speaker A", start: 0.0, end: 5.2, text: "..."}` stored in `meetings.diarized_transcript`

### `meeting_analysis_service.py`
Enriches diarized segments with context classification:

- Sends transcript to Llama-3.3-70b with a structured prompt
- Returns `enriched_segments` (each with `context_type`, `context_details`)
- Returns `action_items` with speaker attribution (`speaker_label`, `assigned_by`), confidence score, parsed deadline
- Returns `speakers` list and `meeting_stats` (total turns, classification breakdown)

Context types: `task_assignment`, `task_completion`, `warning`, `progress_update`, `question`, `decision`, `general`

### `jira_service.py`
Jira Cloud REST API v3 wrapper:

- Credential validation via `GET /rest/api/3/myself`
- `create_issue(project_key, title, description)` — Creates issue with ADF description
- `update_issue(issue_key, fields)` — Updates fields
- `get_transitions(issue_key)` — Lists available workflow transitions
- `transition_issue(issue_key, transition_name)` — Transitions status with dynamic name lookup
- `list_projects()` — Returns available Jira projects
- Exponential backoff on HTTP 429

### `slack_service.py`
Slack Web API wrapper:

- OAuth: `get_authorization_url()`, `exchange_code()`, `auth_test()`
- Messages: `post_message(channel, text, blocks)`, `open_dm_channel(user_id)`, `send_dm(user_id, text)`
- Users: `get_users_list()`, `get_user_by_id(user_id)`, `get_user_by_email(email)`
- Channels: `list_channels()`, `get_channel_history(channel_id)`
- Verification: `verify_slack_signature(headers, body, signing_secret)` — HMAC-SHA256

### `zoom_service.py`
Zoom OAuth 2.0 wrapper:

- `get_authorization_url()`, `exchange_code()`, `refresh_token()`
- `get_user_info(access_token)` — GET `/users/me`
- `download_recording(url, access_token)` — Download cloud recording file
- `verify_webhook_signature(request)` — HMAC-SHA256 verification

### `gmail_service.py`
Gmail IMAP service (no Google Cloud OAuth):

- Connect via App Password (`imaplib.IMAP4_SSL`)
- `test_connection()` — Validate credentials
- `fetch_emails(days, limit)` — Parse headers, body (HTML → text), attachments

### `whisper_local.py`
Optional local Whisper check:

- `check_whisper_availability()` — Returns install status, version, system info

---

## 7. Backend — Celery Background Tasks

### `meeting_tasks.py`
- `transcribe_meeting_task(meeting_id)` — Legacy Celery pipeline: download audio → Whisper transcription → save transcript → chain to summarisation
- `process_message_for_intent(message_id)` — Classify Slack message intent and extract entities; runs after webhook ingestion

### `integration_tasks.py`
- `sync_task_to_jira(task_id, user_id)` — Create or update Jira issue from a Task; idempotent on `task.external_id`; retries up to 3×
- `notify_slack_task_created(task_id, user_id)` — Post Block Kit message to Slack when a task is created; retries up to 3×

> The active production transcription path is `process_meeting_background()` (async `BackgroundTask` in `meetings.py`), not Celery.

---

## 8. Backend — Configuration & Environment Variables

Defined in `app/config.py` as a Pydantic `Settings` class. All values are read from `.env`.

| Variable | Purpose |
|----------|---------|
| `SECRET_KEY` | JWT signing secret |
| `ALGORITHM` | JWT algorithm (`HS256`) |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | 30 minutes |
| `REFRESH_TOKEN_EXPIRE_DAYS` | 7 days |
| `DATABASE_URL` | `postgresql+asyncpg://...` |
| `REDIS_URL` | Redis connection for Celery |
| `CELERY_BROKER_URL` / `CELERY_RESULT_BACKEND` | Celery broker/backend |
| `OPENAI_API_KEY` | Paid fallback AI |
| `GROQ_API_KEY` | Free preferred AI (Whisper + Llama) |
| `HUGGINGFACE_TOKEN` | pyannote.audio diarization (Tier 1) |
| `ASSEMBLYAI_API_KEY` | AssemblyAI diarization (Tier 2) |
| `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` / `AWS_BUCKET_NAME` / `AWS_REGION` | S3 storage |
| `CLOUDINARY_CLOUD_NAME` / `CLOUDINARY_API_KEY` / `CLOUDINARY_API_SECRET` | Cloudinary storage |
| `ALLOWED_ORIGINS` | CORS origins (JSON array) |
| `GMAIL_EMAIL` / `GMAIL_APP_PASSWORD` | Default Gmail credentials |
| `SLACK_CLIENT_ID` / `SLACK_CLIENT_SECRET` / `SLACK_REDIRECT_URI` / `SLACK_SIGNING_SECRET` | Slack OAuth + Events API |
| `ZOOM_CLIENT_ID` / `ZOOM_CLIENT_SECRET` / `ZOOM_REDIRECT_URI` / `ZOOM_WEBHOOK_SECRET_TOKEN` | Zoom OAuth + webhook |
| `FRONTEND_URL` | Used in OAuth redirect URLs |
| `DEMO_SLACK_TOKEN` / `DEMO_SLACK_TEAM_ID` | Demo mode: auto-provision Slack for all new users |

---

## 9. Backend — Authentication System

- **Method:** Stateless JWT Bearer tokens
- **Access token TTL:** 30 minutes
- **Refresh token TTL:** 7 days
- **Storage (client):** `localStorage` (`access_token`, `refresh_token`)
- **Password hashing:** bcrypt via passlib
- **OAuth token encryption:** Fernet symmetric encryption for all integration tokens stored in DB

### Role Hierarchy

```
admin > project_manager > team_lead > senior_developer > developer > intern
```

### Team Auto-Join Logic
- First registered user with `admin` role creates a new Team
- Subsequent non-admin users automatically join the existing admin's Team
- Second admin registration is rejected (only one admin per system)

### Password Reset Flow
- `POST /forgot-password` → generates token → **currently returns token in response** (dev convenience; production should email it)
- `POST /reset-password` → verifies token + expiry → hashes and saves new password

### Request Authentication
- Every request: `get_current_user` dependency extracts `user_id` from JWT, loads User from DB
- Admin-only routes: `get_current_admin_user` dependency — raises HTTP 403 for non-admin roles
- Frontend axios interceptor: on 401, queues pending requests, refreshes token, replays queue; on failure clears storage and redirects to `/login`

---

## 10. Database Relationships

```
teams
 ├── users (team_id FK)
 │    ├── tasks as assignee (assignee_id FK)
 │    ├── tasks as creator (created_by_id FK)
 │    ├── meetings as creator (created_by_id FK)
 │    ├── integrations (user_id FK)
 │    │    └── emails (integration_id FK)
 │    ├── messages (user_id FK)
 │    │    └── action_items (message_id FK)
 │    ├── emails (user_id FK)
 │    ├── sent direct_messages (sender_id FK)
 │    └── received direct_messages (recipient_id FK)
 │
 ├── tasks (team_id FK)
 │    └── action_items.task_id (SET NULL on delete)
 │
 └── meetings (team_id FK)
      └── action_items (meeting_id FK, cascade delete-orphan)
```

---

## 11. Alembic Migrations

All migration files are in `backend/alembic/versions/`.

| File | Change |
|------|--------|
| `001_add_channel_fields_to_messages.py` | Add `channel_id` (String), `channel_type` (String) to `messages` |
| `002_add_entities_and_external_id.py` | Add `entities` (JSON), `external_id` (String) to `messages` |
| `003_add_direct_messages.py` | Create `direct_messages` table (sender_id, recipient_id, content, read_at, slack_ts) |
| `004_add_zoom_integration.py` | Add `ZOOM` to `IntegrationPlatform` enum; add `AWAITING_UPLOAD` to `MeetingStatus` enum; add `zoom_meeting_id`, `zoom_recording_id` to `meetings` |
| `005_add_cols.py` | Miscellaneous column additions |
| `006_add_channel_cols.py` | Additional channel-related columns |
| `007_add_action_item_cols.py` | Add `speaker_label`, `assigned_by`, `context_type` to `action_items` |
| `008_add_calendar_automation.py` | Google Calendar integration tables and preferences |
| `009_add_google_meet_link.py` | Add `google_meet_link` to `meetings` |
| `010_add_meeting_fields_to_tasks.py` | Add `is_meeting_task`, `google_meet_link`, `meeting_scheduled_at`, `meeting_duration_minutes` to `tasks` |
| `011_add_team_invitations.py` | Create `team_invitations` table for invite-based team join flow |

Run migrations: `alembic upgrade head`

---

## 12. Frontend — Pages & Routes

All pages are in `frontend/app/` using Next.js App Router.

### Public Routes
| Path | File | Description |
|------|------|-------------|
| `/login` | `login/page.tsx` | Email + password login form; redirects to `/dashboard` on success |
| `/register` | `register/page.tsx` | Registration with role selection dropdown; first user becomes admin |

### Dashboard Routes (all behind auth guard in `dashboard/layout.tsx`)
| Path | File | Description |
|------|------|-------------|
| `/dashboard` | `dashboard/page.tsx` | Home: task stats cards, recent tasks list, recent meetings list, quick action buttons, admin user count panel |
| `/dashboard/tasks` | `dashboard/tasks/page.tsx` | Task manager: list with status/priority/assignee filters, Work Balance Panel (admin), overdue alert, source badges, prominent assignee chip, edit/delete dialogs |
| `/dashboard/meetings` | `dashboard/meetings/page.tsx` | Meeting list: upload form (admin), status polling every 5s, delete, retry |
| `/dashboard/meetings/[id]` | `dashboard/meetings/[id]/page.tsx` | Meeting detail: speaker-colored diarized transcript, context classification badges, inline speaker name editor, action items with TaskAssignmentDialog, export buttons |
| `/dashboard/emails` | `dashboard/emails/page.tsx` | Gmail email list: sync button, read/flag status, email detail slide-out |
| `/dashboard/slack` | `dashboard/slack/page.tsx` | Slack channel messages: sync, search, intent badges |
| `/dashboard/slack/dms` | `dashboard/slack/dms/page.tsx` | Slack DMs: conversation list, send DM to Slack workspace users |
| `/dashboard/messages` | `dashboard/messages/page.tsx` | Native in-app DMs: conversation threads, real-time-style chat UI, new conversation picker |
| `/dashboard/chat` | `dashboard/chat/page.tsx` | AI chat: natural-language query → LLM response with context + suggested actions |
| `/dashboard/analytics` | `dashboard/analytics/page.tsx` | Analytics: workload stats, team workload table, meeting insights, productivity trend |
| `/dashboard/settings` | `dashboard/settings/page.tsx` | Profile edit, integration cards (Gmail/Slack/Jira/Zoom), admin user management panel |

### `dashboard/layout.tsx`
- Sidebar navigation with links to all routes
- Unread DM badge (polls `/api/dm/unread-count` every 10 seconds)
- Dark mode toggle (syncs with `themeStore`)
- Auth guard: redirects to `/login` if not authenticated
- Mobile-responsive collapsible sidebar

---

## 13. Frontend — Components

All in `frontend/components/`.

### `auth-initializer.tsx`
Runs `authStore.initialize()` on first mount to restore session from `localStorage` tokens.

### `create-task-dialog.tsx`
Modal dialog for creating a new task:
- Fetches team members via `dmApi.getUsers()` for the assignee dropdown
- Fields: title, description, status, priority, assignee, due date, estimated hours, source type
- On submit: `POST /api/tasks` → invalidates `tasks` and `task-stats` query caches

### `task-assignment-dialog.tsx`
Modal for bulk-assigning meeting action items to team members:
- Receives `pendingItems` (with AI-suggested assignee pre-filled) and `teamMembers`
- Each item shows: description, speaker display name, `assignee_mentioned`, deadline, confidence score
- Dropdown per item to select team member (pre-filled with suggestion)
- Counter: "N of M items assigned"
- On confirm: `POST /api/meetings/{id}/bulk-assign` → invalidates meeting + tasks caches

### `ui/` directory
Radix UI primitive wrappers following the shadcn/ui pattern:
- `badge.tsx` — Variants: default, secondary, destructive, outline
- `button.tsx` — Variants: default, outline, ghost, destructive; sizes: default, sm, lg, icon
- `card.tsx` — Card, CardHeader, CardContent, CardTitle, CardDescription, CardFooter
- `dialog.tsx` — Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter
- `input.tsx` — Styled HTML input
- `label.tsx` — Styled HTML label
- `textarea.tsx` — Styled HTML textarea

---

## 14. Frontend — API Modules (`lib/api.ts`)

Single Axios instance (`baseURL = NEXT_PUBLIC_API_URL`, `timeout = 30s`) with two interceptors:
1. **Request** — attaches `Authorization: Bearer <token>` from `localStorage`
2. **Response** — on 401: queues requests → refreshes token → replays; on failure: clears tokens → redirects to `/login`

| Export | Key Methods |
|--------|------------|
| `authApi` | `register`, `login`, `refresh`, `me`, `updateProfile`, `logout`, `forgotPassword`, `resetPassword`, `getRoles`, `checkAdminExists`, `getTeamMembers` |
| `adminApi` | `getAllUsers`, `getUserCount`, `getTeamUsers`, `updateUserRole`, `toggleUserActive`, `deleteUser`, `deleteAllUsers` |
| `taskApi` | `getTasks(params)`, `getTask(id)`, `createTask(data)`, `updateTask(id, data)`, `deleteTask(id)`, `getStats()` |
| `meetingApi` | `getMeetings(params)`, `getMeeting(id)`, `uploadMeeting(formData)`, `retryMeeting(id)`, `uploadToMeeting(id, formData)`, `deleteMeeting(id)`, `convertActionItem(meetingId, itemId)`, `rejectActionItem(meetingId, itemId)`, `updateSpeakerNames(meetingId, names)`, `exportTranscript(meetingId, format)`, `getPendingAssignments(meetingId)`, `bulkAssignActionItems(meetingId, assignments)` |
| `chatApi` | `query(message)`, `getHistory()` |
| `emailApi` | `getEmails(params)`, `getEmail(id)`, `syncEmails(params)`, `getStats()`, `seedDemo()` |
| `messagesApi` | `getMessages(params)`, `getStats()`, `getDmConversations()`, `getSlackUsers()`, `sendDm(payload)` |
| `integrationsApi` | `getIntegrations()`, `connectGmail(creds)`, `startSlackOAuth()`, `connectSlackDemo()`, `connectJira(creds)`, `disconnectIntegration(id)`, `syncIntegration(id)`, `startZoomOAuth()`, `testZoomConnection()` |
| `dmApi` | `getUsers()`, `getConversations()`, `getConversation(userId)`, `sendMessage(payload)`, `getUnreadCount()`, `clearAllDms()`, `deleteMessage(id)` |
| `analyticsApi` | `getWorkload(days)`, `getTeamWorkload()`, `getMeetingInsights()`, `getProductivityTrend(days)` |

---

## 15. Frontend — Stores (`lib/stores/`)

### `authStore.ts` (Zustand)

| State | Type | Description |
|-------|------|-------------|
| `user` | `User \| null` | Current authenticated user |
| `isAuthenticated` | boolean | |
| `isLoading` | boolean | |
| `error` | `string \| null` | |

| Action | Description |
|--------|-------------|
| `initialize()` | Reads `access_token` from localStorage; calls `/api/auth/me`; sets `user` |
| `login(email, password)` | POST `/api/auth/login`; stores tokens; sets `user` |
| `register(data)` | POST `/api/auth/register`; stores tokens; sets `user` |
| `logout()` | Clears tokens from localStorage; resets state |
| `fetchUser()` | Re-fetches `/api/auth/me` to sync profile changes |
| `clearError()` | Resets `error` to null |

### `themeStore.ts` (Zustand)

| State | Type | Description |
|-------|------|-------------|
| `theme` | `'light' \| 'dark'` | Current theme; persisted to localStorage |

| Action | Description |
|--------|-------------|
| `toggleTheme()` | Flips theme; adds/removes `.dark` class on `<html>` |

---

## 16. Frontend — TypeScript Types (`types/index.ts`)

| Type | Description |
|------|-------------|
| `UserRole` | Union: `admin \| project_manager \| team_lead \| senior_developer \| developer \| intern` |
| `USER_ROLES[]` | Array of `{value, label, description}` for registration dropdowns |
| `ROLE_LABELS` | Record mapping role value to display string |
| `User` | Full user object from API |
| `Team` | Team object |
| `Task` | Task object including nested `assignee?: Partial<User>` and `creator?: Partial<User>` |
| `TaskStats` | `{total, todo, in_progress, done, blocked, overdue, completion_rate}` |
| `ContextType` | Union: 7 meeting context classification types |
| `DiarizedSegment` | `{speaker, start, end, text, context_type?, context_details?}` |
| `Meeting` | Full meeting including `action_items: ActionItem[]`, `diarized_transcript`, `speaker_names` |
| `ActionItem` | Action item with `speaker_label`, `assigned_by`, `context_type` |
| `ChatQuery` / `ChatResponse` | AI chat request/response including `context_used` and `suggested_actions[]` |
| `Integration` | Integration record |
| `WorkloadAnalytics` | Task counts and completion stats |
| `TeamMemberWorkload` | Per-member: `active_tasks`, `completed_last_30_days`, `overdue_tasks`, `estimated_hours` |
| `MeetingInsights` | Meeting counts and action item stats |
| `ProductivityTrendDay` | `{date, created, completed}` |
| `AdminUserStats` | Counts by role, active/inactive, new users |

---

## 17. Third-Party Integrations

### Slack
- **Auth:** OAuth 2.0 (captures both bot token and user OAuth token)
- **Bot scopes:** `channels:read`, `channels:history`, `im:history`, `im:read`, `im:write`, `users:read`, `chat:write`, `users:read.email`
- **Events API webhook** (`/api/webhooks/slack/events`): HMAC-SHA256 signature verification; handles `url_verification` challenge and `message` events
- **Demo mode:** `DEMO_SLACK_TOKEN` env var auto-provisions Slack for every new user at registration (no OAuth needed)
- **Features:** Channel message sync, send/receive DMs from Synkro, Slack DM → DirectMessage sync, bot notifications for new tasks and new native DMs

### Jira Cloud
- **Auth:** Basic Auth with email + API token
- **API:** REST v3 (`/rest/api/3/`)
- **Features:** Credential validation, create/update issues (ADF description), dynamic status transition lookup, list projects
- **Sync trigger:** Task create → Celery `sync_task_to_jira`; Task update → inline async sync
- **Bidirectional:** Jira issue key stored in `task.external_id` for idempotent updates

### Zoom
- **Auth:** OAuth 2.0 authorization code flow
- **Webhook events (HMAC-SHA256 verified):**
  - `endpoint.url_validation` — Respond with challenge hash during setup
  - `meeting.ended` — Create `AWAITING_UPLOAD` meeting record; send Slack DM to host with upload link (Track B)
  - `recording.completed` — Download M4A/MP4 from cloud; store to S3/Cloudinary; queue full AI pipeline (Track A)
- **Manual upload fallback:** User can also upload recording manually from the meeting detail page

### Gmail
- **Auth:** IMAP with App Password (no Google Cloud project required)
- **Features:** Connection test, fetch emails from last N days, sync to DB with per-user deduplication

### Groq (Primary AI)
- **Model used:** `whisper-large-v3-turbo` (transcription), `llama-3.3-70b-versatile` (all LLM tasks)
- **Cost:** Free tier with rate limits

### OpenAI (Fallback AI)
- **Models:** `whisper-1` (transcription), `gpt-4` (LLM tasks)
- **Cost:** Paid

### AssemblyAI (Diarization Tier 2)
- **Feature:** Speaker diarization with timestamps
- **Cost:** Free tier: 5 hours/month

### pyannote.audio (Diarization Tier 1)
- **Feature:** Local speaker diarization (best quality)
- **Requirement:** `HUGGINGFACE_TOKEN` + accept model license agreement at `hf.co/pyannote/speaker-diarization-3.1`

---

## 18. AI Pipeline — Meeting Transcription

The full pipeline is implemented as `process_meeting_background(meeting_id)` in `backend/app/routers/meetings.py`. It runs as a FastAPI `BackgroundTask` (not Celery).

```
Audio File
    │
    ▼
[Stage 1] Whisper Transcription
    groq.whisper-large-v3-turbo (primary)
    openai.whisper-1 (fallback)
    Output: plain transcript + whisper_segments [{start, end, text}]
    Also: duration calculated via mutagen
    │
    ▼
[Stage 2] Speaker Diarization
    Tier 1: pyannote.audio (local)  requires HUGGINGFACE_TOKEN
    Tier 2: AssemblyAI (cloud)      requires ASSEMBLYAI_API_KEY
    Tier 3: LLM inference (Groq)    always available
    Output: [{speaker: "Speaker A", start, end, text}]
    Stored in: meetings.diarized_transcript (JSON)
    │
    ▼
[Stage 3] Context Analysis
    Model: llama-3.3-70b-versatile (Groq)
    Input: diarized transcript
    Output:
      - enriched_segments (each with context_type + context_details)
      - action_items [{description, assignee_mentioned, deadline, confidence, speaker_label, assigned_by}]
      - speakers list
      - meeting_stats
    │
    ▼
[Stage 4] Summarisation + Persistence
    - AI summary generated (speaker-aware)
    - Action items with confidence ≥ 0.6 persisted to action_items table
    - Deadlines parsed via dateparser
    - meeting.status → "completed"
```

### Speaker Name Resolution (Post-Pipeline)
After transcription, users can map speaker labels to real names:
1. `PATCH /api/meetings/{id}/speaker-names` with `{"Speaker A": "Alice", "Speaker B": "Bob"}`
2. Backend fuzzy-matches each mapped name against team member `full_name`/`email`
3. Matching pending action items are auto-converted to tasks with the matched user as `assignee_id`
4. Frontend `TaskAssignmentDialog` opens automatically when meeting completes with pending items, with AI-suggested assignees pre-filled

---

## 19. Feature Implementation Log

This section documents every significant feature and when/how it was implemented.

### Initial Foundation
- FastAPI backend with async SQLAlchemy, Alembic migrations, JWT auth
- Next.js 14 frontend with TanStack Query, Zustand, Tailwind CSS
- User registration/login with role-based access (6 roles)
- Single-admin enforcement + team auto-join for non-admin users
- Basic task CRUD (create, read, update, delete, filter)
- Dashboard home with stats and quick actions

### Meeting Upload & Transcription
- Admin-only audio file upload (`POST /api/meetings/upload`)
- Whisper-based transcription via Groq (free) with OpenAI fallback
- `process_meeting_background()` async pipeline (no Celery required)
- Meeting status polling on frontend (5-second interval during processing)
- Meeting list page with upload form, status badges, delete, retry

### Speaker Diarization
- `diarization_service.py` with 3-tier fallback (pyannote → AssemblyAI → LLM)
- Diarized segments stored as JSON in `meetings.diarized_transcript`
- Speaker-colored transcript view in meeting detail page (5 colors per speaker)
- Inline speaker name editor with team member suggestions and fuzzy dedup

### Context-Aware Meeting Analysis
- `meeting_analysis_service.py` classifies every utterance with context type
- 7 context types with emoji badges in frontend
- Speaking time chart per speaker
- Context stats panel in meeting detail summary tab
- Action items with `speaker_label`, `assigned_by`, `context_type` (Migration 007)

### Jira Integration
- Connect via email + API token; validate via Jira REST `/myself`
- Task create triggers Celery `sync_task_to_jira` → creates Jira issue
- Task update triggers inline Jira sync → updates fields + transitions status
- `task.external_id` stores Jira issue key for idempotent sync
- Dynamic transition name lookup (not hardcoded status names)

### Slack Integration
- OAuth 2.0 with demo-mode fallback (`DEMO_SLACK_TOKEN`)
- Events API webhook with HMAC verification
- Channel message sync + intent classification (Celery)
- DM send/receive from Synkro UI
- Slack DM → DirectMessage sync
- Bot notifications: new tasks and new native DMs

### Gmail Integration
- IMAP App Password connection (no Google Cloud project)
- Email sync with deduplication by `(user_id, gmail_message_id)`
- Email list with read/flag status and full body view

### Zoom Integration
- OAuth 2.0 flow
- Track A: `recording.completed` webhook → auto-download → pipeline
- Track B: `meeting.ended` → AWAITING_UPLOAD state → user uploads manually
- Zoom DM notification to host on meeting end
- Zoom badge on meeting detail page

### Native In-App DMs
- `direct_messages` table (Migration 003)
- Full conversation UI with real-time-style polling
- Unread count badge in sidebar (10s poll)
- `POST /api/dm/sync-slack` to import Slack DMs
- Deduplication via `slack_ts` column

### AI Chat
- `/dashboard/chat` page with conversation UI
- Backend gathers task/team/meeting context → Llama-3.3-70b
- Response includes `context_used` metadata and `suggested_actions[]`

### Export Feature
- `GET /api/meetings/{id}/export?format=txt|summary`
- PlainTextResponse with `Content-Disposition: attachment` header
- Download buttons in meeting detail transcript and summary tabs

### Task Auto-Assignment (Most Recent — Meeting Speaker Name Resolution)
- `PATCH /api/meetings/{id}/speaker-names` now auto-assigns action items
- Fuzzy match of `assignee_mentioned` or speaker display name → team member
- `GET /api/meetings/{id}/pending-assignments` returns items with suggested assignees
- `POST /api/meetings/{id}/bulk-assign` batch-converts items to tasks

### Task Assignment Dialog (Most Recent — UI)
- `components/task-assignment-dialog.tsx` — popup with per-item assignee dropdowns
- Pre-filled with AI-suggested assignees from speaker name matching
- Auto-shows when meeting transitions `processing → completed` with pending items
- Manual trigger via "Assign Tasks" button in Action Items tab

### Enhanced Tasks Page (Most Recent)
- **Work Balance Panel** (admin/PM/team-lead): per-member bar chart with active/done/overdue counts; click-to-filter
- **Assignee filter dropdown** for admins — filter by member or "Unassigned"
- **Overdue alert banner** — red banner counting overdue tasks
- **Prominent assignee chip** — indigo pill with name (amber "Unassigned" for admins)
- Non-admin users automatically see only their own assigned tasks
- Task query limit raised to 200; `assignee_id=unassigned` filter supported in backend

### Admin Features
- User management panel in `/dashboard/settings` (role change, activate/deactivate, delete)
- `GET /api/admin/users/count` — breakdown by role + active status
- Admin-only: upload meetings, create tasks, see all team tasks
- Role-based UI rendering throughout (CreateTaskDialog, delete buttons, Work Balance Panel)

### Team Invitation System (2026-05-16)
- `POST /api/auth/invite` — admin creates a 7-day one-time invite token (optional email lock + role)
- `GET /api/auth/invite/validate?token=` — public; validates token; returns team name + role
- `GET /api/auth/invitations` — admin lists their team's invitations
- `DELETE /api/auth/invitations/{id}` — admin revokes unused invite
- `POST /api/auth/register` — now accepts `invite_token`; overrides team + role from the invitation; marks token as used
- `backend/app/models/team_invitation.py` — new `TeamInvitation` ORM model
- Migration 011: `team_invitations` table with token uniqueness index
- `frontend/app/register/page.tsx` — `?invite=<token>` URL auto-validates, shows "Join [Team]" banner, locks role
- `frontend/app/dashboard/settings/page.tsx` — admin "Team Invitations" panel with create form, pending list, copy-link, revoke
