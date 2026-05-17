"""Notification helper — adds a Notification row to the session. Caller must commit."""
import logging
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.notification import Notification, NotificationType

logger = logging.getLogger(__name__)


async def create_notification(
    db: AsyncSession,
    user_id: str,
    type: NotificationType,
    title: str,
    body: str | None = None,
    link: str | None = None,
) -> Notification:
    notif = Notification(user_id=user_id, type=type, title=title, body=body, link=link)
    db.add(notif)
    return notif
