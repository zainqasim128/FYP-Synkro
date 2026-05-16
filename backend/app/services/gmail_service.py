"""
Gmail IMAP service - fetch and parse emails using App Password.
No Google Cloud Console or OAuth needed.
"""
import imaplib
import email
from email.header import decode_header
from email.utils import parsedate_to_datetime
from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta
import logging
import re

from app.config import settings

logger = logging.getLogger(__name__)


def _decode_header_value(value: str) -> str:
    """Decode an email header value."""
    if not value:
        return ""
    decoded_parts = decode_header(value)
    result = []
    for part, charset in decoded_parts:
        if isinstance(part, bytes):
            result.append(part.decode(charset or "utf-8", errors="replace"))
        else:
            result.append(part)
    return " ".join(result)


def _get_email_body(msg: email.message.Message) -> str:
    """Extract plain text body from email message."""
    body = ""

    if msg.is_multipart():
        for part in msg.walk():
            content_type = part.get_content_type()
            content_disposition = str(part.get("Content-Disposition", ""))

            # Skip attachments
            if "attachment" in content_disposition:
                continue

            if content_type == "text/plain":
                try:
                    payload = part.get_payload(decode=True)
                    charset = part.get_content_charset() or "utf-8"
                    body = payload.decode(charset, errors="replace")
                    break
                except Exception:
                    continue
            elif content_type == "text/html" and not body:
                try:
                    payload = part.get_payload(decode=True)
                    charset = part.get_content_charset() or "utf-8"
                    html = payload.decode(charset, errors="replace")
                    # Strip HTML tags for plain text
                    body = re.sub(r"<[^>]+>", " ", html)
                    body = re.sub(r"\s+", " ", body).strip()
                except Exception:
                    continue
    else:
        try:
            payload = msg.get_payload(decode=True)
            charset = msg.get_content_charset() or "utf-8"
            body = payload.decode(charset, errors="replace")
        except Exception:
            body = ""

    return body.strip()


def test_connection(email_addr: str, app_password: str) -> Dict[str, Any]:
    """Test IMAP connection with provided credentials."""
    app_password = app_password.replace(" ", "")
    try:
        mail = imaplib.IMAP4_SSL("imap.gmail.com")
        mail.login(email_addr, app_password)
        mail.select("INBOX", readonly=True)

        # Get mailbox status
        status, data = mail.status("INBOX", "(MESSAGES UNSEEN)")
        messages_info = data[0].decode() if data[0] else ""

        mail.logout()

        return {
            "success": True,
            "email": email_addr,
            "info": messages_info,
        }
    except imaplib.IMAP4.error as e:
        return {"success": False, "error": f"IMAP login failed: {str(e)}"}
    except Exception as e:
        return {"success": False, "error": str(e)}


def fetch_emails(
    email_addr: str,
    app_password: str,
    folder: str = "INBOX",
    limit: int = 20,
    since_days: int = 7,
) -> List[Dict[str, Any]]:
    """
    Fetch recent emails via IMAP.

    Args:
        email_addr: Gmail address
        app_password: App Password (16 chars, no spaces)
        folder: Mailbox folder (INBOX, SENT, etc.)
        limit: Max emails to fetch
        since_days: Fetch emails from last N days

    Returns:
        List of parsed email dicts
    """
    emails = []
    app_password = app_password.replace(" ", "")

    try:
        mail = imaplib.IMAP4_SSL("imap.gmail.com")
        mail.login(email_addr, app_password)
        mail.select(folder, readonly=True)

        # Search for recent emails
        since_date = (datetime.now() - timedelta(days=since_days)).strftime("%d-%b-%Y")
        status, message_ids = mail.search(None, f'(SINCE "{since_date}")')

        if status != "OK" or not message_ids[0]:
            mail.logout()
            return []

        # Get latest N message IDs
        id_list = message_ids[0].split()
        id_list = id_list[-limit:]  # Take the most recent
        id_list.reverse()  # Newest first

        for msg_id in id_list:
            try:
                status, msg_data = mail.fetch(msg_id, "(RFC822)")
                if status != "OK":
                    continue

                raw_email = msg_data[0][1]
                msg = email.message_from_bytes(raw_email)

                # Parse headers
                subject = _decode_header_value(msg.get("Subject", ""))
                sender = _decode_header_value(msg.get("From", ""))
                to = _decode_header_value(msg.get("To", ""))
                date_str = msg.get("Date", "")
                # Strip whitespace/newlines from Message-ID (IMAP headers can be folded)
                message_id = (msg.get("Message-ID", "") or "").strip()

                # Parse date
                received_at = None
                if date_str:
                    try:
                        received_at = parsedate_to_datetime(date_str).isoformat()
                    except Exception:
                        received_at = None

                # Get body
                body = _get_email_body(msg)
                body_preview = body[:200] + "..." if len(body) > 200 else body

                # Check flags
                status2, flags_data = mail.fetch(msg_id, "(FLAGS)")
                flags_str = flags_data[0].decode() if flags_data[0] else ""
                is_read = "\\Seen" in flags_str
                is_flagged = "\\Flagged" in flags_str

                emails.append({
                    "gmail_message_id": message_id,
                    "subject": subject,
                    "sender": sender,
                    "to": to,
                    "body_preview": body_preview,
                    "body": body,
                    "received_at": received_at,
                    "is_read": is_read,
                    "is_flagged": is_flagged,
                })

            except Exception as e:
                logger.warning(f"Failed to parse email {msg_id}: {e}")
                continue

        mail.logout()

    except imaplib.IMAP4.error as e:
        logger.error(f"IMAP error: {e}")
        raise Exception(f"Gmail connection failed: {str(e)}")
    except Exception as e:
        logger.error(f"Email fetch error: {e}")
        raise

    return emails


