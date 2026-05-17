"""Messages router - list Slack/platform messages and send Slack DMs"""
from fastapi import APIRouter, Depends, Query, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, or_, and_
from typing import Optional

from app.database import get_db
from app.models import Message, Integration, IntegrationPlatform
from app.models.user import User
from app.dependencies import get_current_user

router = APIRouter(prefix="/api/messages", tags=["Messages"])


@router.get("")
async def list_messages(
    platform: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    channel_type: Optional[str] = Query(None),
    limit: int = Query(50, le=200),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    # Slack channel messages (not DMs) are workspace-wide — visible to all users.
    # DM messages and non-Slack messages remain scoped to the owning user.
    if platform == "slack":
        query = select(Message).where(
            Message.platform == "slack",
            # Exclude DMs (im/mpim) from the shared view — those stay personal
            Message.channel_type.notin_(["im", "mpim"]),
        )
    else:
        query = select(Message).where(Message.user_id == current_user.id)
        if platform:
            query = query.where(Message.platform == platform)

    if search:
        query = query.where(Message.content.ilike(f"%{search}%"))
    if channel_type:
        query = query.where(Message.channel_type == channel_type)
    query = query.order_by(Message.timestamp.desc()).limit(limit)
    result = await db.execute(query)
    messages = result.scalars().all()
    return [
        {
            "id": m.id,
            "platform": m.platform,
            "sender_name": m.sender_name,
            "sender_email": m.sender_email,
            "content": m.content,
            "timestamp": (m.timestamp.isoformat() + "Z") if m.timestamp else None,
            "thread_id": m.thread_id,
            "channel_id": m.channel_id,
            "channel_type": m.channel_type,
            "intent": m.intent,
            "processed": m.processed,
        }
        for m in messages
    ]


@router.get("/stats")
async def message_stats(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(func.count()).select_from(Message).where(Message.user_id == current_user.id)
    )
    total = result.scalar() or 0
    # Slack channel messages are workspace-wide
    result2 = await db.execute(
        select(func.count()).select_from(Message).where(
            Message.platform == "slack",
            Message.channel_type.notin_(["im", "mpim"]),
        )
    )
    slack_count = result2.scalar() or 0
    result3 = await db.execute(
        select(func.count()).select_from(Message).where(
            Message.user_id == current_user.id,
            Message.platform == "slack",
            Message.channel_type == "im",
        )
    )
    dm_count = result3.scalar() or 0
    return {"total": total, "slack": slack_count, "dms": dm_count}


@router.get("/dms")
async def list_dm_conversations(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return DM messages (channel_type='im' or 'mpim') grouped by sender."""
    result = await db.execute(
        select(Message).where(
            Message.user_id == current_user.id,
            Message.platform == "slack",
            Message.channel_type.in_(["im", "mpim"]),
        ).order_by(Message.timestamp.desc())
    )
    messages = result.scalars().all()

    # Group by channel_id (each DM channel = one conversation)
    conversations: dict = {}
    for m in messages:
        key = m.channel_id or m.sender_name or "unknown"
        entities = m.entities or {}
        is_sent = entities.get("direction") == "sent"
        display_name = (
            entities.get("recipient_name") if is_sent else m.sender_name
        ) or "Unknown"

        if key not in conversations:
            conversations[key] = {
                "channel_id": m.channel_id,
                "channel_type": m.channel_type,
                "sender_name": display_name,
                "slack_user_id": entities.get("recipient_id") if is_sent else entities.get("slack_sender_id"),
                "last_message": m.content,
                "last_timestamp": (m.timestamp.isoformat() + "Z") if m.timestamp else None,
                "unread_count": 0,
                "messages": [],
            }
        conversations[key]["messages"].append({
            "id": m.id,
            "sender_name": m.sender_name if not is_sent else "You",
            "content": m.content,
            "timestamp": (m.timestamp.isoformat() + "Z") if m.timestamp else None,
            "intent": m.intent,
            "direction": "sent" if is_sent else "received",
        })

    return list(conversations.values())


class SendDmRequest(BaseModel):
    slack_user_id: str   # Slack user ID to send to (e.g. U01234)
    message: str
    channel_id: Optional[str] = None  # If already known, skip conversations.open


@router.post("/dms/send")
async def send_dm(
    body: SendDmRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Send a Slack DM to a workspace user."""
    # Get the user's Slack integration
    result = await db.execute(
        select(Integration).where(
            Integration.user_id == current_user.id,
            Integration.platform == IntegrationPlatform.SLACK,
            Integration.is_active == True,
        )
    )
    integration = result.scalars().first()
    if not integration:
        raise HTTPException(status_code=400, detail="Slack not connected")

    from app.services.slack_service import SlackService
    from datetime import datetime
    import uuid as _uuid

    slack = SlackService.from_integration(integration)
    try:
        channel_id = body.channel_id
        if not channel_id:
            channel_id = await slack.open_dm_channel(body.slack_user_id)
        await slack.post_message(channel=channel_id, text=body.message)

        # Resolve recipient display name
        recipient_name = body.slack_user_id
        try:
            user_info = await slack.get_user_info(body.slack_user_id)
            profile = user_info.get("profile", {})
            recipient_name = (
                profile.get("display_name") or profile.get("real_name") or body.slack_user_id
            )
        except Exception:
            pass
    finally:
        await slack.aclose()

    # Save sent message under the sender so they can see it in their DM list
    sent_msg = Message(
        external_id=f"sent-{_uuid.uuid4()}",
        platform="slack",
        sender_name=current_user.full_name or current_user.email,
        sender_email=current_user.email,
        content=body.message,
        timestamp=datetime.utcnow(),
        channel_id=channel_id,
        channel_type="im",
        user_id=current_user.id,
        entities={"recipient_name": recipient_name, "recipient_id": body.slack_user_id, "direction": "sent"},
    )
    db.add(sent_msg)

    # Also save a "received" copy for the recipient if they are a Synkro user,
    # so ONLY the recipient (and sender) can see this DM — not everyone else.
    recipient_integration_result = await db.execute(
        select(Integration).where(
            Integration.platform == IntegrationPlatform.SLACK,
            Integration.is_active == True,
        )
    )
    all_slack_integrations = recipient_integration_result.scalars().all()
    recipient_integration = next(
        (i for i in all_slack_integrations
         if (i.platform_metadata or {}).get("authed_user_id") == body.slack_user_id
         and i.user_id != current_user.id),
        None,
    )
    if recipient_integration:
        received_msg = Message(
            external_id=f"recv-{_uuid.uuid4()}",
            platform="slack",
            sender_name=current_user.full_name or current_user.email,
            sender_email=current_user.email,
            content=body.message,
            timestamp=datetime.utcnow(),
            channel_id=channel_id,
            channel_type="im",
            user_id=recipient_integration.user_id,
            entities={
                "direction": "received",
                "slack_sender_id": (integration.platform_metadata or {}).get("authed_user_id", ""),
                "recipient_id": body.slack_user_id,
                "recipient_name": recipient_name,
            },
        )
        db.add(received_msg)

    await db.commit()

    return {"ok": True, "channel_id": channel_id}


@router.get("/dms/users")
async def list_slack_users(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List workspace users available to DM."""
    result = await db.execute(
        select(Integration).where(
            Integration.user_id == current_user.id,
            Integration.platform == IntegrationPlatform.SLACK,
            Integration.is_active == True,
        )
    )
    integration = result.scalars().first()
    if not integration:
        raise HTTPException(status_code=400, detail="Slack not connected")

    from app.services.slack_service import SlackService
    slack = SlackService.from_integration(integration)
    try:
        users = await slack.list_workspace_users()
    finally:
        await slack.aclose()

    return [
        {
            "id": u["id"],
            "name": u.get("profile", {}).get("display_name") or u.get("real_name") or u.get("name"),
            "real_name": u.get("real_name"),
            "avatar": u.get("profile", {}).get("image_48"),
        }
        for u in users
    ]
