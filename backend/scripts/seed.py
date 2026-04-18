"""
Seed script - Populate the database with demo data for testing.

Usage:
    cd backend
    python -m scripts.seed

Requires the database to be running and tables created.
"""
import asyncio
import uuid
from datetime import datetime, timedelta
import random

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sqlalchemy.ext.asyncio import AsyncSession
from app.database import AsyncSessionLocal, engine, Base
from app.utils.security import get_password_hash
from app.models import (
    Team, TeamPlan,
    User, UserRole,
    Task, TaskStatus, TaskPriority, TaskSourceType,
    Meeting, MeetingStatus,
    ActionItem, ActionItemStatus,
)


# ── Demo Data ─────────────────────────────────────────────────────────────────

TEAM_NAME = "Synkro Demo Team"
DEFAULT_PASSWORD = "password123"  # All demo users share this password

USERS = [
    {"full_name": "Alice Johnson", "email": "alice@synkro.dev", "role": UserRole.ADMIN},
    {"full_name": "Bob Smith", "email": "bob@synkro.dev", "role": UserRole.DEVELOPER},
    {"full_name": "Carol Williams", "email": "carol@synkro.dev", "role": UserRole.DEVELOPER},
    {"full_name": "Dave Brown", "email": "dave@synkro.dev", "role": UserRole.DEVELOPER},
]

TASKS = [
    # To-do tasks
    {"title": "Design system color tokens", "description": "Define primary, secondary, and accent colors for the design system.", "status": TaskStatus.TODO, "priority": TaskPriority.HIGH, "estimated_hours": 4},
    {"title": "Write API documentation", "description": "Document all REST endpoints using OpenAPI spec.", "status": TaskStatus.TODO, "priority": TaskPriority.MEDIUM, "estimated_hours": 8},
    {"title": "Set up CI/CD pipeline", "description": "Configure GitHub Actions for automated testing and deployment.", "status": TaskStatus.TODO, "priority": TaskPriority.HIGH, "estimated_hours": 6},
    {"title": "Add email notification service", "description": "Integrate SendGrid for transactional emails.", "status": TaskStatus.TODO, "priority": TaskPriority.LOW, "estimated_hours": 5},

    # In-progress tasks
    {"title": "Implement user dashboard", "description": "Build the main dashboard with task stats, recent activity, and quick actions.", "status": TaskStatus.IN_PROGRESS, "priority": TaskPriority.URGENT, "estimated_hours": 12},
    {"title": "Meeting transcription pipeline", "description": "Connect Whisper API to process uploaded meeting recordings.", "status": TaskStatus.IN_PROGRESS, "priority": TaskPriority.HIGH, "estimated_hours": 10},
    {"title": "Database query optimization", "description": "Add indexes and optimize slow queries in task listing.", "status": TaskStatus.IN_PROGRESS, "priority": TaskPriority.MEDIUM, "estimated_hours": 3},

    # Done tasks
    {"title": "User authentication system", "description": "JWT-based auth with register, login, refresh, and logout.", "status": TaskStatus.DONE, "priority": TaskPriority.URGENT, "estimated_hours": 8},
    {"title": "Database schema design", "description": "Design and implement all SQLAlchemy models.", "status": TaskStatus.DONE, "priority": TaskPriority.URGENT, "estimated_hours": 6},
    {"title": "Project scaffolding", "description": "Set up FastAPI backend and Next.js frontend structure.", "status": TaskStatus.DONE, "priority": TaskPriority.HIGH, "estimated_hours": 4},
    {"title": "Task CRUD API", "description": "Create, read, update, delete endpoints for tasks.", "status": TaskStatus.DONE, "priority": TaskPriority.HIGH, "estimated_hours": 5},
    {"title": "Frontend routing and layout", "description": "Set up Next.js app router with dashboard layout.", "status": TaskStatus.DONE, "priority": TaskPriority.MEDIUM, "estimated_hours": 3},

    # Blocked tasks
    {"title": "Slack integration", "description": "OAuth flow and message sync for Slack. Blocked: waiting for Slack app approval.", "status": TaskStatus.BLOCKED, "priority": TaskPriority.MEDIUM, "estimated_hours": 8},
    {"title": "Deploy to production", "description": "Deploy to AWS ECS. Blocked: waiting for infrastructure provisioning.", "status": TaskStatus.BLOCKED, "priority": TaskPriority.HIGH, "estimated_hours": 6},
]

