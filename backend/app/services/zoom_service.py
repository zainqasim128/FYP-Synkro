"""
Zoom OAuth 2.0 service wrapper.

Covers:
- Authorization URL generation (OAuth 2.0 code grant)
- Authorization code exchange
- Access token refresh
- User / recording API calls
- Cloud recording file download
- Webhook HMAC-SHA256 signature verification
"""

import hashlib
import hmac
import logging
import time
from datetime import datetime, timedelta
from typing import Any, Dict, Optional

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

_ZOOM_API_BASE = "https://api.zoom.us/v2"
_ZOOM_OAUTH_BASE = "https://zoom.us/oauth"

_OAUTH_SCOPES = [
    "recording:read:admin",
    "meeting:read:admin",
    "user:read:admin",
]


class ZoomService:
    """Async wrapper around the Zoom REST API.

    Typical usage:
        svc = ZoomService(access_token="...")
        user = await svc.get_user()
    """

    def __init__(self, access_token: str = "") -> None:
        self.access_token = access_token
        self._client = httpx.AsyncClient(
            base_url=_ZOOM_API_BASE,
            timeout=httpx.Timeout(30.0, connect=5.0),
            headers={"Authorization": f"Bearer {access_token}"},
        )

    # ── Construction helpers ─────────────────────────────────────────────────

    @classmethod
    def from_integration(cls, integration: Any) -> "ZoomService":
        """Build a ZoomService from a DB Integration row (decrypts token)."""
        from app.utils.security import decrypt_value

        tok = integration.access_token
        try:
            tok = decrypt_value(tok)
        except Exception:
            logger.warning(
                "Could not decrypt Zoom token for integration %s — using raw value",
                integration.id,
            )
        return cls(access_token=tok)

    # ── OAuth helpers ────────────────────────────────────────────────────────

    @staticmethod
    def get_auth_url(state: str = "") -> str:
        """Return the Zoom OAuth authorization URL."""
        params = httpx.QueryParams({
            "response_type": "code",
            "client_id": settings.ZOOM_CLIENT_ID,
            "redirect_uri": settings.ZOOM_REDIRECT_URI,
        })
        if state:
            params = params.set("state", state)
        return f"{_ZOOM_OAUTH_BASE}/authorize?{params}"

    @staticmethod
    async def exchange_code(code: str) -> Dict[str, Any]:
        """Exchange an authorization code for access + refresh tokens.

        Returns:
            Dict with access_token, refresh_token, expires_in, token_type, scope.
        Raises:
            ValueError: If Zoom returns an error.
        """
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                f"{_ZOOM_OAUTH_BASE}/token",
                params={
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": settings.ZOOM_REDIRECT_URI,
                },
                auth=(settings.ZOOM_CLIENT_ID, settings.ZOOM_CLIENT_SECRET),
            )
        if resp.status_code != 200:
            raise ValueError(f"Zoom token exchange failed: {resp.text}")
        data = resp.json()
        if "error" in data:
            raise ValueError(f"Zoom token exchange error: {data['error']} — {data.get('reason', '')}")
        logger.info("Zoom OAuth code exchange succeeded")
        return data

    @staticmethod
    async def refresh_access_token(refresh_token: str) -> Dict[str, Any]:
        """Refresh a Zoom access token using the stored refresh token.

        Returns:
            Dict with new access_token, refresh_token, expires_in.
        Raises:
            ValueError: If Zoom returns an error.
        """
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                f"{_ZOOM_OAUTH_BASE}/token",
                params={
                    "grant_type": "refresh_token",
                    "refresh_token": refresh_token,
                },
                auth=(settings.ZOOM_CLIENT_ID, settings.ZOOM_CLIENT_SECRET),
            )
        if resp.status_code != 200:
            raise ValueError(f"Zoom token refresh failed: {resp.text}")
        data = resp.json()
        if "error" in data:
            raise ValueError(f"Zoom token refresh error: {data['error']}")
        logger.info("Zoom access token refreshed")
        return data

    # ── API calls ────────────────────────────────────────────────────────────

    async def get_user(self, user_id: str = "me") -> Dict[str, Any]:
        """Fetch Zoom user info (defaults to the token owner)."""
        resp = await self._client.get(f"/users/{user_id}")
        resp.raise_for_status()
        return resp.json()

    async def get_recording(self, meeting_id: str) -> Dict[str, Any]:
        """Fetch cloud recording metadata for a meeting."""
        resp = await self._client.get(f"/meetings/{meeting_id}/recordings")
        resp.raise_for_status()
        return resp.json()

    async def download_recording_file(self, download_url: str) -> bytes:
        """Download a cloud recording file.

        Zoom requires the access token appended as a query param.
        """
        url_with_token = f"{download_url}?access_token={self.access_token}"
        async with httpx.AsyncClient(timeout=httpx.Timeout(300.0, connect=10.0), follow_redirects=True) as client:
            resp = await client.get(url_with_token)
        resp.raise_for_status()
        return resp.content

    # ── Webhook verification ─────────────────────────────────────────────────

    @staticmethod
    def verify_webhook_signature(
        body: bytes,
        signature: str,
        timestamp: str,
    ) -> bool:
        """Verify a Zoom webhook request using HMAC-SHA256.

        Zoom sends:
        - x-zm-signature      : v0=<hex-digest>
        - x-zm-request-timestamp: Unix timestamp (seconds, as string)

        Rejects requests older than 5 minutes to prevent replay attacks.

        Returns:
            True if valid, False otherwise.
        """
        if not timestamp or not signature:
            logger.warning("Zoom webhook: missing signature or timestamp header")
            return False

        try:
            ts_int = int(timestamp)
        except ValueError:
            logger.warning("Zoom webhook: non-integer timestamp '%s'", timestamp)
            return False

        if abs(time.time() - ts_int) > 300:
            logger.warning(
                "Zoom webhook: timestamp %d is outside 5-minute window", ts_int
            )
            return False

        message = f"v0:{timestamp}:".encode() + body
        expected = "v0=" + hmac.new(
            settings.ZOOM_WEBHOOK_SECRET_TOKEN.encode("utf-8"),
            message,
            hashlib.sha256,
        ).hexdigest()

        if not hmac.compare_digest(expected, signature):
            logger.warning(
                "Zoom webhook: signature mismatch (expected=%s…, got=%s…)",
                expected[:20],
                signature[:20],
            )
            return False

        return True

    # ── Cleanup ──────────────────────────────────────────────────────────────

    async def aclose(self) -> None:
        """Close the underlying HTTP client."""
        await self._client.aclose()


# ── Token refresh helper ───────────────────────────────────────────────────────


def token_needs_refresh(expires_at: Optional[datetime], buffer_minutes: int = 5) -> bool:
    """Return True if the access token expires within buffer_minutes."""
    if expires_at is None:
        return False
    return datetime.utcnow() >= expires_at - timedelta(minutes=buffer_minutes)
