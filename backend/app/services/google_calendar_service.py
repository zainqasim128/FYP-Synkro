"""
Google Calendar API v3 service.

Handles OAuth 2.0 token exchange, event CRUD, and token refresh.
Uses httpx (already in requirements) — mirrors ZoomService structure.
"""

import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional
from urllib.parse import urlencode

import httpx


from app.config import settings

logger = logging.getLogger(__name__)

_GCAL_API_BASE = "https://www.googleapis.com/calendar/v3"
_GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/auth"
_GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
_SCOPES = [
    "https://www.googleapis.com/auth/calendar.events",
    "https://www.googleapis.com/auth/calendar.readonly",
]


class GoogleCalendarService:
    """Async Google Calendar API client.

    Usage:
        svc = GoogleCalendarService.from_integration(integration)
        event = await svc.create_event("primary", event_body)
        await svc.aclose()
    """

    def __init__(
        self,
        access_token: str,
        refresh_token: Optional[str] = None,
        integration_id: Optional[str] = None,
    ) -> None:
        self.access_token = access_token
        self.refresh_token = refresh_token
        self.integration_id = integration_id
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(30.0, connect=5.0),
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    # ── Factory ──────────────────────────────────────────────────────────────

    @classmethod
    def from_integration(cls, integration: Any) -> "GoogleCalendarService":
        """Build service from a DB Integration row (decrypts tokens)."""
        from app.utils.security import decrypt_value

        access_token = decrypt_value(integration.access_token)
        refresh_token = (
            decrypt_value(integration.refresh_token)
            if integration.refresh_token
            else None
        )
        return cls(
            access_token=access_token,
            refresh_token=refresh_token,
            integration_id=integration.id,
        )

    # ── OAuth helpers (class-level, no token needed) ─────────────────────────

    @classmethod
    def get_authorization_url(cls, state: str) -> str:
        """Build the Google OAuth consent screen URL."""
        params = {
            "client_id": settings.GOOGLE_CLIENT_ID,
            "redirect_uri": settings.GOOGLE_CALENDAR_REDIRECT_URI,
            "response_type": "code",
            "scope": " ".join(_SCOPES),
            "access_type": "offline",
            "prompt": "consent",
            "state": state,
        }
        return _GOOGLE_AUTH_URL + "?" + urlencode(params)

    @classmethod
    async def exchange_code(cls, code: str) -> Dict[str, Any]:
        """Exchange authorization code for access + refresh tokens."""
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                _GOOGLE_TOKEN_URL,
                data={
                    "code": code,
                    "client_id": settings.GOOGLE_CLIENT_ID,
                    "client_secret": settings.GOOGLE_CLIENT_SECRET,
                    "redirect_uri": settings.GOOGLE_CALENDAR_REDIRECT_URI,
                    "grant_type": "authorization_code",
                },
            )
            resp.raise_for_status()
            return resp.json()

    # ── Token refresh ────────────────────────────────────────────────────────

    async def refresh_access_token(self) -> str:
        """Use refresh_token to get a new access token. Returns new token."""
        if not self.refresh_token:
            raise ValueError("No refresh token available")

        resp = await self._client.post(
            _GOOGLE_TOKEN_URL,
            data={
                "client_id": settings.GOOGLE_CLIENT_ID,
                "client_secret": settings.GOOGLE_CLIENT_SECRET,
                "refresh_token": self.refresh_token,
                "grant_type": "refresh_token",
            },
        )
        resp.raise_for_status()
        data = resp.json()
        self.access_token = data["access_token"]
        return self.access_token

    async def _persist_refreshed_token(self, db: Any) -> None:
        """Store refreshed access token back to the DB integration row."""
        from sqlalchemy import select
        from app.models.integration import Integration
        from app.utils.security import encrypt_value

        result = await db.execute(
            select(Integration).where(Integration.id == self.integration_id)
        )
        integration = result.scalar_one_or_none()
        if integration:
            integration.access_token = encrypt_value(self.access_token)
            await db.commit()

    # ── HTTP request with auto-refresh on 401 ────────────────────────────────

    async def _request(
        self, method: str, path: str, db: Any = None, **kwargs
    ) -> Dict[str, Any]:
        headers = {"Authorization": f"Bearer {self.access_token}"}
        kwargs.setdefault("headers", {}).update(headers)

        resp = await self._client.request(method, _GCAL_API_BASE + path, **kwargs)

        if resp.status_code == 401 and self.refresh_token:
            logger.info("GCal token expired, refreshing for integration %s", self.integration_id)
            await self.refresh_access_token()
            if db:
                await self._persist_refreshed_token(db)
            kwargs["headers"]["Authorization"] = f"Bearer {self.access_token}"
            resp = await self._client.request(method, _GCAL_API_BASE + path, **kwargs)

        if resp.status_code == 204:
            return {}

        if not resp.is_success:
            try:
                body = resp.json()
                err = body.get("error", {})
                reason = err.get("errors", [{}])[0].get("reason", "")
                message = err.get("message", resp.text)
                logger.error("GCal API %d for %s: reason=%s message=%s", resp.status_code, path, reason, message)
            except Exception:
                logger.error("GCal API %d for %s: %s", resp.status_code, path, resp.text[:500])
            resp.raise_for_status()

        return resp.json()

    # ── Event CRUD ───────────────────────────────────────────────────────────

    async def create_event(
        self, calendar_id: str, event: Dict[str, Any], db: Any = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        return await self._request(
            "POST", f"/calendars/{calendar_id}/events", db=db, json=event, params=params
        )

    async def update_event(
        self, calendar_id: str, event_id: str, event: Dict[str, Any], db: Any = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        return await self._request(
            "PUT", f"/calendars/{calendar_id}/events/{event_id}", db=db, json=event, params=params
        )

    async def get_event(
        self, calendar_id: str, event_id: str, db: Any = None
    ) -> Dict[str, Any]:
        return await self._request("GET", f"/calendars/{calendar_id}/events/{event_id}", db=db)

    async def delete_event(
        self, calendar_id: str, event_id: str, db: Any = None
    ) -> None:
        try:
            await self._request(
                "DELETE", f"/calendars/{calendar_id}/events/{event_id}", db=db
            )
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                logger.warning("Calendar event %s not found — already deleted", event_id)
            else:
                raise

    async def get_freebusy(
        self, time_min: str, time_max: str, db: Any = None
    ) -> Dict[str, Any]:
        body = {
            "timeMin": time_min,
            "timeMax": time_max,
            "items": [{"id": "primary"}],
        }
        return await self._request("POST", "/freeBusy", db=db, json=body)

    async def list_events(
        self, time_min: str, time_max: str, db: Any = None
    ) -> List[Dict[str, Any]]:
        resp = await self._request(
            "GET",
            "/calendars/primary/events",
            db=db,
            params={
                "timeMin": time_min,
                "timeMax": time_max,
                "singleEvents": "true",
                "orderBy": "startTime",
            },
        )
        return resp.get("items", [])

    async def verify_connection(self) -> Dict[str, Any]:
        """Confirm the token works by fetching the primary calendar metadata."""
        resp = await self._client.get(
            f"{_GCAL_API_BASE}/calendars/primary",
            headers={"Authorization": f"Bearer {self.access_token}"},
        )
        if not resp.is_success:
            try:
                body = resp.json()
                err = body.get("error", {})
                reason = err.get("errors", [{}])[0].get("reason", "")
                message = err.get("message", "Unknown error")
                logger.error(
                    "GCal verify_connection %d: reason=%s message=%s",
                    resp.status_code, reason, message,
                )
            except Exception:
                logger.error("GCal verify_connection %d: %s", resp.status_code, resp.text[:300])
            resp.raise_for_status()
        return resp.json()

    # ── Conversion helpers ───────────────────────────────────────────────────

    @staticmethod
    def task_to_event(
        task: Any, assignee_name: str, synkro_url: str, user_timezone: str = "UTC"
    ) -> Dict[str, Any]:
        """Convert a Synkro Task into a Google Calendar event body."""
        priority = task.priority.value if hasattr(task.priority, "value") else str(task.priority)

        description_lines = []
        if task.description:
            description_lines.append(task.description)
        description_lines += [
            f"Priority: {priority.upper()}",
            f"Assigned to: {assignee_name}",
            f"View in Synkro: {synkro_url}/dashboard/tasks",
        ]

        status = task.status.value if hasattr(task.status, "value") else str(task.status)
        title_prefix = "[DONE]" if status == "done" else "[BLOCKED]" if status == "blocked" else "[TASK]"

        due_dt: datetime = task.due_date
        has_time = due_dt and (due_dt.hour != 0 or due_dt.minute != 0)

        if has_time:
            # due_date is stored as the user's local time (no UTC conversion on ingest)
            # so use it directly with the user's timezone string
            duration_hours = task.estimated_hours if task.estimated_hours and task.estimated_hours > 0 else 1
            end_dt = due_dt + timedelta(hours=duration_hours)
            start_block = {"dateTime": due_dt.strftime("%Y-%m-%dT%H:%M:%S"), "timeZone": user_timezone}
            end_block = {"dateTime": end_dt.strftime("%Y-%m-%dT%H:%M:%S"), "timeZone": user_timezone}
        else:
            # All-day event: use the date as stored (UTC date is the correct calendar date)
            due_date_str = due_dt.strftime("%Y-%m-%d") if due_dt else None
            next_day_str = (due_dt + timedelta(days=1)).strftime("%Y-%m-%d") if due_dt else None
            start_block = {"date": due_date_str}
            end_block = {"date": next_day_str}

        return {
            "summary": f"{title_prefix} {task.title}",
            "description": "\n".join(description_lines),
            "start": start_block,
            "end": end_block,
            "reminders": GoogleCalendarService._build_reminders(priority, {}),
        }

    @staticmethod
    def _build_reminders(priority: str, preferences: Dict[str, Any]) -> Dict[str, Any]:
        """Build Google Calendar reminders dict for a given task priority."""
        defaults: Dict[str, List[Dict[str, Any]]] = {
            "urgent": [
                {"method": "email", "minutes": 2880},
                {"method": "email", "minutes": 120},
                {"method": "popup", "minutes": 30},
            ],
            "high": [
                {"method": "email", "minutes": 1440},
                {"method": "popup", "minutes": 120},
            ],
            "medium": [
                {"method": "email", "minutes": 1440},
                {"method": "popup", "minutes": 60},
            ],
            "low": [
                {"method": "email", "minutes": 360},
            ],
        }
        overrides = defaults.get(priority, defaults["medium"])
        return {"useDefault": False, "overrides": overrides}