MEETINGS = [
    {
        "title": "Sprint Planning - Week 12",
        "status": MeetingStatus.COMPLETED,
        "duration_minutes": 45,
        "days_ago": 7,
        "summary": "Sprint planning session for week 12. The team agreed to focus on completing the AI transcription pipeline and dashboard UI. Alice will lead the backend work while Bob and Carol handle frontend components. Dave will work on testing and documentation.\n\nKey decisions:\n- Prioritize meeting transcription over Slack integration\n- Use Whisper API for transcription instead of building custom model\n- Target demo-ready state by end of sprint",
        "transcript": "Alice: Good morning everyone. Let's plan our sprint for this week.\n\nBob: I think we should focus on the dashboard. Users need a clean overview.\n\nCarol: Agreed. I can work on the task cards and stats components.\n\nDave: I'll write tests for the API endpoints we finished last week.\n\nAlice: Great. I'll continue the meeting transcription pipeline. We should use the Whisper API - it's more reliable than building our own.\n\nBob: Makes sense. What about the Slack integration?\n\nAlice: Let's push that to next sprint. The transcription feature is more valuable for the demo.\n\nCarol: I agree. Dashboard and transcription are the priorities.\n\nDave: I'll also start on the API documentation.\n\nAlice: Perfect. Let's aim to be demo-ready by Friday.",
        "action_items": [
            {"description": "Complete meeting transcription pipeline using Whisper API", "assignee_mentioned": "Alice", "confidence_score": 0.95},
            {"description": "Build dashboard task cards and statistics components", "assignee_mentioned": "Carol", "confidence_score": 0.92},
            {"description": "Write API endpoint tests for auth and task modules", "assignee_mentioned": "Dave", "confidence_score": 0.88},
            {"description": "Start API documentation using OpenAPI spec", "assignee_mentioned": "Dave", "confidence_score": 0.85},
        ],
    },
    {
        "title": "Design Review - UI Components",
        "status": MeetingStatus.COMPLETED,
        "duration_minutes": 30,
        "days_ago": 5,
        "summary": "Design review session for the UI component library. The team reviewed the sidebar navigation, card components, and badge designs. Decided to use shadcn/ui as the component base with custom Tailwind theme tokens.\n\nFeedback:\n- Sidebar needs active state highlighting\n- Cards should have hover effects for clickable items\n- Status badges need consistent color coding across the app",
        "transcript": "Bob: Let me walk through the component designs I've put together.\n\nBob: Starting with the sidebar - we have icons for each section: Dashboard, Tasks, Meetings, Chat, and Settings.\n\nCarol: Looks clean. Can we add an active state indicator? Maybe highlight the background.\n\nBob: Good idea. I'll add a primary color background for the active route.\n\nAlice: What about the cards? They look a bit flat.\n\nBob: I was thinking hover shadows for interactive cards. Let me show the meeting card design.\n\nCarol: The status badges need consistent colors. Processing should be blue, completed green, failed red.\n\nDave: We should document these color conventions.\n\nAlice: Agreed. Let's use shadcn/ui as our base and customize from there.",
        "action_items": [
            {"description": "Add active state highlighting to sidebar navigation", "assignee_mentioned": "Bob", "confidence_score": 0.93},
            {"description": "Implement hover shadows on interactive card components", "assignee_mentioned": "Bob", "confidence_score": 0.87},
            {"description": "Standardize status badge color coding across the application", "assignee_mentioned": "Carol", "confidence_score": 0.90},
        ],
    },
    {
        "title": "Daily Standup - Monday",
        "status": MeetingStatus.COMPLETED,
        "duration_minutes": 15,
        "days_ago": 2,
        "summary": "Quick daily standup. Everyone shared progress updates. Alice completed the Whisper integration. Bob is finishing the analytics page. Carol is debugging a styling issue on mobile. Dave completed unit tests for the auth module.",
        "transcript": None,
        "action_items": [
            {"description": "Fix mobile responsive layout issue on meetings page", "assignee_mentioned": "Carol", "confidence_score": 0.82},
        ],
    },
    {
        "title": "Architecture Discussion - Scaling Plan",
        "status": MeetingStatus.TRANSCRIBED,
        "duration_minutes": 60,
        "days_ago": 1,
        "summary": None,
        "transcript": "Alice: We need to think about how this scales beyond the demo.\n\nDave: The main bottleneck will be the transcription pipeline. Whisper API calls can take minutes for long recordings.\n\nAlice: That's why we have Celery. Background tasks handle the heavy lifting.\n\nBob: What about the database? Are we going to hit query performance issues?\n\nAlice: We have indexes on the key columns. For the demo scale, PostgreSQL is more than enough.\n\nCarol: Should we add caching? Redis is already in our stack.\n\nAlice: Good point. We can cache task stats and analytics data. Those don't change frequently.\n\nDave: What about file storage for recordings?\n\nAlice: We support both S3 and local filesystem. For production, we'll use S3 with pre-signed URLs.",
        "action_items": [],
    },
]


