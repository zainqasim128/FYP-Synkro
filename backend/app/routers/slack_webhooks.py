"""
Slack Events API webhook receiver.

Security
--------
Every incoming request is verified against the Slack signing secret using
HMAC-SHA256 before any processing occurs (see SlackService.verify_signature).

Event deduplication
-------------------
Slack may deliver the same event more than once (at-least-once delivery).
We guard against duplicate processing by checking whether a Message row with
the same external_id already exists before inserting.

url_verification challenge
--------------------------
During Slack app setup, Slack sends a one-time challenge that must be echoed
back immediately.  This is handled before signature verification to keep
setup frictionless (the challenge itself is not a security risk).

Async processing
----------------
Message intent classification and task creation are dispatched to Celery
so the webhook endpoint returns within Slack's 3-second timeout window.
"""

import logging
import time
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import Integration, IntegrationPlatform, Message
from app.models.direct_message import DirectMessage
from app.models.user import User
from app.services.slack_service import SlackService

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/webhooks/slack", tags=["Webhooks"])


@router.post(
    "/events",
    summary="Slack Events API endpoint",
    description=(
        "Receives Slack Events API payloads. Verifies the Slack signing secret, "
        "handles url_verification challenges, and dispatches message events to "
        "the background intent classifier."
    ),
)
async def slack_events(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Primary Slack Events API handler.

    Flow:
    1. Read raw body (needed for signature verification).
    2. Respond immediately to ``url_verification`` challenge (Slack setup).
    3. Verify HMAC-SHA256 signature against ``SLACK_SIGNING_SECRET``.
    4. Ignore bot messages and non-message event types.
    5. Look up the Integration record for the workspace (``team_id``).
    6. Deduplicate using ``Message.external_id``.
    7. Persist the Message row.
    8. Enqueue Celery task for intent classification (non-blocking).
    """
    # ── 1. Read raw body before any parsing ──────────────────────────────────
    body_bytes: bytes = await request.body()

    # ── 2. url_verification challenge (Slack app setup) ──────────────────────
    # Handle BEFORE signature check — challenge arrives before the secret is
    # configured in some app setups.  The challenge itself is harmless.
    try:
        payload: dict = await request.json()
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Request body is not valid JSON",
        )

    if payload.get("type") == "url_verification":
        logger.info("Slack url_verification challenge received")
        return {"challenge": payload.get("challenge")}

    logger.info("Slack event received: type=%s team=%s event_type=%s",
                payload.get("type"), payload.get("team_id"), payload.get("event", {}).get("type"))

    # ── 3. Signature verification ─────────────────────────────────────────────
    if not SlackService.verify_signature(dict(request.headers), body_bytes):
        logger.warning(
            "Slack webhook: rejected request with invalid signature "
            "(remote=%s)",
            request.client.host if request.client else "unknown",
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid Slack signature",
        )

    # ── 4. Route on event type ────────────────────────────────────────────────
    event: dict = payload.get("event", {})
    event_type: str = event.get("type", "")

    # Only process user-authored messages (skip bot posts, message edits, etc.)
    if event_type != "message" or event.get("bot_id") or event.get("subtype"):
        return {"ok": True}

    # Skip Synkro's own notification messages (sent via user token, no bot_id)
    if event.get("text", "").startswith("[synkro-notify]"):
        return {"ok": True}

    team_id: str = payload.get("team_id", "")
    if not team_id:
        logger.warning("Slack event payload missing team_id")
        return {"ok": True}

    # ── 5. Resolve workspace → Integration record ─────────────────────────────
    # Fetch all active Slack integrations and filter by team_id in Python
    # (avoids db-specific JSON functions like SQLite's json_extract vs Postgres's ->)
    result = await db.execute(
        select(Integration).where(
            Integration.platform == IntegrationPlatform.SLACK,
            Integration.is_active == True,
        )
    )
    all_integrations = result.scalars().all()
    integration = next(
        (i for i in all_integrations
         if (i.platform_metadata or {}).get("team_id") == team_id),
        None,
    )

    if not integration:
        logger.warning(
            "Slack event received for unknown/inactive team_id=%s", team_id
        )
        return {"ok": True}

    # ── 5b. For DM channels, route to the Synkro user who owns the channel ─────
    channel_id_evt = event.get("channel")
    channel_type_evt = event.get("channel_type")
    slack_sender_id: str = event.get("user", "")

    # Find the sender's integration by matching authed_user_id
    sender_integration_by_uid = next(
        (i for i in all_integrations
         if slack_sender_id and (i.platform_metadata or {}).get("authed_user_id") == slack_sender_id),
        None,
    )
    if sender_integration_by_uid:
        integration = sender_integration_by_uid
        logger.debug("DM event routed via authed_user_id=%s to user=%s", slack_sender_id, integration.user_id)
    elif channel_id_evt and channel_type_evt == "im":
        # Fall back: check which Synkro user has existing messages in this channel
        channel_owner_result = await db.execute(
            select(Message.user_id).where(
                Message.channel_id == channel_id_evt,
                Message.platform == "slack",
            ).limit(1)
        )
        owner_user_id = channel_owner_result.scalar_one_or_none()
        if owner_user_id:
            fallback = next((i for i in all_integrations if i.user_id == owner_user_id), None)
            if fallback:
                integration = fallback

    # ── 6. Resolve sender display name ───────────────────────────────────────
    ts_float: float = float(event.get("ts") or time.time())
    external_id: str = event.get("client_msg_id") or event.get("ts") or ""

    slack_user_id: str = event.get("user", "")
    sender_display_name: str = slack_user_id
    if slack_user_id:
        try:
            slack_svc = SlackService.from_integration(integration)
            user_info = await slack_svc.get_user_info(slack_user_id)
            profile = user_info.get("profile", {})
            sender_display_name = (
                profile.get("display_name")
                or profile.get("real_name")
                or slack_user_id
            )
            await slack_svc.aclose()
        except Exception as exc:
            logger.warning("Could not resolve Slack user %s: %s", slack_user_id, exc)

    # ── 7. Persist message for ALL involved Synkro users ─────────────────────
    # Build a dict of {synkro_user_id: (integration, direction)} for all parties.
    # Dedup is per-user so the same event is stored once per user.

    involved: dict = {}  # synkro_user_id → (integration, direction)

    # ── Method A: payload.authorizations (Slack Events API v2, no extra scope) ──
    # Slack includes an "authorizations" array listing every app installation that
    # should receive this event. This works without im:read scope.
    for auth in payload.get("authorizations", []):
        auth_uid = auth.get("user_id")
        if not auth_uid or auth.get("is_bot"):
            continue
        auth_intg = next(
            (i for i in all_integrations
             if (i.platform_metadata or {}).get("authed_user_id") == auth_uid),
            None,
        )
        if auth_intg:
            is_sender = (auth_uid == slack_user_id)
            direction = "sent" if is_sender else "received"
            involved[auth_intg.user_id] = (auth_intg, direction)

    # ── Method B: conversations.members API (requires im:read scope) ───────────
    # Use as fallback when authorizations didn't cover everyone.
    recipient_slack_id = None
    if channel_type_evt == "im" and channel_id_evt and slack_user_id:
        try:
            ch_svc = SlackService.from_integration(integration)
            members = await ch_svc.get_channel_members(channel_id_evt)
            await ch_svc.aclose()
            for member_uid in members:
                if member_uid == "USLACKBOT":
                    continue
                m_intg = next(
                    (i for i in all_integrations
                     if (i.platform_metadata or {}).get("authed_user_id") == member_uid),
                    None,
                )
                if m_intg and m_intg.user_id not in involved:
                    is_sender = (member_uid == slack_user_id)
                    involved[m_intg.user_id] = (m_intg, "sent" if is_sender else "received")
                    if not is_sender:
                        recipient_slack_id = member_uid
        except Exception as exc:
            logger.warning("Could not get channel members for %s: %s", channel_id_evt, exc)

    # ── Fallback: at minimum store for the routed integration ──────────────────
    if not involved:
        authed_uid = (integration.platform_metadata or {}).get("authed_user_id")
        direction = "sent" if (slack_user_id and slack_user_id == authed_uid) else "received"
        involved[integration.user_id] = (integration, direction)

    # Set recipient_slack_id from authorizations if not already found
    if not recipient_slack_id:
        for auth in payload.get("authorizations", []):
            auth_uid = auth.get("user_id")
            if auth_uid and not auth.get("is_bot") and auth_uid != slack_user_id:
                recipient_slack_id = auth_uid
                break

    parties: list = list(involved.values())

    first_msg = None
    for party_intg, direction in parties:
        # Per-user dedup: same external_id can exist once per user
        if external_id:
            dup_check = await db.execute(
                select(Message.id).where(
                    Message.external_id == external_id,
                    Message.platform == "slack",
                    Message.user_id == party_intg.user_id,
                )
            )
            if dup_check.scalar_one_or_none():
                logger.debug("Dedup skip external_id=%s user=%s", external_id, party_intg.user_id)
                continue

        entities: dict = {"direction": direction, "slack_sender_id": slack_user_id}
        if direction == "sent" and recipient_slack_id:
            entities["recipient_slack_id"] = recipient_slack_id

        msg_obj = Message(
            external_id=external_id or None,
            platform="slack",
            sender_email=None,
            sender_name=sender_display_name,
            content=event.get("text", ""),
            timestamp=datetime.utcfromtimestamp(ts_float),
            thread_id=event.get("thread_ts"),
            channel_id=event.get("channel"),
            channel_type=event.get("channel_type"),
            user_id=party_intg.user_id,
            entities=entities,
        )
        db.add(msg_obj)
        if first_msg is None:
            first_msg = msg_obj

    await db.commit()
    if first_msg is not None:
        await db.refresh(first_msg)

    msg = first_msg  # used by intent task below

    logger.info(
        "Slack message persisted for %d parties: team=%s user=%s ts=%s",
        len(parties),
        team_id,
        event.get("user"),
        event.get("ts"),
    )

    # ── 7b. Create DirectMessage record for /dashboard/messages ──────────────
    if channel_type_evt == "im" and slack_sender_id:
        # Derive sender/recipient Synkro IDs from the involved dict
        sender_synkro_id = None
        recipient_synkro_id = None

        for uid, (party_intg, direction) in involved.items():
            if direction == "sent":
                sender_synkro_id = uid
            else:
                recipient_synkro_id = uid

        # Fallback: email lookup for users not in involved
        if not sender_synkro_id:
            try:
                bot_svc = SlackService.from_integration(integration)
                user_info = await bot_svc.get_user_info(slack_sender_id)
                profile = user_info.get("profile", {})
                sender_email = profile.get("email", "").lower()
                await bot_svc.aclose()
                if sender_email:
                    sender_result = await db.execute(
                        select(User).where(User.email == sender_email, User.is_active == True)
                    )
                    sender_user = sender_result.scalar_one_or_none()
                    if sender_user:
                        sender_synkro_id = sender_user.id
            except Exception as exc:
                logger.warning("Could not resolve sender email: %s", exc)

        if not recipient_synkro_id and recipient_slack_id:
            try:
                bot_svc = SlackService.from_integration(integration)
                user_info = await bot_svc.get_user_info(recipient_slack_id)
                profile = user_info.get("profile", {})
                recip_email = profile.get("email", "").lower()
                await bot_svc.aclose()
                if recip_email:
                    recip_result = await db.execute(
                        select(User).where(User.email == recip_email, User.is_active == True)
                    )
                    recip_user = recip_result.scalar_one_or_none()
                    if recip_user:
                        recipient_synkro_id = recip_user.id
            except Exception as exc:
                logger.warning("Could not resolve recipient email: %s", exc)

        if sender_synkro_id and recipient_synkro_id and sender_synkro_id != recipient_synkro_id:
            slack_ts_val = event.get("ts", "")
            dup_dm = await db.execute(
                select(DirectMessage).where(DirectMessage.slack_ts == slack_ts_val)
            )
            if not dup_dm.scalar_one_or_none():
                dm = DirectMessage(
                    sender_id=sender_synkro_id,
                    recipient_id=recipient_synkro_id,
                    content=event.get("text", ""),
                    created_at=datetime.utcfromtimestamp(ts_float),
                    slack_ts=slack_ts_val,
                )
                db.add(dm)
                await db.commit()
                logger.info(
                    "DirectMessage created from Slack DM: sender=%s recipient=%s ts=%s",
                    sender_synkro_id, recipient_synkro_id, slack_ts_val,
                )

    # ── 8. Enqueue background intent classification ───────────────────────────
    # Celery task runs outside the request cycle — webhook returns immediately
    try:
        from app.tasks.meeting_tasks import process_message_for_intent
        process_message_for_intent.delay(msg.id)
        logger.debug("Intent classification enqueued for message %s", msg.id)
    except Exception as exc:
        # Celery may not be running in dev — log but don't fail the webhook
        logger.error(
            "Failed to enqueue intent classification for message %s: %s",
            msg.id,
            exc,
        )

    return {"ok": True}
