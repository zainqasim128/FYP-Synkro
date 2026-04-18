"""
Jira Cloud REST API v3 wrapper with:
- Atlassian Document Format (ADF) conversion for rich text fields
- Credential verification
- Issue CRUD + status transitions
- Project listing
- Exponential back-off + jitter on 429

Architecture note
-----------------
Jira Cloud REST API v3 (https://developer.atlassian.com/cloud/jira/platform/rest/v3/)
requires HTTP Basic Auth:  email : api_token
The ``description`` field must be Atlassian Document Format (ADF), NOT a plain string.
Transition (status change) and PUT endpoints return 204 No Content on success.

API token generation: https://id.atlassian.com → Security → API tokens
"""

import asyncio
import logging
import random
from typing import Any, Dict, List, Optional

import httpx

logger = logging.getLogger(__name__)

# ── Priority mapping ───────────────────────────────────────────────────────────
# Internal TaskPriority enum values → Jira priority display names
PRIORITY_MAP: Dict[str, str] = {
    "low": "Low",
    "medium": "Medium",
    "high": "High",
    "urgent": "Highest",
}


def _to_adf(text: str) -> Dict[str, Any]:
    """Convert plain text to Atlassian Document Format (ADF).

    Jira Cloud REST API v3 rejects plain-string ``description`` values.
    This wraps the text in a single-paragraph ADF document.

    Args:
        text: Plain-text content.

    Returns:
        ADF document dict compatible with ``fields.description``.
    """
    return {
        "version": 1,
        "type": "doc",
        "content": [
            {
                "type": "paragraph",
                "content": [{"type": "text", "text": text}],
            }
        ],
    }