async def seed():
    """Seed the database with demo data."""
    print("Seeding database with demo data...")

    # Create tables
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    print("  Tables created/verified.")

    async with AsyncSessionLocal() as db:
        # ── Team ──────────────────────────────────────────────────────────
        team_id = str(uuid.uuid4())
        team = Team(
            id=team_id,
            name=TEAM_NAME,
            plan=TeamPlan.PRO,
            settings={"ai_features": True, "max_meetings_per_month": 100},
        )
        db.add(team)
        await db.flush()
        print(f"  Created team: {TEAM_NAME}")

        # ── Users ─────────────────────────────────────────────────────────
        user_ids = []
        password_hash = get_password_hash(DEFAULT_PASSWORD)

        for u in USERS:
            user_id = str(uuid.uuid4())
            user_ids.append(user_id)
            user = User(
                id=user_id,
                email=u["email"],
                password_hash=password_hash,
                full_name=u["full_name"],
                role=u["role"],
                team_id=team_id,
                is_active=True,
                is_verified=True,
            )
            db.add(user)
            print(f"  Created user: {u['full_name']} ({u['email']})")

        await db.flush()

        # ── Tasks ─────────────────────────────────────────────────────────
        now = datetime.utcnow()
        for i, t in enumerate(TASKS):
            assignee_id = user_ids[i % len(user_ids)]
            creator_id = user_ids[0]  # Alice creates all tasks

            # Generate a due date: done tasks in the past, others in the future
            if t["status"] == TaskStatus.DONE:
                due_date = now - timedelta(days=random.randint(1, 10))
                created_at = now - timedelta(days=random.randint(11, 20))
            elif t["status"] == TaskStatus.BLOCKED:
                due_date = now + timedelta(days=random.randint(1, 5))
                created_at = now - timedelta(days=random.randint(5, 10))
            else:
                due_date = now + timedelta(days=random.randint(2, 14))
                created_at = now - timedelta(days=random.randint(1, 7))

            task = Task(
                id=str(uuid.uuid4()),
                title=t["title"],
                description=t["description"],
                status=t["status"],
                priority=t["priority"],
                estimated_hours=t["estimated_hours"],
                due_date=due_date,
                assignee_id=assignee_id,
                created_by_id=creator_id,
                team_id=team_id,
                source_type=TaskSourceType.MANUAL,
                created_at=created_at,
            )
            db.add(task)

        await db.flush()
        print(f"  Created {len(TASKS)} tasks.")

        # ── Meetings & Action Items ───────────────────────────────────────
        for m in MEETINGS:
            meeting_id = str(uuid.uuid4())
            created_at = now - timedelta(days=m["days_ago"])
            meeting = Meeting(
                id=meeting_id,
                title=m["title"],
                status=m["status"],
                duration_minutes=m["duration_minutes"],
                transcript=m.get("transcript"),
                summary=m.get("summary"),
                team_id=team_id,
                created_by_id=user_ids[0],
                created_at=created_at,
            )
            db.add(meeting)
            await db.flush()

            # Action items
            for ai_item in m.get("action_items", []):
                action_item = ActionItem(
                    id=str(uuid.uuid4()),
                    description=ai_item["description"],
                    assignee_mentioned=ai_item.get("assignee_mentioned"),
                    confidence_score=ai_item["confidence_score"],
                    status=ActionItemStatus.PENDING,
                    meeting_id=meeting_id,
                    created_at=created_at,
                )
                db.add(action_item)

        await db.flush()
        print(f"  Created {len(MEETINGS)} meetings with action items.")

        # Commit all
        await db.commit()

    print("\nSeed complete! Demo credentials:")
    print(f"  Email:    alice@synkro.dev")
    print(f"  Password: {DEFAULT_PASSWORD}")
    print(f"  (All users share the same password)")


if __name__ == "__main__":
    asyncio.run(seed())
