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

import io
import logging
import secrets
import tempfile
import os
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.dependencies import get_current_user
from app.models import Integration, IntegrationPlatform, User
from app.models.meeting import Meeting, MeetingStatus
from app.services import jira_service as jira_module
from app.services import slack_service as slack_module
from app.services import zoom_service as zoom_module
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

    existing_q = await db.execute(
        select(Integration).where(
            and_(
                Integration.user_id == current_user.id,
                Integration.platform == IntegrationPlatform.GMAIL,
            )
        )
    )
    integration = existing_q.scalar_one_or_none()

    if integration:
        integration.access_token = app_password
        integration.is_active = True
        integration.platform_metadata = {"email": email_addr}
    else:
        integration = Integration(
            user_id=current_user.id,
            platform=IntegrationPlatform.GMAIL,
            access_token=app_password,
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

    email_addr = integration.platform_metadata.get("email") or settings.GMAIL_EMAIL
    app_password = integration.access_token

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


# ── Generic sync / disconnect ──────────────────────────────────────────────────


@router.post(
    "/{integration_id}/sync",
    summary="Trigger a manual sync for an integration",
)
async def sync_integration(
    integration_id: str,
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

            # Fetch all public channels
            resp = await svc._request("conversations.list", method="GET", params={
                "types": "public_channel,private_channel",
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
                try:
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
                        db.add(Message(
                            user_id=current_user.id,
                            platform="slack",
                            external_id=external_id,
                            sender_name=sender_name,
                            content=msg.get("text", ""),
                            channel_id=ch_id,
                            channel_type="channel",
                            timestamp=msg_time,
                        ))
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
# ── Zoom OAuth 2.0 ────────────────────────────────────────────────────────────


class ZoomConnectResponse(BaseModel):
    authorization_url: str


class ZoomTestResponse(BaseModel):
    ok: bool
    zoom_user_id: Optional[str] = None
    display_name: Optional[str] = None
    email: Optional[str] = None


@router.get(
    "/zoom/start",
    response_model=ZoomConnectResponse,
    summary="Start Zoom OAuth flow — returns authorization URL",
)
async def zoom_oauth_start(
    current_user: User = Depends(get_current_user),
) -> ZoomConnectResponse:
    """Return the Zoom authorization URL. The frontend should redirect the user there."""
    state = secrets.token_urlsafe(16)
    url = zoom_module.ZoomService.get_auth_url(state=state)
    return ZoomConnectResponse(authorization_url=url)


@router.get(
    "/zoom/callback",
    summary="Zoom OAuth callback — exchanges code for access token",
    include_in_schema=False,
)
async def zoom_oauth_callback(
    code: str,
    state: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> RedirectResponse:
    """Handle the OAuth redirect from Zoom.

    Exchanges the code for tokens, encrypts them, and upserts the Integration row.
    """
    frontend_base = settings.FRONTEND_URL or "http://localhost:3000"
    error_redirect = f"{frontend_base}/dashboard/settings?integration=zoom&status=error"
    success_redirect = f"{frontend_base}/dashboard/settings?integration=zoom&status=success"

    try:
        data = await zoom_module.ZoomService.exchange_code(code)
    except Exception as exc:
        logger.error("Zoom OAuth code exchange failed for user %s: %s", current_user.id, exc)
        return RedirectResponse(
            url=f"{error_redirect}&message={str(exc)[:200]}", status_code=302
        )

    access_token: str = data.get("access_token", "")
    refresh_token: str = data.get("refresh_token", "")
    expires_in: int = data.get("expires_in", 3600)
    scope: str = data.get("scope", "")

    if not access_token:
        return RedirectResponse(url=f"{error_redirect}&message=missing_access_token", status_code=302)

    # Fetch Zoom user info to store in metadata
    svc = zoom_module.ZoomService(access_token=access_token)
    try:
        zoom_user = await svc.get_user()
    except Exception as exc:
        logger.warning("Could not fetch Zoom user info for user %s: %s", current_user.id, exc)
        zoom_user = {}
    finally:
        await svc.aclose()

    from app.utils.security import encrypt_value

    zoom_user_id: str = zoom_user.get("id", "")
    metadata: Dict[str, Any] = {
        "zoom_user_id": zoom_user_id,
        "account_id": zoom_user.get("account_id", ""),
        "display_name": zoom_user.get("display_name", ""),
        "email": zoom_user.get("email", ""),
    }

    expires_at = datetime.utcnow() + timedelta(seconds=expires_in)
    encrypted_token = encrypt_value(access_token)
    encrypted_refresh = encrypt_value(refresh_token) if refresh_token else None

    existing_q = await db.execute(
        select(Integration).where(
            and_(
                Integration.user_id == current_user.id,
                Integration.platform == IntegrationPlatform.ZOOM,
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
        integration.platform_metadata = metadata
    else:
        integration = Integration(
            user_id=current_user.id,
            platform=IntegrationPlatform.ZOOM,
            access_token=encrypted_token,
            refresh_token=encrypted_refresh,
            expires_at=expires_at,
            scope=scope,
            is_active=True,
            platform_metadata=metadata,
        )
        db.add(integration)

    await db.commit()
    logger.info("Zoom connected: user=%s zoom_user=%s", current_user.id, zoom_user_id)
    return RedirectResponse(url=success_redirect, status_code=302)


@router.get(
    "/zoom/test",
    response_model=ZoomTestResponse,
    summary="Verify stored Zoom credentials are still valid",
)
async def test_zoom_connection(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ZoomTestResponse:
    """Call Zoom GET /users/me to confirm stored token works."""
    result = await db.execute(
        select(Integration).where(
            and_(
                Integration.user_id == current_user.id,
                Integration.platform == IntegrationPlatform.ZOOM,
                Integration.is_active == True,
            )
        )
    )
    integration = result.scalar_one_or_none()
    if not integration:
        raise HTTPException(status_code=404, detail="Zoom integration not found")

    # Refresh token if needed
    if zoom_module.token_needs_refresh(integration.expires_at):
        await _refresh_zoom_token(integration, db)

    svc = zoom_module.ZoomService.from_integration(integration)
    try:
        user_info = await svc.get_user()
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Zoom token invalid: {exc}")
    finally:
        await svc.aclose()

    return ZoomTestResponse(
        ok=True,
        zoom_user_id=user_info.get("id"),
        display_name=user_info.get("display_name"),
        email=user_info.get("email"),
    )


@router.post(
    "/zoom/webhook",
    summary="Receive Zoom webhook events",
    include_in_schema=False,
)
async def zoom_webhook(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """Handle Zoom webhook events.

    Events handled:
    - endpoint.url_validation  : Zoom URL validation challenge (must respond within 3s)
    - meeting.ended            : Create Meeting(AWAITING_UPLOAD) + Slack DM notification
    - recording.completed      : Download cloud recording → process pipeline (Track A)

    Verified via HMAC-SHA256 using ZOOM_WEBHOOK_SECRET_TOKEN.
    """
    body = await request.body()

    # Verify signature
    signature = request.headers.get("x-zm-signature", "")
    timestamp = request.headers.get("x-zm-request-timestamp", "")

    # Allow endpoint validation challenge without full secret check
    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    # Zoom URL validation challenge (no signature on first validation call)
    if payload.get("event") == "endpoint.url_validation":
        plain_token = payload.get("payload", {}).get("plainToken", "")
        import hashlib as _hl
        enc_token = _hl.sha256(
            (settings.ZOOM_WEBHOOK_SECRET_TOKEN + plain_token).encode()
        ).hexdigest()
        return {"plainToken": plain_token, "encryptedToken": enc_token}

    # Verify signature for all other events
    if settings.ZOOM_WEBHOOK_SECRET_TOKEN:
        if not zoom_module.ZoomService.verify_webhook_signature(body, signature, timestamp):
            raise HTTPException(status_code=403, detail="Invalid webhook signature")

    event = payload.get("event", "")
    obj = payload.get("payload", {}).get("object", {})

    logger.info("Zoom webhook event received: %s", event)

    if event == "meeting.ended":
        await _handle_meeting_ended(obj, db)
    elif event == "recording.completed":
        await _handle_recording_completed(obj, db)

    return {"status": "ok"}


# ── Zoom webhook sub-handlers ─────────────────────────────────────────────────


async def _refresh_zoom_token(integration: Integration, db: AsyncSession) -> None:
    """Refresh the Zoom access token and persist the updated values."""
    from app.utils.security import decrypt_value, encrypt_value

    if not integration.refresh_token:
        logger.warning("Zoom integration %s has no refresh token", integration.id)
        return

    try:
        raw_refresh = decrypt_value(integration.refresh_token)
    except Exception:
        raw_refresh = integration.refresh_token

    try:
        data = await zoom_module.ZoomService.refresh_access_token(raw_refresh)
    except Exception as exc:
        logger.error("Zoom token refresh failed for integration %s: %s", integration.id, exc)
        return

    integration.access_token = encrypt_value(data.get("access_token", ""))
    if data.get("refresh_token"):
        integration.refresh_token = encrypt_value(data["refresh_token"])
    expires_in = data.get("expires_in", 3600)
    integration.expires_at = datetime.utcnow() + timedelta(seconds=expires_in)
    await db.commit()


async def _handle_meeting_ended(obj: Dict[str, Any], db: AsyncSession) -> None:
    """Create an AWAITING_UPLOAD meeting row and send a Slack DM notification."""
    import uuid

    zoom_meeting_id = str(obj.get("id", ""))
    topic = obj.get("topic", "Zoom Meeting")
    start_time_str = obj.get("start_time")
    duration_minutes = obj.get("duration")
    host_id = obj.get("host_id", "")

    if not zoom_meeting_id:
        logger.warning("meeting.ended event missing meeting id")
        return

    # Resolve team via the Zoom integration whose zoom_user_id matches the host
    result = await db.execute(
        select(Integration).where(
            and_(
                Integration.platform == IntegrationPlatform.ZOOM,
                Integration.is_active == True,
            )
        )
    )
    integrations = result.scalars().all()
    zoom_integration = next(
        (i for i in integrations if i.platform_metadata.get("zoom_user_id") == host_id),
        integrations[0] if integrations else None,
    )

    if not zoom_integration:
        logger.warning("No Zoom integration found for host_id=%s — skipping meeting.ended", host_id)
        return

    # Fetch the user to get their team_id
    user_result = await db.execute(
        select(User).where(User.id == zoom_integration.user_id)
    )
    host_user = user_result.scalar_one_or_none()
    if not host_user or not host_user.team_id:
        logger.warning("Host user or team not found for Zoom integration %s", zoom_integration.id)
        return

    # Parse scheduled_at
    scheduled_at = None
    if start_time_str:
        try:
            scheduled_at = datetime.fromisoformat(start_time_str.replace("Z", "+00:00"))
        except ValueError:
            pass

    meeting = Meeting(
        id=str(uuid.uuid4()),
        title=topic,
        scheduled_at=scheduled_at,
        duration_minutes=duration_minutes,
        status=MeetingStatus.AWAITING_UPLOAD,
        team_id=host_user.team_id,
        created_by_id=host_user.id,
        zoom_meeting_id=zoom_meeting_id,
    )
    db.add(meeting)
    await db.commit()
    await db.refresh(meeting)
    logger.info("Created AWAITING_UPLOAD meeting %s for Zoom meeting %s", meeting.id, zoom_meeting_id)

    # Send Slack DM notification if Slack is connected
    slack_result = await db.execute(
        select(Integration).where(
            and_(
                Integration.user_id == host_user.id,
                Integration.platform == IntegrationPlatform.SLACK,
                Integration.is_active == True,
            )
        )
    )
    slack_integration = slack_result.scalar_one_or_none()
    if slack_integration:
        slack_svc = slack_module.SlackService.from_integration(slack_integration)
        try:
            authed_user_id = slack_integration.platform_metadata.get("authed_user_id")
            if authed_user_id:
                frontend_url = settings.FRONTEND_URL or "http://localhost:3000"
                upload_url = f"{frontend_url}/dashboard/meetings/{meeting.id}"
                dm_channel = await slack_svc.open_dm_channel(authed_user_id)
                await slack_svc.post_message(
                    channel=dm_channel,
                    text=(
                        f"Your Zoom meeting *{topic}* just ended. "
                        f"Upload the recording to get your transcript and action items: {upload_url}"
                    ),
                )
                logger.info("Sent Slack DM to user %s for meeting %s", authed_user_id, meeting.id)
        except Exception as exc:
            logger.warning("Could not send Slack DM for meeting %s: %s", meeting.id, exc)
        finally:
            await slack_svc.aclose()


async def _handle_recording_completed(obj: Dict[str, Any], db: AsyncSession) -> None:
    """Download the cloud recording and enqueue the processing pipeline (Track A)."""
    import uuid

    zoom_meeting_id = str(obj.get("id", ""))
    topic = obj.get("topic", "Zoom Meeting")
    start_time_str = obj.get("start_time")
    duration_minutes = obj.get("duration")
    host_id = obj.get("host_id", "")
    recording_files = obj.get("recording_files", [])

    if not zoom_meeting_id:
        logger.warning("recording.completed event missing meeting id")
        return

    # Find the best recording file (prefer audio-only M4A, fall back to MP4)
    best_file = None
    for rf in recording_files:
        if rf.get("file_type") in ("M4A", "MP4") and rf.get("status") == "completed":
            if best_file is None or rf.get("file_type") == "M4A":
                best_file = rf

    if not best_file:
        logger.warning("No usable recording file for meeting %s", zoom_meeting_id)
        return

    recording_id = best_file.get("id", "")
    download_url = best_file.get("download_url", "")

    if not download_url:
        logger.warning("Recording file has no download_url for meeting %s", zoom_meeting_id)
        return

    # Dedup guard — check if already processed
    existing_q = await db.execute(
        select(Meeting).where(Meeting.zoom_recording_id == recording_id)
    )
    if existing_q.scalar_one_or_none():
        logger.info("Recording %s already processed — skipping", recording_id)
        return

    # Resolve Zoom integration for this host
    result = await db.execute(
        select(Integration).where(
            and_(
                Integration.platform == IntegrationPlatform.ZOOM,
                Integration.is_active == True,
            )
        )
    )
    integrations = result.scalars().all()
    zoom_integration = next(
        (i for i in integrations if i.platform_metadata.get("zoom_user_id") == host_id),
        integrations[0] if integrations else None,
    )

    if not zoom_integration:
        logger.warning("No Zoom integration for host_id=%s — skipping recording.completed", host_id)
        return

    user_result = await db.execute(
        select(User).where(User.id == zoom_integration.user_id)
    )
    host_user = user_result.scalar_one_or_none()
    if not host_user or not host_user.team_id:
        logger.warning("Host user or team not found for recording %s", recording_id)
        return

    # Refresh token if needed
    if zoom_module.token_needs_refresh(zoom_integration.expires_at):
        await _refresh_zoom_token(zoom_integration, db)

    svc = zoom_module.ZoomService.from_integration(zoom_integration)
    try:
        file_bytes = await svc.download_recording_file(download_url)
    except Exception as exc:
        logger.error("Failed to download recording for meeting %s: %s", zoom_meeting_id, exc)
        return
    finally:
        await svc.aclose()

    # Upload to storage
    from app.utils.storage import get_storage
    storage = get_storage()
    file_ext = "m4a" if best_file.get("file_type") == "M4A" else "mp4"
    filename = f"zoom_{zoom_meeting_id}.{file_ext}"
    content_type = "audio/mp4" if file_ext == "m4a" else "video/mp4"
    recording_url = await storage.upload_file(
        file_obj=io.BytesIO(file_bytes),
        filename=filename,
        folder="meetings",
        content_type=content_type,
    )

    # Check if an AWAITING_UPLOAD meeting already exists for this zoom_meeting_id
    existing_meeting_q = await db.execute(
        select(Meeting).where(Meeting.zoom_meeting_id == zoom_meeting_id)
    )
    meeting = existing_meeting_q.scalar_one_or_none()

    scheduled_at = None
    if start_time_str:
        try:
            scheduled_at = datetime.fromisoformat(start_time_str.replace("Z", "+00:00"))
        except ValueError:
            pass

    if meeting:
        meeting.recording_url = recording_url
        meeting.zoom_recording_id = recording_id
        meeting.status = MeetingStatus.PROCESSING
    else:
        meeting = Meeting(
            id=str(uuid.uuid4()),
            title=topic,
            scheduled_at=scheduled_at,
            duration_minutes=duration_minutes,
            recording_url=recording_url,
            status=MeetingStatus.PROCESSING,
            team_id=host_user.team_id,
            created_by_id=host_user.id,
            zoom_meeting_id=zoom_meeting_id,
            zoom_recording_id=recording_id,
        )
        db.add(meeting)

    await db.commit()
    await db.refresh(meeting)
    logger.info(
        "Recording downloaded and meeting %s queued for processing (zoom_meeting=%s)",
        meeting.id,
        zoom_meeting_id,
    )

    # Enqueue background processing
    try:
        from app.tasks.meeting_tasks import process_meeting_background
        process_meeting_background.delay(meeting.id)
        logger.info("Enqueued process_meeting_background for meeting %s", meeting.id)
    except Exception as exc:
        logger.error("Failed to enqueue processing for meeting %s: %s", meeting.id, exc)

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

