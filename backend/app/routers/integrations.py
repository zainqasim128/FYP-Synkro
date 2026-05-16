"""
Integration endpoints.

Slack OAuth 2.0 flow
--------------------
1. GET /api/integrations/slack/start         → returns { authorization_url }
2. GET /api/integrations/slack/callback?code= → exchanges code, stores token

Jira API token flow
-------------------
1. POST /api/integrations/jira/connect       → validates credentials + stores token
2. GET  /api/integrations/jira/test          → health-check stored credentials
3. GET  /api/integrations/jira/projects      → list accessible Jira projects

Security notes
--------------
- Access tokens are encrypted at rest using Fernet (see app/utils/security.py).
- OAuth state param (Slack) should be a signed, time-limited CSRF token in prod.
"""

import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field
from sqlalchemy import and_, delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.dependencies import get_current_user
from app.models import Integration, IntegrationPlatform, User
from app.services import jira_service as jira_module
from app.services import slack_service as slack_module
from app.services import google_calendar_service as gcal_module

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/integrations", tags=["Integrations"])


# ── Request / Response schemas ─────────────────────────────────────────────────


class GmailConnectRequest(BaseModel):
    email: str
    app_password: str


class SlackConnectResponse(BaseModel):
    authorization_url: str


class JiraConnectRequest(BaseModel):
    domain: str = Field(..., example="yourcompany.atlassian.net")
    email: str = Field(..., example="you@yourcompany.com")
    api_token: str = Field(..., example="ATATT3x...")
    project_key: Optional[str] = Field(None, example="PROJ")


class JiraConnectResponse(BaseModel):
    message: str
    integration_id: str


class JiraProject(BaseModel):
    id: str
    key: str
    name: str


class JiraTestResponse(BaseModel):
    ok: bool
    account_id: Optional[str] = None
    display_name: Optional[str] = None
    domain: str


# ── List all integrations ──────────────────────────────────────────────────────


