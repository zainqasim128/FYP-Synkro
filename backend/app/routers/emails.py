"""Email endpoints - list, detail, stats, sync from Gmail"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, func, desc
from sqlalchemy.dialects.postgresql import insert as pg_insert
from typing import List, Optional
from datetime import datetime, timedelta, timezone
import uuid
import logging

from app.database import get_db
from app.models import User, Email, Integration, IntegrationPlatform
from app.models.task import Task, TaskStatus, TaskPriority, TaskSourceType
from app.dependencies import get_current_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/emails", tags=["Emails"])


@router.post("/sync")
async def sync_emails(
    limit: int = Query(default=50, le=50),
    days: int = Query(default=15, le=30),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Sync emails from Gmail into the database.
    Deduplicates by gmail_message_id.
    """
    from app.services.gmail_service import fetch_emails

    # Get active Gmail integration
    result = await db.execute(
        select(Integration).where(
            and_(
                Integration.user_id == current_user.id,
                Integration.platform == IntegrationPlatform.GMAIL,
                Integration.is_active == True,
            )
        )
    )
    integration = result.scalar_one_or_none()

    if not integration:
        raise HTTPException(status_code=404, detail="Gmail not connected. Go to Settings to connect.")

    email_addr = integration.platform_metadata.get("email", "")
    app_password = integration.access_token

    try:
        raw_emails = fetch_emails(
            email_addr=email_addr,
            app_password=app_password,
            limit=limit,
            since_days=days,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch emails: {str(e)}")

    from app.services.ai_service import extract_task_from_email

    new_count = 0
    tasks_created = 0
    new_email_ids: list[tuple[str, dict]] = []  # (email_db_id, raw_email)

    for raw in raw_emails:
        # Normalize Message-ID: strip any whitespace/newlines from header folding
        msg_id = (raw.get("gmail_message_id", "") or "").strip()
        if not msg_id:
            continue

        # Parse received_at and normalize to naive UTC (DB uses TIMESTAMP WITHOUT TIME ZONE)
        received_at = None
        if raw.get("received_at"):
            try:
                dt = datetime.fromisoformat(raw["received_at"].replace("Z", "+00:00"))
                if dt.tzinfo is not None:
                    dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
                received_at = dt
            except Exception:
                received_at = None

        email_db_id = str(uuid.uuid4())

        # Use INSERT ... ON CONFLICT DO NOTHING so duplicate syncs never raise errors
        stmt = pg_insert(Email).values(
            id=email_db_id,
            gmail_message_id=msg_id,
            subject=raw.get("subject", "")[:1000],
            sender=raw.get("sender", "")[:500],
            to=raw.get("to", "")[:500],
            body_preview=raw.get("body_preview", "")[:500],
            body=raw.get("body", ""),
            received_at=received_at,
            is_read=raw.get("is_read", False),
            is_flagged=raw.get("is_flagged", False),
            ai_classification=None,
            ai_summary=None,
            user_id=current_user.id,
            integration_id=integration.id,
            created_at=datetime.utcnow(),
        ).on_conflict_do_nothing(constraint="uq_emails_user_gmail_id")

        result = await db.execute(stmt)
        if result.rowcount > 0:
            new_count += 1
            new_email_ids.append((email_db_id, raw))

    # Update last synced
    integration.last_synced_at = datetime.utcnow()
    await db.commit()

    # Auto-extract tasks from newly synced emails using AI
    for email_db_id, raw in new_email_ids:
        try:
            task_info = await extract_task_from_email(
                subject=raw.get("subject", ""),
                sender=raw.get("sender", ""),
                body=raw.get("body", ""),
            )
            if task_info.get("has_task"):
                priority_map = {
                    "low": TaskPriority.LOW,
                    "medium": TaskPriority.MEDIUM,
                    "high": TaskPriority.HIGH,
                    "urgent": TaskPriority.URGENT,
                }
                priority = priority_map.get(
                    (task_info.get("priority") or "medium").lower(), TaskPriority.MEDIUM
                )

                due_date = None
                raw_due = task_info.get("due_date")
                if raw_due:
                    try:
                        due_date = datetime.strptime(raw_due, "%Y-%m-%d")
                    except Exception:
                        due_date = None

                new_task = Task(
                    title=(task_info.get("title") or raw.get("subject", "Task from email"))[:500],
                    description=task_info.get("description") or f"Extracted from email: {raw.get('subject', '')}",
                    status=TaskStatus.TODO,
                    priority=priority,
                    due_date=due_date,
                    assignee_id=current_user.id,
                    created_by_id=current_user.id,
                    team_id=current_user.team_id,
                    source_type=TaskSourceType.AI,
                    source_id=email_db_id,
                )
                db.add(new_task)
                tasks_created += 1
        except Exception as e:
            logger.warning(f"Failed to extract task from email {email_db_id}: {e}")
            continue

    if tasks_created:
        await db.commit()

    logger.info(f"Synced {new_count} new emails, auto-created {tasks_created} tasks for user {current_user.id}")

    return {
        "message": f"Synced {new_count} new emails" + (f", created {tasks_created} task(s) from email content" if tasks_created else ""),
        "new_count": new_count,
        "total_fetched": len(raw_emails),
        "tasks_created": tasks_created,
    }


@router.get("")
async def list_emails(
    limit: int = Query(default=20, le=50),
    offset: int = Query(default=0, ge=0),
    is_read: Optional[bool] = None,
    is_flagged: Optional[bool] = None,
    search: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """List synced emails with filters and pagination."""
    query = select(Email).where(Email.user_id == current_user.id)

    if is_read is not None:
        query = query.where(Email.is_read == is_read)
    if is_flagged is not None:
        query = query.where(Email.is_flagged == is_flagged)
    if search:
        query = query.where(
            Email.subject.ilike(f"%{search}%") | Email.sender.ilike(f"%{search}%")
        )

    query = query.order_by(desc(Email.received_at)).limit(limit).offset(offset)

    result = await db.execute(query)
    emails = result.scalars().all()

    return [
        {
            "id": e.id,
            "subject": e.subject,
            "sender": e.sender,
            "body_preview": e.body_preview,
            "received_at": e.received_at.isoformat() + "Z" if e.received_at else None,
            "is_read": e.is_read,
            "is_flagged": e.is_flagged,
            "ai_classification": e.ai_classification,
        }
        for e in emails
    ]


@router.get("/stats")
async def email_stats(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get email statistics."""
    base = select(func.count()).select_from(Email).where(Email.user_id == current_user.id)

    total = (await db.execute(base)).scalar() or 0
    unread = (await db.execute(base.where(Email.is_read == False))).scalar() or 0
    flagged = (await db.execute(base.where(Email.is_flagged == True))).scalar() or 0

    return {"total": total, "unread": unread, "flagged": flagged}


@router.post("/seed-demo")
async def seed_demo_emails(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Insert dummy test emails for demo/testing purposes."""
    now = datetime.utcnow()

    demo_emails = [
        {
            "gmail_message_id": f"demo-{uuid.uuid4().hex[:12]}",
            "subject": "Sprint Planning - Q1 Review",
            "sender": "Sarah Chen <sarah.chen@company.com>",
            "to": current_user.email,
            "body_preview": "Hi team, let's review our Q1 progress and plan for the next sprint. Please bring your updates...",
            "body": "Hi team,\n\nLet's review our Q1 progress and plan for the next sprint.\n\nPlease bring your updates on:\n- Current task completion rates\n- Any blockers or dependencies\n- Priorities for next sprint\n\nMeeting is scheduled for Thursday at 2pm.\n\nBest,\nSarah",
            "received_at": now - timedelta(hours=1),
            "is_read": False,
            "is_flagged": True,
            "ai_classification": "action_required",
        },
        {
            "gmail_message_id": f"demo-{uuid.uuid4().hex[:12]}",
            "subject": "Bug Report: Login page crash on mobile",
            "sender": "Dev Team <devteam@company.com>",
            "to": current_user.email,
            "body_preview": "A critical bug has been reported in the login page. Users on iOS 17 are experiencing crashes when...",
            "body": "A critical bug has been reported in the login page.\n\nUsers on iOS 17 are experiencing crashes when tapping the password field. This affects approximately 15% of our mobile users.\n\nSteps to reproduce:\n1. Open app on iOS 17 device\n2. Navigate to login\n3. Tap password field\n4. App crashes\n\nPriority: HIGH\nAssigned to: Frontend Team\n\nPlease investigate ASAP.",
            "received_at": now - timedelta(hours=3),
            "is_read": False,
            "is_flagged": True,
            "ai_classification": "urgent",
        },
        {
            "gmail_message_id": f"demo-{uuid.uuid4().hex[:12]}",
            "subject": "Weekly Standup Notes - Feb 10",
            "sender": "Ali Khan <ali.khan@company.com>",
            "to": current_user.email,
            "body_preview": "Here are the notes from today's standup. Backend: API refactor complete. Frontend: Dashboard redesign in progress...",
            "body": "Here are the notes from today's standup:\n\nBackend Team:\n- API refactor complete\n- Database migration scripts ready\n- Performance testing scheduled for Wednesday\n\nFrontend Team:\n- Dashboard redesign 70% complete\n- New component library integrated\n- Mobile responsive fixes in progress\n\nDevOps:\n- CI/CD pipeline updated\n- Staging environment refreshed\n\nNext standup: Wednesday 10am",
            "received_at": now - timedelta(hours=6),
            "is_read": True,
            "is_flagged": False,
            "ai_classification": "fyi",
        },
        {
            "gmail_message_id": f"demo-{uuid.uuid4().hex[:12]}",
            "subject": "Invoice #INV-2024-0342 Attached",
            "sender": "Billing <billing@cloudhost.io>",
            "to": current_user.email,
            "body_preview": "Your monthly invoice for January 2024 is ready. Total: $127.50. Payment due by Feb 28...",
            "body": "Your monthly invoice for January 2024 is ready.\n\nPlan: Team Pro\nPeriod: Jan 1 - Jan 31, 2024\nTotal: $127.50\n\nPayment due by: Feb 28, 2024\n\nView and pay your invoice online at: https://billing.cloudhost.io/invoices\n\nThank you for your business!\n\n- CloudHost Billing Team",
            "received_at": now - timedelta(days=1),
            "is_read": True,
            "is_flagged": False,
            "ai_classification": "billing",
        },
        {
            "gmail_message_id": f"demo-{uuid.uuid4().hex[:12]}",
            "subject": "Re: API Integration Questions",
            "sender": "Mike Johnson <mike.j@partnerco.com>",
            "to": current_user.email,
            "body_preview": "Thanks for the detailed docs! One more question - does your webhook support retry logic for failed deliveries?",
            "body": "Thanks for the detailed docs! One more question - does your webhook support retry logic for failed deliveries?\n\nWe're planning to go live next week and want to make sure we handle edge cases properly.\n\nAlso, is there a sandbox environment we can test against?\n\nThanks,\nMike",
            "received_at": now - timedelta(days=1, hours=5),
            "is_read": False,
            "is_flagged": False,
            "ai_classification": "needs_reply",
        },
    ]

    count = 0
    for em_data in demo_emails:
        email_record = Email(
            gmail_message_id=em_data["gmail_message_id"],
            subject=em_data["subject"],
            sender=em_data["sender"],
            to=em_data["to"],
            body_preview=em_data["body_preview"],
            body=em_data["body"],
            received_at=em_data["received_at"],
            is_read=em_data["is_read"],
            is_flagged=em_data["is_flagged"],
            ai_classification=em_data["ai_classification"],
            user_id=current_user.id,
            integration_id=None,
        )
        db.add(email_record)
        count += 1

    await db.commit()
    return {"message": f"Created {count} demo emails", "count": count}


@router.patch("/{email_id}/mark-read")
async def mark_email_read(
    email_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Mark an email as read locally and in Gmail."""
    result = await db.execute(
        select(Email).where(and_(Email.id == email_id, Email.user_id == current_user.id))
    )
    email_record = result.scalar_one_or_none()
    if not email_record:
        raise HTTPException(status_code=404, detail="Email not found")

    email_record.is_read = True
    gmail_marked = False

    if email_record.gmail_message_id and not email_record.gmail_message_id.startswith("demo-"):
        integ_result = await db.execute(
            select(Integration).where(
                and_(
                    Integration.user_id == current_user.id,
                    Integration.platform == IntegrationPlatform.GMAIL,
                    Integration.is_active == True,
                )
            )
        )
        integration = integ_result.scalar_one_or_none()
        if integration:
            from app.services.gmail_service import mark_email_as_read_in_gmail
            try:
                gmail_marked = mark_email_as_read_in_gmail(
                    integration.platform_metadata.get("email", ""),
                    integration.access_token,
                    email_record.gmail_message_id,
                )
            except Exception as e:
                logger.warning(f"Could not mark email as read in Gmail: {e}")

    await db.commit()
    return {"ok": True, "gmail_marked": gmail_marked}


@router.delete("/{email_id}")
async def delete_email(
    email_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Delete an email from the database and from Gmail."""
    result = await db.execute(
        select(Email).where(
            and_(Email.id == email_id, Email.user_id == current_user.id)
        )
    )
    email_record = result.scalar_one_or_none()

    if not email_record:
        raise HTTPException(status_code=404, detail="Email not found")

    gmail_deleted = False

    # Only attempt Gmail deletion for real (non-demo) emails
    if email_record.gmail_message_id and not email_record.gmail_message_id.startswith("demo-"):
        # Get Gmail integration credentials
        integ_result = await db.execute(
            select(Integration).where(
                and_(
                    Integration.user_id == current_user.id,
                    Integration.platform == IntegrationPlatform.GMAIL,
                    Integration.is_active == True,
                )
            )
        )
        integration = integ_result.scalar_one_or_none()

        if integration:
            from app.services.gmail_service import delete_email_from_gmail
            email_addr = integration.platform_metadata.get("email", "")
            app_password = integration.access_token
            try:
                gmail_deleted = delete_email_from_gmail(email_addr, app_password, email_record.gmail_message_id)
            except Exception as e:
                logger.warning(f"Could not delete email from Gmail: {e}")

    await db.delete(email_record)
    await db.commit()

    return {"message": "Email deleted", "gmail_deleted": gmail_deleted}


@router.get("/{email_id}")
async def get_email(
    email_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get a single email with full body."""
    result = await db.execute(
        select(Email).where(
            and_(Email.id == email_id, Email.user_id == current_user.id)
        )
    )
    email_record = result.scalar_one_or_none()

    if not email_record:
        raise HTTPException(status_code=404, detail="Email not found")

    return {
        "id": email_record.id,
        "gmail_message_id": email_record.gmail_message_id,
        "subject": email_record.subject,
        "sender": email_record.sender,
        "to": email_record.to,
        "body_preview": email_record.body_preview,
        "body": email_record.body,
        "received_at": email_record.received_at.isoformat() + "Z" if email_record.received_at else None,
        "is_read": email_record.is_read,
        "is_flagged": email_record.is_flagged,
        "ai_classification": email_record.ai_classification,
        "ai_summary": email_record.ai_summary,
        "created_at": email_record.created_at.isoformat() + "Z",
    }
