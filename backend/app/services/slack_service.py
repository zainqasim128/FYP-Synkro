"""
Slack Web API wrapper — OAuth 2.0, Events API signature verification,
messaging, and rate-limit handling with exponential back-off + jitter.

Architecture note
-----------------
This module is a *service layer* class.  Routers and Celery tasks must
never call httpx directly; they go through :class:`SlackService`.

Required Slack App scopes
-------------------------
Bot Token Scopes  : channels:history, chat:write, users:read, incoming-webhook
OAuth Redirect URI: <SLACK_REDIRECT_URI>  (set in Slack App → OAuth & Permissions)
Event Subscriptions Request URL: <backend>/api/webhooks/slack/events
"""

import asyncio
import hashlib
import hmac
import logging
import random
import time
from typing import Any, Dict, List, Optional

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

_SLACK_API_BASE = "https://slack.com/api/"

# Required scopes — extend this list if you add Slack features later
_BOT_SCOPES: List[str] = [
    "channels:history",
    "chat:write",
    "users:read",
    "users:read.email",
    "incoming-webhook",
    "im:history",
    "im:read",
    "im:write",
    "mpim:history",
    "mpim:read",
    "mpim:write",
]

# User-level scopes so we can read user-to-user DMs
_USER_SCOPES: List[str] = [
    "im:history",
    "im:read",
    "channels:history",
    "users:read",
    "users:read.email",
]


