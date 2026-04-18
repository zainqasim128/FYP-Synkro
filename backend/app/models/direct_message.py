"""DirectMessage model - native in-app DMs between team members"""
from sqlalchemy import Column, String, DateTime, ForeignKey, Text, Boolean
from sqlalchemy.orm import relationship
from datetime import datetime
import uuid

from app.database import Base


class DirectMessage(Base):
    __tablename__ = "direct_messages"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    sender_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    recipient_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    content = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    read_at = Column(DateTime, nullable=True)
    # Slack message timestamp used for deduplication when syncing from Slack
    slack_ts = Column(String(32), nullable=True, index=True)

    sender = relationship("User", foreign_keys=[sender_id])
    recipient = relationship("User", foreign_keys=[recipient_id])