def mark_email_as_read_in_gmail(email_addr: str, app_password: str, gmail_message_id: str) -> bool:
    """
    Mark an email as read in Gmail by adding the \\Seen flag via IMAP.
    Returns True if successful, False otherwise.
    """
    app_password = app_password.replace(" ", "")
    try:
        mail = imaplib.IMAP4_SSL("imap.gmail.com")
        mail.login(email_addr, app_password)

        folders_to_try = ["INBOX", "[Gmail]/All Mail"]
        marked = False

        for folder in folders_to_try:
            try:
                status, _ = mail.select(folder)
                if status != "OK":
                    continue
                safe_id = gmail_message_id.replace('"', '\\"')
                status, data = mail.search(None, f'HEADER Message-ID "{safe_id}"')
                if status != "OK" or not data[0]:
                    continue
                msg_ids = data[0].split()
                if not msg_ids:
                    continue
                for msg_id in msg_ids:
                    mail.store(msg_id, "+FLAGS", "\\Seen")
                marked = True
                break
            except Exception:
                continue

        mail.logout()
        return marked

    except imaplib.IMAP4.error as e:
        logger.error(f"IMAP error while marking email as read: {e}")
        return False
    except Exception as e:
        logger.error(f"Failed to mark email as read in Gmail: {e}")
        return False


def delete_email_from_gmail(email_addr: str, app_password: str, gmail_message_id: str) -> bool:
    """
    Delete an email from Gmail by its Message-ID header.
    Gmail moves the message to Trash on EXPUNGE.

    Returns True if deleted, False if not found or on error.
    """
    app_password = app_password.replace(" ", "")
    try:
        mail = imaplib.IMAP4_SSL("imap.gmail.com")
        mail.login(email_addr, app_password)

        # Search across INBOX and All Mail so we find it regardless of folder
        folders_to_try = ["INBOX", "[Gmail]/All Mail"]
        deleted = False

        for folder in folders_to_try:
            try:
                status, _ = mail.select(folder)
                if status != "OK":
                    continue

                # Escape any quotes in the message-id
                safe_id = gmail_message_id.replace('"', '\\"')
                status, data = mail.search(None, f'HEADER Message-ID "{safe_id}"')
                if status != "OK" or not data[0]:
                    continue

                msg_ids = data[0].split()
                if not msg_ids:
                    continue

                for msg_id in msg_ids:
                    mail.store(msg_id, "+FLAGS", "\\Deleted")
                mail.expunge()
                deleted = True
                break
            except Exception:
                continue

        mail.logout()
        return deleted

    except imaplib.IMAP4.error as e:
        logger.error(f"IMAP error while deleting email: {e}")
        return False
    except Exception as e:
        logger.error(f"Failed to delete email from Gmail: {e}")
        return False
