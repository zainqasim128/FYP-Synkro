"""
Tests for integration endpoints (Slack, Jira).
"""
import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.models import Integration, IntegrationPlatform
from app.services import slack_service


@pytest.mark.asyncio
async def test_slack_start_endpoint(client: AsyncClient):
    """Slack start should return an authorization URL."""
    response = await client.get("/api/integrations/slack/start")
    assert response.status_code == 200
    data = response.json()
    assert "authorization_url" in data
    assert data["authorization_url"].startswith("https://")


@pytest.mark.asyncio
async def test_jira_connect_endpoint(client: AsyncClient, test_db, auth_headers):
    """Posting Jira credentials should create an integration and redirect."""
    payload = {
        "domain": "example.atlassian.net",
        "email": "user@example.com",
        "api_token": "fake-token-123",
    }
    # do not follow redirects so we can assert 302
    response = await client.post(
        "/api/integrations/jira/connect",
        headers=auth_headers,
        json=payload,
        follow_redirects=False,
    )
    assert response.status_code == 302

    # verify integration record exists (filter by platform)
    result = await test_db.execute(select(Integration).where(Integration.platform == IntegrationPlatform.JIRA))
    integration = result.scalar_one_or_none()
    assert integration is not None
    assert integration.platform == IntegrationPlatform.JIRA
    assert integration.platform_metadata.get("domain") == "example.atlassian.net"


@pytest.mark.asyncio
async def test_slack_callback_creates_integration(client: AsyncClient, test_db, auth_headers, monkeypatch):
    """Mock Slack exchange_code and ensure callback stores integration and redirects."""
    fake_resp = {
        "ok": True,
        "team": {"id": "T123"},
        "bot_user_id": "B123",
        "access_token": "xoxb-faketoken",
        "scope": "chat:write",
    }

    async def fake_exchange(self, code: str):
        return fake_resp

    monkeypatch.setattr(slack_service.SlackService, "exchange_code", fake_exchange)

    response = await client.get(
        "/api/integrations/slack/callback",
        headers=auth_headers,
        params={"code": "dummy-code"},
        follow_redirects=False,
    )
    assert response.status_code == 302
    # look up the stored integration
    result = await test_db.execute(select(Integration).where(Integration.platform == IntegrationPlatform.SLACK))
    integration = result.scalar_one_or_none()
    assert integration is not None
    assert integration.platform_metadata.get("team_id") == "T123"
    # access_token should be encrypted string (nonempty)
    assert integration.access_token != ""