class JiraService:
    """Async wrapper for Jira Cloud REST API v3.

    Authentication: HTTP Basic Auth using the user's Atlassian email and an
    API token (generated at https://id.atlassian.com/manage-profile/security).

    Usage::

        svc = JiraService("acme.atlassian.net", "user@acme.com", "<token>")
        issue = await svc.create_issue("PROJ", "Fix login bug", priority="high")
        print(issue["key"])  # PROJ-42
    """

    def __init__(self, domain: str, email: str, api_token: str) -> None:
        # Normalise domain: strip scheme and trailing slash
        clean_domain = (
            domain.rstrip("/")
            .removeprefix("https://")
            .removeprefix("http://")
        )
        self._domain = clean_domain
        self._base_url = f"https://{clean_domain}/rest/api/3"

        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            auth=httpx.BasicAuth(email, api_token),
            timeout=httpx.Timeout(15.0, connect=5.0),
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
        )

    @classmethod
    def from_integration(cls, integration: Any) -> "JiraService":
        """Build a :class:`JiraService` from a DB :class:`Integration` row.

        Decrypts the stored API token using Fernet before use.
        Falls back to the raw value if decryption fails.
        """
        from app.utils.security import decrypt_value

        meta: Dict[str, Any] = integration.platform_metadata or {}
        domain: str = meta.get("domain", "")
        email: str = meta.get("email", "")
        token: str = integration.access_token
        try:
            token = decrypt_value(token)
        except Exception:
            logger.warning(
                "Could not decrypt Jira token for integration %s — using raw value",
                integration.id,
            )
        return cls(domain=domain, email=email, api_token=token)

    # ── Credential validation ────────────────────────────────────────────────

    async def verify_credentials(self) -> Dict[str, Any]:
        """Verify that the stored credentials are valid by calling ``/myself``.

        Returns:
            Atlassian account info dict (``accountId``, ``displayName``, etc.).

        Raises:
            ValueError: If the credentials are invalid (401/403).
        """
        return await self._request("myself", method="GET")

    # ── Projects ─────────────────────────────────────────────────────────────

    async def list_projects(self) -> List[Dict[str, Any]]:
        """Return all projects the authenticated user can access.

        Returns:
            List of project dicts, each containing ``id``, ``key``, ``name``.
        """
        resp = await self._request("project/search", method="GET")
        return resp.get("values", [])

    # ── Issues ───────────────────────────────────────────────────────────────

    async def create_issue(
        self,
        project_key: str,
        summary: str,
        description: Optional[str] = None,
        priority: Optional[str] = None,
        duedate: Optional[str] = None,
        issue_type: str = "Task",
        extra_fields: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Create a Jira issue.

        Field mapping from Synkro internal model to Jira:

        ===============  =========================  =====================
        Internal field   Jira field                 Notes
        ===============  =========================  =====================
        title            ``fields.summary``         Plain string
        description      ``fields.description``     Auto-converted to ADF
        priority         ``fields.priority.name``   Mapped via PRIORITY_MAP
        due_date         ``fields.duedate``         Must be ``YYYY-MM-DD``
        ===============  =========================  =====================

        Args:
            project_key : Jira project key, e.g. ``"PROJ"``.
            summary     : Issue title / summary.
            description : Plain-text body — converted to ADF automatically.
            priority    : Internal priority string (``"low"``–``"urgent"``) or
                          a raw Jira name (``"High"``).
            duedate     : ISO date string ``"YYYY-MM-DD"``.
            issue_type  : Jira issue type name (default ``"Task"``).
            extra_fields: Additional raw Jira field dict merged into ``fields``.

        Returns:
            Dict with ``id``, ``key``, ``self`` from Jira (HTTP 201 response).
        """
        fields: Dict[str, Any] = {
            "project": {"key": project_key},
            "summary": summary,
            "issuetype": {"name": issue_type},
        }

        if description:
            # Jira v3 API requires ADF — plain strings return HTTP 400
            fields["description"] = _to_adf(description)

        if priority:
            jira_priority = PRIORITY_MAP.get(priority.lower(), priority.capitalize())
            fields["priority"] = {"name": jira_priority}

        if duedate:
            fields["duedate"] = duedate

        if extra_fields:
            fields.update(extra_fields)

        result = await self._request("issue", method="POST", json={"fields": fields})
        logger.info(
            "Jira issue created: key=%s id=%s project=%s",
            result.get("key"),
            result.get("id"),
            project_key,
        )
        return result

    async def get_issue(self, issue_id_or_key: str) -> Dict[str, Any]:
        """Fetch full issue detail by ID or key (e.g. ``"PROJ-42"``).

        Returns the complete Jira issue object including fields, comments, etc.
        """
        return await self._request(f"issue/{issue_id_or_key}", method="GET")

    async def get_transitions(self, issue_id_or_key: str) -> List[Dict[str, Any]]:
        """Return the available status transitions for an issue.

        Use this to discover the ``id`` needed by :meth:`update_issue_status`.

        Returns:
            List of transition dicts, each with ``id``, ``name``, ``to`` status.
        """
        resp = await self._request(
            f"issue/{issue_id_or_key}/transitions", method="GET"
        )
        return resp.get("transitions", [])

    async def update_issue_status(
        self,
        issue_id_or_key: str,
        transition_id: str,
    ) -> None:
        """Transition an issue to a new workflow status.

        The Jira transitions endpoint returns HTTP 204 (No Content) on success,
        so this method returns ``None``.

        Args:
            issue_id_or_key: Issue ID (``"10001"``) or key (``"PROJ-42"``).
            transition_id  : Transition ID from :meth:`get_transitions`.
        """
        await self._request(
            f"issue/{issue_id_or_key}/transitions",
            method="POST",
            json={"transition": {"id": transition_id}},
        )
        logger.info(
            "Jira issue %s transitioned via transition_id=%s",
            issue_id_or_key,
            transition_id,
        )

    async def update_issue_fields(
        self,
        issue_id_or_key: str,
        fields: Dict[str, Any],
    ) -> None:
        """Partially update issue fields (PUT → 204 No Content).

        Args:
            issue_id_or_key: Issue ID or key.
            fields          : Dict of Jira field names to new values.
                              Strings in ``description`` are auto-converted to ADF.
        """
        # Auto-convert description if a plain string is passed
        if "description" in fields and isinstance(fields["description"], str):
            fields = {**fields, "description": _to_adf(fields["description"])}

        await self._request(
            f"issue/{issue_id_or_key}",
            method="PUT",
            json={"fields": fields},
        )
        logger.info(
            "Jira issue %s fields updated: %s",
            issue_id_or_key,
            list(fields.keys()),
        )

    # ── Internal HTTP helper ─────────────────────────────────────────────────

    async def _request(
        self,
        endpoint: str,
        method: str = "GET",
        max_retries: int = 5,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """Execute a Jira API request with exponential back-off + jitter on 429.

        Rate-limiting strategy mirrors :class:`SlackService`:
        - Honour the ``Retry-After`` header value.
        - Multiply by ``2^attempt`` and add random jitter (0–1s).
        - Return an empty dict for 204 No Content responses (transitions, PUTs).

        Args:
            endpoint   : Path relative to base URL, e.g. ``"issue/PROJ-1"``.
            method     : HTTP verb.
            max_retries: Max number of 429-retry attempts.
            **kwargs   : Forwarded to ``httpx.AsyncClient.request``.

        Returns:
            Parsed JSON body, or ``{}`` for 204 responses.

        Raises:
            ValueError  : On 4xx errors (bad request, auth failure, not found).
            RuntimeError: After exhausting all retry attempts.
        """
        for attempt in range(max_retries):
            resp = await self._client.request(method, endpoint, **kwargs)

            if resp.status_code == 429:
                retry_after = int(resp.headers.get("Retry-After", "1"))
                jitter = random.uniform(0.0, 1.0)
                wait = retry_after * (2 ** attempt) + jitter
                logger.warning(
                    "Jira rate-limited on %s %s (attempt %d/%d) — sleeping %.2fs",
                    method,
                    endpoint,
                    attempt + 1,
                    max_retries,
                    wait,
                )
                await asyncio.sleep(wait)
                continue

            # 204 No Content: transitions, PUT field updates, DELETE — no body
            if resp.status_code == 204:
                return {}

            # 4xx / 5xx errors
            if resp.status_code >= 400:
                try:
                    body: Any = resp.json()
                except Exception:
                    body = resp.text
                logger.error(
                    "Jira API error: %s %s → HTTP %d | body=%s",
                    method,
                    endpoint,
                    resp.status_code,
                    body,
                )
                raise ValueError(
                    f"Jira API {method} /{endpoint} → {resp.status_code}: {body}"
                )

            # 201 Created (issue creation), 200 OK (reads)
            if resp.content:
                return resp.json()  # type: ignore[return-value]
            return {}

        raise RuntimeError(
            f"Jira API {method} /{endpoint}: exceeded {max_retries} rate-limit retries"
        )

    async def aclose(self) -> None:
        """Close the underlying HTTP client."""
        await self._client.aclose()


# ── Dependency factory ─────────────────────────────────────────────────────────


def get_jira_service(integration: Any) -> JiraService:
    """FastAPI/Celery dependency: build a :class:`JiraService` from a DB row."""
    return JiraService.from_integration(integration)