@router.get(
    "",
    response_model=List[Dict[str, Any]],
    summary="List all integrations for the current user",
)
async def get_integrations(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> List[Dict[str, Any]]:
    """Return all integration records belonging to the authenticated user."""
    result = await db.execute(
        select(Integration).where(Integration.user_id == current_user.id)
    )
    integrations = result.scalars().all()
    return [
        {
            "id": i.id,
            "platform": i.platform.value,
            "is_active": i.is_active,
            "last_synced_at": (
                i.last_synced_at.isoformat() + "Z" if i.last_synced_at else None
            ),
            "created_at": i.created_at.isoformat() + "Z",
            "metadata": i.platform_metadata or {},
        }
        for i in integrations
    ]


# ── Gmail IMAP ─────────────────────────────────────────────────────────────────


@router.post("/gmail/connect", summary="Connect Gmail via IMAP App Password")
async def connect_gmail(
    request: GmailConnectRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """Connect a Gmail account using an App Password for IMAP access."""
    from app.services.gmail_service import test_connection

    email_addr = request.email.strip()
    app_password = request.app_password.strip()

    if not email_addr or not app_password:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email and app password are required",
        )

    result = test_connection(email_addr, app_password)
    if not result["success"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=result["error"],
        )

    from app.utils.security import encrypt_value

    existing_q = await db.execute(
        select(Integration).where(
            and_(
                Integration.user_id == current_user.id,
                Integration.platform == IntegrationPlatform.GMAIL,
            )
        )
    )
    integration = existing_q.scalar_one_or_none()

    encrypted_password = encrypt_value(app_password)

    if integration:
        integration.access_token = encrypted_password
        integration.is_active = True
        integration.platform_metadata = {"email": email_addr}
    else:
        integration = Integration(
            user_id=current_user.id,
            platform=IntegrationPlatform.GMAIL,
            access_token=encrypted_password,
            is_active=True,
            platform_metadata={"email": email_addr},
        )
        db.add(integration)

    await db.commit()
    logger.info("Gmail connected for user %s (%s)", current_user.id, email_addr)
    return {"message": "Gmail connected successfully!", "email": email_addr}


@router.get("/gmail/emails", summary="Fetch recent emails from connected Gmail")
async def get_gmail_emails(
    limit: int = 20,
    days: int = 7,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    from app.services.gmail_service import fetch_emails

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
        raise HTTPException(
            status_code=404,
            detail="Gmail not connected. Go to Settings to connect.",
        )

    from app.utils.security import decrypt_value

    email_addr = integration.platform_metadata.get("email") or settings.GMAIL_EMAIL
    app_password = decrypt_value(integration.access_token)

    try:
        emails = fetch_emails(
            email_addr=email_addr,
            app_password=app_password,
            limit=min(limit, 50),
            since_days=min(days, 30),
        )
        integration.last_synced_at = datetime.utcnow()
        await db.commit()
        return {"emails": emails, "count": len(emails)}
    except Exception as exc:
        logger.error("Failed to fetch emails for user %s: %s", current_user.id, exc)
        raise HTTPException(status_code=500, detail=f"Failed to fetch emails: {exc}")


# ── Slack OAuth 2.0 ────────────────────────────────────────────────────────────


@router.post(
    "/slack/demo-connect",
    summary="Demo: directly connect Slack using DEMO_SLACK_TOKEN (no OAuth required)",
)
async def slack_demo_connect(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Provision Slack integration directly from DEMO_SLACK_TOKEN env var.

    Replaces any existing Slack integration for the current user.
    """
    import uuid
    from app.utils.security import encrypt_value

    token = settings.DEMO_SLACK_TOKEN
    if not token:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Demo Slack token not configured",
        )

    # Remove existing
    result = await db.execute(
        select(Integration).where(
            Integration.user_id == current_user.id,
            Integration.platform == IntegrationPlatform.SLACK,
        )
    )
    existing = result.scalar_one_or_none()
    if existing:
        await db.delete(existing)

    integration = Integration(
        id=str(uuid.uuid4()),
        user_id=current_user.id,
        platform=IntegrationPlatform.SLACK,
        access_token=encrypt_value(token),
        is_active=True,
        platform_metadata={
            "team_id": settings.DEMO_SLACK_TEAM_ID,
            "team_name": "Synkro Workspace",
            "default_channel": "#general",
        },
    )
    db.add(integration)
    await db.commit()
    logger.info("Demo Slack integration created for user %s", current_user.id)
    return {"ok": True, "integration_id": integration.id}


@router.get(
    "/slack/start",
    response_model=SlackConnectResponse,
    summary="Start Slack OAuth flow — returns authorization URL",
)
async def slack_oauth_start(
    current_user: User = Depends(get_current_user),
) -> SlackConnectResponse:
    """Return the Slack authorization URL.

    The frontend should redirect the user to ``authorization_url``.
    After consent Slack redirects to ``SLACK_REDIRECT_URI`` with ``code``.
    """
    # Pass user ID as state so the callback can identify the user without a session
    url = slack_module.SlackService.authorization_url(state=current_user.id)
    return SlackConnectResponse(authorization_url=url)


@router.get(
    "/oauth/slack/callback",
    summary="Slack OAuth callback (legacy path alias)",
    include_in_schema=False,
)
async def slack_oauth_callback_legacy(
    code: str,
    state: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
) -> RedirectResponse:
    """Alias for /slack/callback — handles legacy redirect_uri."""
    return await slack_oauth_callback(code=code, state=state, db=db)


@router.get(
    "/slack/callback",
    summary="Slack OAuth callback — exchanges code for access token",
    include_in_schema=False,
)
async def slack_oauth_callback(
    code: str,
    state: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
) -> RedirectResponse:
    """Handle the OAuth redirect from Slack.

    Exchanges the ``code`` for a bot access token, encrypts it,
    and upserts the Integration record for this user + workspace.
    The ``state`` parameter carries the Synkro user ID set during oauth start.
    """
    frontend_base = settings.FRONTEND_URL or "http://localhost:3000"
    error_redirect = (
        f"{frontend_base}/dashboard/settings?integration=slack&status=error"
    )
    success_redirect = (
        f"{frontend_base}/dashboard/settings?integration=slack&status=success"
    )

    # Resolve user from state (user ID passed during oauth start)
    if not state:
        logger.error("Slack OAuth callback missing state (user ID)")
        return RedirectResponse(url=f"{error_redirect}&message=missing_state", status_code=302)
    user_result = await db.execute(select(User).where(User.id == state))
    current_user = user_result.scalar_one_or_none()
    if not current_user:
        logger.error("Slack OAuth callback: user not found for state=%s", state)
        return RedirectResponse(url=f"{error_redirect}&message=user_not_found", status_code=302)

    # Use a token-less instance solely for the code exchange
    svc = slack_module.SlackService(token="")
    try:
        data = await svc.exchange_code(code)
    except Exception as exc:
        logger.error("Slack OAuth code exchange failed for user %s: %s", current_user.id, exc)
        return RedirectResponse(
            url=f"{error_redirect}&message={str(exc)[:200]}", status_code=302
        )
    finally:
        await svc.aclose()

    team_id: Optional[str] = data.get("team", {}).get("id")
    bot_user_id: Optional[str] = data.get("bot_user_id")
    access_token: Optional[str] = data.get("access_token")
    scope: Optional[str] = data.get("scope")
    # The Slack user ID and user token of the person who authorized the app
    authed_user: Dict[str, Any] = data.get("authed_user") or {}
    authed_user_id: Optional[str] = authed_user.get("id")
    user_access_token: Optional[str] = authed_user.get("access_token")
    # Capture webhook URL if the incoming-webhook scope was granted
    webhook_info: Dict[str, Any] = data.get("incoming_webhook") or {}

    if not access_token or not team_id:
        logger.error("Slack OAuth response missing access_token or team_id for user %s", current_user.id)
        return RedirectResponse(
            url=f"{error_redirect}&message=missing_required_fields", status_code=302
        )

    from app.utils.security import encrypt_value

    metadata: Dict[str, Any] = {"team_id": team_id, "bot_user_id": bot_user_id}
    if authed_user_id:
        metadata["authed_user_id"] = authed_user_id
    if user_access_token:
        metadata["user_access_token"] = encrypt_value(user_access_token)
        logger.info("Captured user access token for user=%s slack_user=%s", current_user.id, authed_user_id)
    if webhook_info.get("url"):
        metadata["webhook_url"] = webhook_info["url"]
    if webhook_info.get("channel"):
        metadata["default_channel"] = webhook_info["channel"]

    existing_q = await db.execute(
        select(Integration).where(
            and_(
                Integration.user_id == current_user.id,
                Integration.platform == IntegrationPlatform.SLACK,
            )
        )
    )
    all_user_slack = existing_q.scalars().all()
    integration = next(
        (i for i in all_user_slack if (i.platform_metadata or {}).get("team_id") == team_id),
        None,
    )
    encrypted_token = encrypt_value(access_token)

    # If connecting a different workspace, wipe old messages and stale integrations
    from app.models import Message
    old_team_ids = {
        (i.platform_metadata or {}).get("team_id")
        for i in all_user_slack
        if (i.platform_metadata or {}).get("team_id") != team_id
    }
    if old_team_ids:
        logger.info(
            "New Slack workspace %s for user %s — clearing messages from old workspace(s) %s",
            team_id, current_user.id, old_team_ids,
        )
        await db.execute(
            delete(Message).where(
                Message.user_id == current_user.id,
                Message.platform == "slack",
            )
        )
        for old_int in all_user_slack:
            if (old_int.platform_metadata or {}).get("team_id") != team_id:
                await db.delete(old_int)

    if integration:
        integration.access_token = encrypted_token
        integration.scope = scope
        integration.is_active = True
        integration.platform_metadata = metadata
    else:
        integration = Integration(
            user_id=current_user.id,
            platform=IntegrationPlatform.SLACK,
            access_token=encrypted_token,
            scope=scope,
            is_active=True,
            platform_metadata=metadata,
        )
        db.add(integration)

    await db.commit()
    logger.info("Slack connected: user=%s team=%s scopes=%s", current_user.id, team_id, scope)
    return RedirectResponse(url=success_redirect, status_code=302)


# ── Jira API token ─────────────────────────────────────────────────────────────


@router.post(
    "/jira/connect",
    response_model=JiraConnectResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Connect Jira Cloud workspace via email + API token",
)
async def connect_jira(
    request: JiraConnectRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JiraConnectResponse:
    """Store Jira Cloud connection details.

    Validates the credentials by calling ``GET /myself`` before storing.
    The API token is encrypted at rest with Fernet.

    Generate an API token at: https://id.atlassian.com/manage-profile/security
    """
    if not request.domain or not request.email or not request.api_token:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="domain, email and api_token are all required",
        )

    # Validate credentials before persisting — fails fast on typos/revoked tokens
    jira = jira_module.JiraService(request.domain, request.email, request.api_token)
    try:
        account = await jira.verify_credentials()
    except ValueError as exc:
        logger.warning(
            "Jira credential validation failed for user %s domain %s: %s",
            current_user.id, request.domain, exc,
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Jira credentials are invalid: {exc}",
        )
    finally:
        await jira.aclose()

    from app.utils.security import encrypt_value

    existing_q = await db.execute(
        select(Integration).where(
            and_(
                Integration.user_id == current_user.id,
                Integration.platform == IntegrationPlatform.JIRA,
            )
        )
    )
    all_jira = existing_q.scalars().all()
    integration = next(
        (i for i in all_jira if (i.platform_metadata or {}).get("domain") == request.domain),
        None,
    )

    metadata: Dict[str, Any] = {
        "domain": request.domain,
        "email": request.email,
        "account_id": account.get("accountId"),
        "display_name": account.get("displayName"),
    }
    if request.project_key:
        metadata["project_key"] = request.project_key

    encrypted_token = encrypt_value(request.api_token)

    if integration:
        integration.access_token = encrypted_token
        integration.platform_metadata = metadata
        integration.is_active = True
    else:
        integration = Integration(
            user_id=current_user.id,
            platform=IntegrationPlatform.JIRA,
            access_token=encrypted_token,
            is_active=True,
            platform_metadata=metadata,
        )
        db.add(integration)

    await db.commit()
    await db.refresh(integration)
    logger.info(
        "Jira connected: user=%s domain=%s account=%s",
        current_user.id, request.domain, account.get("accountId"),
    )
    return JiraConnectResponse(
        message="Jira connected successfully!",
        integration_id=integration.id,
    )


@router.get(
    "/jira/test",
    response_model=JiraTestResponse,
    summary="Verify stored Jira credentials are still valid",
)
async def test_jira_connection(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JiraTestResponse:
    """Call Jira ``GET /myself`` to confirm stored credentials work."""
    result = await db.execute(
        select(Integration).where(
            and_(
                Integration.user_id == current_user.id,
                Integration.platform == IntegrationPlatform.JIRA,
                Integration.is_active == True,
            )
        )
    )
    integration = result.scalar_one_or_none()
    if not integration:
        raise HTTPException(status_code=404, detail="Jira integration not found")

    jira = jira_module.JiraService.from_integration(integration)
    try:
        account = await jira.verify_credentials()
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Jira credentials invalid: {exc}",
        )
    finally:
        await jira.aclose()

    return JiraTestResponse(
        ok=True,
        account_id=account.get("accountId"),
        display_name=account.get("displayName"),
        domain=integration.platform_metadata.get("domain", ""),
    )


@router.get(
    "/jira/projects",
    response_model=List[JiraProject],
    summary="List Jira projects accessible with stored credentials",
)
async def list_jira_projects(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> List[JiraProject]:
    """Return all Jira projects the authenticated user can see.

    Useful for letting users pick their default project key during onboarding.
    """
    result = await db.execute(
        select(Integration).where(
            and_(
                Integration.user_id == current_user.id,
                Integration.platform == IntegrationPlatform.JIRA,
                Integration.is_active == True,
            )
        )
    )
    integration = result.scalar_one_or_none()
    if not integration:
        raise HTTPException(status_code=404, detail="Jira integration not found")

    jira = jira_module.JiraService.from_integration(integration)
    try:
        projects = await jira.list_projects()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    finally:
        await jira.aclose()

    return [
        JiraProject(id=p["id"], key=p["key"], name=p["name"])
        for p in projects
    ]


# ── Slack message → task background processor ─────────────────────────────────


async def _process_slack_message_for_task(message_id: str) -> None:
    """Classify a Slack message and auto-create a task if it is a task request."""
    from app.database import AsyncSessionLocal
    from app.models import Message
    from app.models.task import Task, TaskStatus, TaskPriority, TaskSourceType
    from app.models.user import User as UserModel
    from app.services.ai_service import classify_intent, extract_task_entities

    async with AsyncSessionLocal() as db:
        try:
            msg_result = await db.execute(select(Message).where(Message.id == message_id))
            message = msg_result.scalar_one_or_none()
            if not message or message.processed:
                return

            intent_data = await classify_intent(message.content)
            message.intent = intent_data.get("intent", "information")

            if intent_data.get("intent") != "task_request":
                message.processed = True
                await db.commit()
                return

            entities = await extract_task_entities(message.content)
            message.entities = entities

            # Resolve owning user → team
            user_result = await db.execute(select(UserModel).where(UserModel.id == message.user_id))
            msg_user = user_result.scalar_one_or_none()
            if not msg_user or not msg_user.team_id:
                message.processed = True
                await db.commit()
                return

            # Resolve assignee name/@mention → team member
            assignee_id = None
            raw_assignee = (entities.get("assignee") or "").lstrip("@").lower().strip()
            if raw_assignee:
                members_result = await db.execute(
                    select(UserModel).where(UserModel.team_id == msg_user.team_id)
                )
                for member in members_result.scalars().all():
                    name_lower = (member.full_name or "").lower()
                    email_lower = (member.email or "").lower()
                    if (
                        raw_assignee == name_lower
                        or name_lower.startswith(raw_assignee)
                        or email_lower.startswith(raw_assignee)
                    ):
                        assignee_id = member.id
                        break

            # Parse priority safely
            priority_map = {p.value: p for p in TaskPriority}
            priority = priority_map.get(
                (entities.get("priority") or "medium").lower(), TaskPriority.MEDIUM
            )

            # Parse deadline
            due_date = None
            if entities.get("deadline"):
                try:
                    from dateutil import parser as date_parser
                    due_date = date_parser.parse(entities["deadline"])
                except Exception:
                    pass

            title = entities.get("title") or message.content[:100]
            description = entities.get("description") or message.content

            task = Task(
                title=title,
                description=description,
                status=TaskStatus.TODO,
                priority=priority,
                due_date=due_date,
                source_type=TaskSourceType.MESSAGE,
                source_id=message.id,
                team_id=msg_user.team_id,
                created_by_id=message.user_id,
                assignee_id=assignee_id,
            )
            db.add(task)
            message.processed = True
            await db.commit()
            logger.info(
                "Auto-created task '%s' from Slack message %s (assignee_id=%s)",
                title, message_id, assignee_id,
            )
        except Exception as exc:
            logger.error("Failed to process Slack message %s for task: %s", message_id, exc)
            await db.rollback()


# ── Generic sync / disconnect ──────────────────────────────────────────────────


@router.post(
    "/{integration_id}/sync",
    summary="Trigger a manual sync for an integration",
)
async def sync_integration(
    integration_id: str,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    from app.models import Message
    from app.utils.security import decrypt_value

    result = await db.execute(
        select(Integration).where(
            and_(
                Integration.id == integration_id,
                Integration.user_id == current_user.id,
            )
        )
    )
    integration = result.scalar_one_or_none()

    if not integration:
        raise HTTPException(status_code=404, detail="Integration not found")
    if not integration.is_active:
        raise HTTPException(status_code=400, detail="Integration is not active")

    synced_count = 0

    if integration.platform == IntegrationPlatform.SLACK:
        try:
            from datetime import timezone
            from datetime import datetime as dt

            token = decrypt_value(integration.access_token)
            svc = slack_module.SlackService(token)

            # Fetch public channels (groups:read scope required for private — skip if not granted)
            resp = await svc._request("conversations.list", method="GET", params={
                "types": "public_channel",
                "limit": 200,
                "exclude_archived": "true",
            })
            channels = resp.get("channels", [])

            # Cache user ID → display name to avoid redundant API calls
            user_name_cache: Dict[str, str] = {}

            import re
            _slack_uid_re = re.compile(r'^[UW][A-Z0-9]{6,}$')

            async def resolve_name(uid: str) -> str:
                if not uid:
                    return "unknown"
                if uid not in user_name_cache:
                    try:
                        user_info = await svc.get_user_info(uid)
                        profile = user_info.get("profile", {})
                        user_name_cache[uid] = (
                            profile.get("display_name")
                            or profile.get("real_name")
                            or uid
                        )
                    except Exception:
                        user_name_cache[uid] = uid
                return user_name_cache[uid]

            # Fix existing messages that have raw Slack user IDs as sender_name
            from sqlalchemy import update as sa_update
            stale_q = await db.execute(
                select(Message).where(
                    Message.platform == "slack",
                    Message.user_id == current_user.id,
                )
            )
            stale_msgs = stale_q.scalars().all()
            for m in stale_msgs:
                if m.sender_name and _slack_uid_re.match(m.sender_name):
                    resolved = await resolve_name(m.sender_name)
                    if resolved != m.sender_name:
                        m.sender_name = resolved
            await db.commit()

            for ch in channels:
                ch_id = ch["id"]
                is_private = ch.get("is_private", False)
                try:
                    # Auto-join public channels so the bot can read history
                    if not ch.get("is_member") and not is_private:
                        try:
                            await svc._request("conversations.join", method="POST", data={"channel": ch_id})
                        except Exception:
                            pass

                    messages = await svc.get_channel_messages(ch_id, limit=50)
                    for msg in messages:
                        if not msg.get("text") or msg.get("subtype"):
                            continue
                        external_id = msg.get("ts", "")
                        exists = await db.execute(
                            select(Message).where(Message.external_id == external_id)
                        )
                        if exists.scalar_one_or_none():
                            continue

                        sender_name = await resolve_name(msg.get("user", ""))

                        ts = float(msg.get("ts", 0))
                        msg_time = dt.fromtimestamp(ts, tz=timezone.utc).replace(tzinfo=None) if ts else dt.utcnow()
                        new_msg = Message(
                            user_id=current_user.id,
                            platform="slack",
                            external_id=external_id,
                            sender_name=sender_name,
                            content=msg.get("text", ""),
                            channel_id=ch_id,
                            channel_type="channel",
                            timestamp=msg_time,
                        )
                        db.add(new_msg)
                        await db.flush()  # get new_msg.id before background task
                        background_tasks.add_task(_process_slack_message_for_task, new_msg.id)
                        synced_count += 1
                except Exception:
                    continue

            await db.commit()
        except Exception as e:
            logger.warning("Slack sync failed: %s", e)

    integration.last_synced_at = datetime.utcnow()
    await db.commit()
    return {"message": f"Sync complete — {synced_count} new messages", "integration_id": integration_id, "synced": synced_count}


@router.delete(
    "/{integration_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Disconnect (delete) an integration",
)
async def disconnect_integration(
    integration_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    result = await db.execute(
        select(Integration).where(
            and_(
                Integration.id == integration_id,
                Integration.user_id == current_user.id,
            )
        )
    )
    integration = result.scalar_one_or_none()

    if not integration:
        raise HTTPException(status_code=404, detail="Integration not found")

    await db.delete(integration)
    await db.commit()
    logger.info(
        "Integration %s (%s) disconnected for user %s",
        integration_id,
        integration.platform.value,
        current_user.id,
    )


# ── Google Calendar OAuth 2.0 ─────────────────────────────────────────────────


class GCalConnectResponse(BaseModel):
    authorization_url: str


class GCalTestResponse(BaseModel):
    ok: bool
    calendar_id: Optional[str] = None
    summary: Optional[str] = None


@router.get(
    "/google-calendar/configured",
    summary="Check whether Google Calendar credentials are present in server config",
)
async def gcal_is_configured() -> dict:
    """Returns {configured: bool} — no auth required, used to show/hide the Connect button."""
    return {"configured": bool(settings.GOOGLE_CLIENT_ID and settings.GOOGLE_CLIENT_SECRET)}


@router.get(
    "/google-calendar/start",
    response_model=GCalConnectResponse,
    summary="Start Google Calendar OAuth flow — returns authorization URL",
)
async def gcal_oauth_start(
    current_user: User = Depends(get_current_user),
) -> GCalConnectResponse:
    """Return the Google OAuth consent URL. Frontend should redirect the user there."""
    if not settings.GOOGLE_CLIENT_ID or not settings.GOOGLE_CLIENT_SECRET:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Google Calendar OAuth credentials are not configured on this server. Set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET in the backend .env file.",
        )
    url = gcal_module.GoogleCalendarService.get_authorization_url(state=current_user.id)
    return GCalConnectResponse(authorization_url=url)


@router.get(
    "/google-calendar/callback",
    summary="Google Calendar OAuth callback — exchanges code for tokens",
    include_in_schema=False,
)
async def gcal_oauth_callback(
    code: str,
    state: str,
    db: AsyncSession = Depends(get_db),
) -> RedirectResponse:
    """Handle the OAuth redirect from Google.

    Exchanges the code for access + refresh tokens, encrypts them,
    and upserts the Integration record. User is identified via the state param.
    """
    frontend_base = settings.FRONTEND_URL or "http://localhost:3000"
    error_redirect = (
        f"{frontend_base}/dashboard/settings?integration=google-calendar&status=error"
    )
    success_redirect = (
        f"{frontend_base}/dashboard/settings?integration=google-calendar&status=success"
    )

    user_result = await db.execute(select(User).where(User.id == state))
    current_user = user_result.scalar_one_or_none()
    if not current_user:
        logger.error("GCal OAuth callback: user not found for state=%s", state)
        return RedirectResponse(
            url=f"{error_redirect}&message=user_not_found", status_code=302
        )

    try:
        data = await gcal_module.GoogleCalendarService.exchange_code(code)
    except Exception as exc:
        logger.error("GCal code exchange failed for user %s: %s", current_user.id, exc)
        return RedirectResponse(
            url=f"{error_redirect}&message={str(exc)[:200]}", status_code=302
        )

    access_token: str = data.get("access_token", "")
    refresh_token: str = data.get("refresh_token", "")
    expires_in: int = data.get("expires_in", 3600)
    scope: str = data.get("scope", "")

    if not access_token:
        return RedirectResponse(
            url=f"{error_redirect}&message=missing_access_token", status_code=302
        )

    from app.utils.security import encrypt_value

    expires_at = datetime.utcnow() + timedelta(seconds=expires_in)
    encrypted_token = encrypt_value(access_token)
    encrypted_refresh = encrypt_value(refresh_token) if refresh_token else None

    existing_q = await db.execute(
        select(Integration).where(
            and_(
                Integration.user_id == current_user.id,
                Integration.platform == IntegrationPlatform.GOOGLE_CALENDAR,
            )
        )
    )
    integration = existing_q.scalar_one_or_none()

    if integration:
        integration.access_token = encrypted_token
        integration.refresh_token = encrypted_refresh
        integration.expires_at = expires_at
        integration.scope = scope
        integration.is_active = True
        integration.platform_metadata = {"email": current_user.email}
    else:
        integration = Integration(
            user_id=current_user.id,
            platform=IntegrationPlatform.GOOGLE_CALENDAR,
            access_token=encrypted_token,
            refresh_token=encrypted_refresh,
            expires_at=expires_at,
            scope=scope,
            is_active=True,
            platform_metadata={"email": current_user.email},
        )
        db.add(integration)

    await db.commit()
    logger.info("Google Calendar connected: user=%s", current_user.id)
    return RedirectResponse(url=success_redirect, status_code=302)


@router.get(
    "/google-calendar/test",
    response_model=GCalTestResponse,
    summary="Verify stored Google Calendar token is still valid",
)
async def test_gcal_connection(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> GCalTestResponse:
    """Call Google Calendar API to confirm stored token works."""
    result = await db.execute(
        select(Integration).where(
            and_(
                Integration.user_id == current_user.id,
                Integration.platform == IntegrationPlatform.GOOGLE_CALENDAR,
                Integration.is_active == True,
            )
        )
    )
    integration = result.scalar_one_or_none()
    if not integration:
        raise HTTPException(status_code=404, detail="Google Calendar integration not found")

    svc = gcal_module.GoogleCalendarService.from_integration(integration)
    try:
        cal_info = await svc.verify_connection()
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Google Calendar token invalid: {exc}",
        )
    finally:
        await svc.aclose()

    return GCalTestResponse(
        ok=True,
        calendar_id=cal_info.get("id"),
        summary=cal_info.get("summary"),
    )


@router.get(
    "/google-calendar/diagnose",
    summary="Diagnose Google Calendar 403 / scope issues",
)
async def diagnose_gcal(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Return raw Google API error details to diagnose 403/scope problems."""
    import httpx as _httpx

    result = await db.execute(
        select(Integration).where(
            and_(
                Integration.user_id == current_user.id,
                Integration.platform == IntegrationPlatform.GOOGLE_CALENDAR,
                Integration.is_active == True,
            )
        )
    )
    integration = result.scalar_one_or_none()
    if not integration:
        return {"connected": False, "detail": "No active Google Calendar integration found."}

    svc = gcal_module.GoogleCalendarService.from_integration(integration)
    try:
        info = await svc.verify_connection()
        return {
            "connected": True,
            "calendar_id": info.get("id"),
            "summary": info.get("summary"),
            "stored_scope": integration.scope,
        }
    except _httpx.HTTPStatusError as exc:
        try:
            body = exc.response.json()
        except Exception:
            body = {"raw": exc.response.text[:500]}
        return {
            "connected": False,
            "http_status": exc.response.status_code,
            "google_error": body,
            "stored_scope": integration.scope,
            "hint": (
                "accessNotConfigured → enable Google Calendar API at console.cloud.google.com"
                if body.get("error", {}).get("errors", [{}])[0].get("reason") == "accessNotConfigured"
                else "Add your Google account as a Test User in the OAuth consent screen, then reconnect."
            ),
        }
    except Exception as exc:
        return {"connected": False, "detail": str(exc)}
    finally:
        await svc.aclose()