class SlackService:
    """Thin async wrapper around the Slack Web API.

    Responsibilities:
    - OAuth 2.0 authorization code grant (bot token flow)
    - Signing-secret verification for Events API requests
    - Sending messages with Block Kit support
    - Fetching user / channel metadata
    - Automatic 429 retry with exponential back-off + jitter
    """

    def __init__(self, token: str) -> None:
        self.token = token
        # Reuse a single client per service instance for connection pooling
        self._client = httpx.AsyncClient(
            base_url=_SLACK_API_BASE,
            timeout=httpx.Timeout(10.0, connect=5.0),
            headers={"Authorization": f"Bearer {token}"},
        )

    # ── Construction helpers ─────────────────────────────────────────────────

    @classmethod
    def from_integration(cls, integration: Any) -> "SlackService":
        """Build a :class:`SlackService` from a DB :class:`Integration` row.

        Decrypts the stored access token using Fernet before use.
        Falls back to the raw value if decryption fails (e.g., dev plaintext).
        """
        from app.utils.security import decrypt_value

        tok = integration.access_token
        try:
            tok = decrypt_value(tok)
        except Exception:
            logger.warning(
                "Could not decrypt Slack token for integration %s — using raw value",
                integration.id,
            )
        return cls(token=tok)

    # ── Signature verification ───────────────────────────────────────────────

    @staticmethod
    def verify_signature(headers: Dict[str, str], body: bytes) -> bool:
        """Verify a Slack Events API request using HMAC-SHA256.

        Slack signs every request with:
        - ``X-Slack-Request-Timestamp``: Unix timestamp (seconds)
        - ``X-Slack-Signature``        : ``v0=<hex-digest>``

        The digest is: HMAC-SHA256(signing_secret, f"v0:{ts}:{raw_body}")

        Requests older than 5 minutes are rejected to prevent replay attacks.

        Args:
            headers: HTTP request headers dict (case-insensitive lookup).
            body   : Raw (un-parsed) request body bytes.

        Returns:
            ``True`` if the signature is valid, ``False`` otherwise.
        """
        # Case-insensitive header lookup
        ts_val = headers.get("x-slack-request-timestamp") or headers.get(
            "X-Slack-Request-Timestamp", ""
        )
        sig_val = headers.get("x-slack-signature") or headers.get(
            "X-Slack-Signature", ""
        )

        if not ts_val:
            logger.warning("Slack webhook: missing X-Slack-Request-Timestamp header")
            return False

        try:
            ts = int(ts_val)
        except ValueError:
            logger.warning("Slack webhook: non-integer timestamp '%s'", ts_val)
            return False

        # Replay-attack guard: reject requests older than 5 minutes
        if abs(time.time() - ts) > 300:
            logger.warning(
                "Slack webhook: request timestamp %d is outside the 5-minute window", ts
            )
            return False

        sig_base = f"v0:{ts_val}:".encode() + body
        expected = (
            "v0="
            + hmac.new(
                settings.SLACK_SIGNING_SECRET.encode("utf-8"),
                sig_base,
                hashlib.sha256,
            ).hexdigest()
        )

        if not hmac.compare_digest(expected, sig_val):
            logger.warning(
                "Slack webhook: signature mismatch (expected=%s, got=%s)",
                expected[:20] + "…",
                sig_val[:20] + "…",
            )
            return False

        return True

    # ── OAuth 2.0 helpers ────────────────────────────────────────────────────

    @classmethod
    def authorization_url(cls, state: Optional[str] = None) -> str:
        """Build the Slack OAuth v2 authorization URL.

        The frontend should redirect the user to this URL.  After consent,
        Slack redirects back to ``SLACK_REDIRECT_URI`` with a ``code`` param.

        Args:
            state: Optional CSRF token / workspace identifier to round-trip.

        Returns:
            Full ``https://slack.com/oauth/v2/authorize?...`` URL.
        """
        params: Dict[str, str] = {
            "client_id": settings.SLACK_CLIENT_ID,
            "scope": ",".join(_BOT_SCOPES),
            "user_scope": ",".join(_USER_SCOPES),
            "redirect_uri": settings.SLACK_REDIRECT_URI,
        }
        if state:
            params["state"] = state
        return "https://slack.com/oauth/v2/authorize?" + str(httpx.QueryParams(params))

    async def exchange_code(self, code: str) -> Dict[str, Any]:
        """Exchange an OAuth authorization code for a bot access token.

        Args:
            code: ``code`` query param from the OAuth redirect.

        Returns:
            Full ``oauth.v2.access`` response (contains ``access_token``,
            ``team``, ``bot_user_id``, ``incoming_webhook``, etc.).

        Raises:
            ValueError: If Slack returns ``ok: false``.
        """
        # Use a fresh client — no Authorization header needed for token exchange
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                f"{_SLACK_API_BASE}oauth.v2.access",
                data={
                    "client_id": settings.SLACK_CLIENT_ID,
                    "client_secret": settings.SLACK_CLIENT_SECRET,
                    "code": code,
                    "redirect_uri": settings.SLACK_REDIRECT_URI,
                },
            )
        resp.raise_for_status()
        data: Dict[str, Any] = resp.json()
        if not data.get("ok"):
            raise ValueError(
                f"Slack oauth.v2.access error: {data.get('error', data)}"
            )
        logger.info(
            "Slack OAuth token exchange succeeded for team=%s",
            data.get("team", {}).get("id"),
        )
        return data

    # ── Messaging ────────────────────────────────────────────────────────────

    async def post_message(
        self,
        channel: str,
        text: str,
        blocks: Optional[List[Dict[str, Any]]] = None,
        thread_ts: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Post a message to a Slack channel.

        Args:
            channel  : Channel ID (``C01234``) or name (``#general``).
            text     : Fallback / notification text (shown in push notifications).
            blocks   : Optional Block Kit payload for rich layout.
            thread_ts: Reply into a thread by providing the parent message ts.

        Returns:
            Slack API response dict (includes ``channel``, ``ts``, ``message``).
        """
        payload: Dict[str, Any] = {"channel": channel, "text": text}
        if blocks:
            payload["blocks"] = blocks
        if thread_ts:
            payload["thread_ts"] = thread_ts

        result = await self._request("chat.postMessage", json=payload)
        logger.info(
            "Slack message posted — channel=%s ts=%s", channel, result.get("ts")
        )
        return result

    # ── User / channel metadata ──────────────────────────────────────────────

    async def auth_test(self) -> Dict[str, Any]:
        """Call auth.test to get the identity of the token owner.

        Returns dict with at minimum ``user_id`` key (the Slack user ID of
        whoever owns this token).
        """
        resp = await self._request("auth.test", method="GET")
        return resp

    async def lookup_user_by_email(self, email: str) -> Optional[str]:
        """Look up a Slack user ID by email address.

        Requires ``users:read.email`` scope on the token.

        Args:
            email: The email address to look up.

        Returns:
            Slack user ID string (e.g. ``U01234``) or ``None`` if not found.
        """
        try:
            resp = await self._request(
                "users.lookupByEmail", method="GET", params={"email": email}
            )
            return resp.get("user", {}).get("id")
        except Exception as exc:
            logger.warning("lookup_user_by_email(%s) failed: %s", email, exc)
            return None

    async def get_user_info(self, user_id: str) -> Dict[str, Any]:
        """Fetch a Slack user's profile (requires ``users:read`` scope).

        Returns:
            ``user`` sub-dict from the Slack ``users.info`` response.
        """
        resp = await self._request(
            "users.info", method="GET", params={"user": user_id}
        )
        return resp.get("user", resp)

    async def open_dm_channel(self, slack_user_id: str) -> str:
        """Open (or retrieve existing) DM channel with a Slack user.

        Uses ``conversations.open`` which is idempotent — calling it multiple
        times for the same user just returns the existing channel.

        Args:
            slack_user_id: The Slack user ID to open a DM with (e.g. ``U01234``).

        Returns:
            The DM channel ID (starts with ``D``).
        """
        resp = await self._request(
            "conversations.open",
            json={"users": slack_user_id},
        )
        return resp["channel"]["id"]

    async def list_workspace_users(self) -> List[Dict[str, Any]]:
        """List ALL non-bot, non-deleted workspace members using cursor pagination.

        Returns:
            List of user dicts (id, name, real_name, profile).
        """
        all_members: List[Dict[str, Any]] = []
        cursor: Optional[str] = None

        while True:
            params: Dict[str, Any] = {"limit": 200}
            if cursor:
                params["cursor"] = cursor
            resp = await self._request("users.list", method="GET", params=params)
            members = resp.get("members", [])
            all_members.extend(
                m for m in members
                if not m.get("is_bot") and not m.get("deleted") and m.get("id") != "USLACKBOT"
            )
            cursor = resp.get("response_metadata", {}).get("next_cursor")
            if not cursor:
                break

        return all_members

    async def list_im_channels(self) -> List[Dict[str, Any]]:
        """List all DM (im) channels accessible to this token.

        Works with user tokens (xoxp-) that have ``im:read`` scope.

        Returns:
            List of channel dicts with ``id`` and ``user`` (Slack user ID).
        """
        channels: List[Dict[str, Any]] = []
        cursor: Optional[str] = None
        while True:
            params: Dict[str, Any] = {"types": "im", "limit": 200}
            if cursor:
                params["cursor"] = cursor
            resp = await self._request("conversations.list", method="GET", params=params)
            channels.extend(resp.get("channels", []))
            cursor = resp.get("response_metadata", {}).get("next_cursor")
            if not cursor:
                break
        return channels

    async def get_channel_messages(
        self,
        channel_id: str,
        limit: int = 50,
        oldest: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Fetch recent messages from a channel or DM.

        Works with user tokens (xoxp-) that have ``im:history`` scope.

        Args:
            channel_id: Channel or DM ID.
            limit     : Max number of messages (Slack max 999).
            oldest    : Only return messages newer than this Unix timestamp string.

        Returns:
            List of message dicts.
        """
        params: Dict[str, Any] = {"channel": channel_id, "limit": limit}
        if oldest:
            params["oldest"] = oldest
        resp = await self._request("conversations.history", method="GET", params=params)
        return resp.get("messages", [])

    async def get_channel_members(self, channel_id: str) -> List[str]:
        """Return list of Slack user IDs in a channel/DM.

        Works with tokens that have ``channels:read`` or ``im:read`` scope.
        """
        resp = await self._request(
            "conversations.members", method="GET", params={"channel": channel_id}
        )
        return resp.get("members", [])

    async def get_channel_info(self, channel_id: str) -> Dict[str, Any]:
        """Fetch channel metadata (requires ``channels:read`` scope).

        Returns:
            ``channel`` sub-dict from the Slack ``conversations.info`` response.
        """
        resp = await self._request(
            "conversations.info", method="GET", params={"channel": channel_id}
        )
        return resp.get("channel", resp)

    # ── Internal HTTP helper ─────────────────────────────────────────────────

    async def _request(
        self,
        endpoint: str,
        method: str = "POST",
        max_retries: int = 5,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """Execute a Slack API call with 429 back-off + jitter.

        Rate-limiting strategy:
        - Honour the ``Retry-After`` header from Slack (in seconds).
        - Add exponential factor: ``wait = retry_after * 2^attempt + jitter``.
        - Jitter (0–1s) prevents thundering-herd when multiple workers hit
          the same Slack workspace simultaneously.

        Args:
            endpoint   : Slack API method name, e.g. ``"chat.postMessage"``.
            method     : HTTP verb (``"POST"`` or ``"GET"``).
            max_retries: Max number of 429-retry attempts before giving up.
            **kwargs   : Passed through to ``httpx.AsyncClient.request``.

        Returns:
            Parsed JSON response dict (always has ``ok: true``).

        Raises:
            ValueError   : Slack returned ``ok: false`` (API-level error).
            RuntimeError : Exhausted all retry attempts.
        """
        for attempt in range(max_retries):
            resp = await self._client.request(method, endpoint, **kwargs)

            if resp.status_code == 429:
                retry_after = int(resp.headers.get("Retry-After", "1"))
                jitter = random.uniform(0.0, 1.0)
                wait = retry_after * (2 ** attempt) + jitter
                logger.warning(
                    "Slack rate-limited on %s (attempt %d/%d) — sleeping %.2fs",
                    endpoint,
                    attempt + 1,
                    max_retries,
                    wait,
                )
                await asyncio.sleep(wait)
                continue

            resp.raise_for_status()
            data: Dict[str, Any] = resp.json()

            if not data.get("ok"):
                error = data.get("error", "unknown_error")
                logger.error(
                    "Slack API error on %s: error=%s response=%s",
                    endpoint,
                    error,
                    data,
                )
                raise ValueError(f"Slack API [{endpoint}] error: {error}")

            return data

        raise RuntimeError(
            f"Slack API {endpoint}: exceeded {max_retries} rate-limit retry attempts"
        )

    async def aclose(self) -> None:
        """Close the underlying HTTP client."""
        await self._client.aclose()


# ── Dependency factory ─────────────────────────────────────────────────────────


def get_slack_service(integration: Any) -> SlackService:
    """FastAPI/Celery dependency: build a :class:`SlackService` from a DB row."""
    return SlackService.from_integration(integration)
