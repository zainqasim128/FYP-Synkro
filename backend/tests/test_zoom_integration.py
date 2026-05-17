"""
Unit tests for Zoom integration.

Covers:
- ZoomService.verify_webhook_signature (HMAC-SHA256 validation)
- Dedup guard in _handle_recording_completed (zoom_recording_id uniqueness)
- token_needs_refresh helper
"""
import hashlib
import hmac
import time
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.zoom_service import ZoomService, token_needs_refresh


# ── Webhook signature verification ───────────────────────────────────────────


def _make_signature(secret: str, timestamp: str, body: bytes) -> str:
    """Reproduce the HMAC-SHA256 Zoom signature for a given payload."""
    message = f"v0:{timestamp}:".encode() + body
    digest = hmac.new(secret.encode(), message, hashlib.sha256).hexdigest()
    return f"v0={digest}"


class TestVerifyWebhookSignature:
    SECRET = "test-webhook-secret"
    BODY = b'{"event":"recording.completed"}'

    def test_valid_signature_accepted(self):
        ts = str(int(time.time()))
        sig = _make_signature(self.SECRET, ts, self.BODY)
        with patch("app.services.zoom_service.settings") as mock_settings:
            mock_settings.ZOOM_WEBHOOK_SECRET_TOKEN = self.SECRET
            result = ZoomService.verify_webhook_signature(self.BODY, sig, ts)
        assert result is True

    def test_wrong_secret_rejected(self):
        ts = str(int(time.time()))
        sig = _make_signature("wrong-secret", ts, self.BODY)
        with patch("app.services.zoom_service.settings") as mock_settings:
            mock_settings.ZOOM_WEBHOOK_SECRET_TOKEN = self.SECRET
            result = ZoomService.verify_webhook_signature(self.BODY, sig, ts)
        assert result is False

    def test_tampered_body_rejected(self):
        ts = str(int(time.time()))
        sig = _make_signature(self.SECRET, ts, self.BODY)
        tampered = b'{"event":"recording.completed","extra":"injected"}'
        with patch("app.services.zoom_service.settings") as mock_settings:
            mock_settings.ZOOM_WEBHOOK_SECRET_TOKEN = self.SECRET
            result = ZoomService.verify_webhook_signature(tampered, sig, ts)
        assert result is False

    def test_old_timestamp_rejected(self):
        # Timestamp more than 5 minutes in the past
        ts = str(int(time.time()) - 400)
        sig = _make_signature(self.SECRET, ts, self.BODY)
        with patch("app.services.zoom_service.settings") as mock_settings:
            mock_settings.ZOOM_WEBHOOK_SECRET_TOKEN = self.SECRET
            result = ZoomService.verify_webhook_signature(self.BODY, sig, ts)
        assert result is False

    def test_future_timestamp_rejected(self):
        # Timestamp more than 5 minutes in the future
        ts = str(int(time.time()) + 400)
        sig = _make_signature(self.SECRET, ts, self.BODY)
        with patch("app.services.zoom_service.settings") as mock_settings:
            mock_settings.ZOOM_WEBHOOK_SECRET_TOKEN = self.SECRET
            result = ZoomService.verify_webhook_signature(self.BODY, sig, ts)
        assert result is False

    def test_missing_signature_rejected(self):
        ts = str(int(time.time()))
        with patch("app.services.zoom_service.settings") as mock_settings:
            mock_settings.ZOOM_WEBHOOK_SECRET_TOKEN = self.SECRET
            result = ZoomService.verify_webhook_signature(self.BODY, "", ts)
        assert result is False

    def test_missing_timestamp_rejected(self):
        ts = str(int(time.time()))
        sig = _make_signature(self.SECRET, ts, self.BODY)
        with patch("app.services.zoom_service.settings") as mock_settings:
            mock_settings.ZOOM_WEBHOOK_SECRET_TOKEN = self.SECRET
            result = ZoomService.verify_webhook_signature(self.BODY, sig, "")
        assert result is False

    def test_non_integer_timestamp_rejected(self):
        sig = _make_signature(self.SECRET, "not-a-number", self.BODY)
        with patch("app.services.zoom_service.settings") as mock_settings:
            mock_settings.ZOOM_WEBHOOK_SECRET_TOKEN = self.SECRET
            result = ZoomService.verify_webhook_signature(self.BODY, sig, "not-a-number")
        assert result is False


# ── token_needs_refresh helper ────────────────────────────────────────────────


class TestTokenNeedsRefresh:
    def test_no_expiry_does_not_need_refresh(self):
        assert token_needs_refresh(None) is False

    def test_token_far_future_does_not_need_refresh(self):
        future = datetime.utcnow() + timedelta(hours=2)
        assert token_needs_refresh(future) is False

    def test_token_expiring_within_buffer_needs_refresh(self):
        # Expires in 3 minutes, buffer is 5 → should need refresh
        almost_expired = datetime.utcnow() + timedelta(minutes=3)
        assert token_needs_refresh(almost_expired, buffer_minutes=5) is True

    def test_already_expired_needs_refresh(self):
        past = datetime.utcnow() - timedelta(minutes=10)
        assert token_needs_refresh(past) is True

    def test_custom_buffer(self):
        # With a 1-minute buffer, a token expiring in 2 minutes should NOT need refresh
        in_two_minutes = datetime.utcnow() + timedelta(minutes=2)
        assert token_needs_refresh(in_two_minutes, buffer_minutes=1) is False
        # But with a 3-minute buffer it should
        assert token_needs_refresh(in_two_minutes, buffer_minutes=3) is True


# ── Dedup guard (zoom_recording_id) ──────────────────────────────────────────


async def test_recording_completed_dedup_guard():
    """
    _handle_recording_completed must skip processing if zoom_recording_id
    already exists in the database (Zoom can retry webhook delivery).
    """
    from app.routers.integrations import _handle_recording_completed

    existing_meeting = MagicMock()
    existing_meeting.id = "existing-meeting-id"

    # Simulate DB returning an existing meeting for the recording_id
    mock_scalar = MagicMock()
    mock_scalar.scalar_one_or_none.return_value = existing_meeting

    mock_db = AsyncMock()
    mock_db.execute.return_value = mock_scalar

    obj = {
        "id": "zoom-meeting-123",
        "topic": "Weekly Standup",
        "start_time": "2024-01-15T10:00:00Z",
        "duration": 45,
        "host_id": "host-abc",
        "recording_files": [
            {
                "id": "rec-file-already-processed",
                "file_type": "MP4",
                "status": "completed",
                "download_url": "https://example.zoom.us/rec/download/...",
            }
        ],
    }

    # Should return early without creating a new meeting or downloading anything
    await _handle_recording_completed(obj, mock_db)

    # db.execute called once (for dedup check), then no further inserts
    assert mock_db.execute.call_count == 1
    mock_db.add.assert_not_called()
    mock_db.commit.assert_not_called()


async def test_recording_completed_skips_when_no_recording_files():
    """Handler must exit gracefully when recording_files is empty."""
    from app.routers.integrations import _handle_recording_completed

    mock_db = AsyncMock()

    obj = {
        "id": "zoom-meeting-456",
        "topic": "Empty Meeting",
        "host_id": "host-xyz",
        "recording_files": [],
    }

    await _handle_recording_completed(obj, mock_db)

    # Nothing committed — no files to process
    mock_db.commit.assert_not_called()


async def test_meeting_ended_skips_when_no_zoom_integration():
    """meeting.ended handler must skip gracefully when no matching integration exists."""
    from app.routers.integrations import _handle_meeting_ended

    # DB returns no integrations
    mock_scalar = MagicMock()
    mock_scalar.scalars.return_value.all.return_value = []

    mock_db = AsyncMock()
    mock_db.execute.return_value = mock_scalar

    obj = {
        "id": "zoom-meeting-789",
        "topic": "No Integration Meeting",
        "host_id": "unknown-host",
        "start_time": "2024-01-15T10:00:00Z",
        "duration": 30,
    }

    await _handle_meeting_ended(obj, mock_db)

    # No meeting row should be created
    mock_db.add.assert_not_called()
    mock_db.commit.assert_not_called()
