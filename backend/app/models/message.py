"""Message model - messages from integrations (Gmail, Slack, etc)"""
from sqlalchemy import Column, String, Text, Boolean, DateTime, ForeignKey, Enum as SQLEnum, JSON
from sqlalchemy.orm import relationship
from datetime import datetime
import uuid
import enum

from app.database import Base


class MessageIntent(str, enum.Enum):
    """AI-classified intent of the message"""
    TASK_REQUEST = "task_request"
    BLOCKER = "blocker"
    QUESTION = "question"
    INFORMATION = "information"
    URGENT_ISSUE = "urgent_issue"
    CASUAL = "casual"


class Message(Base):
    """Message model - stores messages from email/Slack/etc"""
    __tablename__ = "messages"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    external_id = Column(String(255), unique=True, nullable=False)  # Platform-specific ID
    platform = Column(String(50), nullable=False)  # gmail, slack, etc
    sender_email = Column(String(255), nullable=True)
    sender_name = Column(String(255), nullable=True)
    content = Column(Text, nullable=False)
    timestamp = Column(DateTime, nullable=False)
    thread_id = Column(String(255), nullable=True)  # For threading
    channel_id = Column(String(255), nullable=True)   # Slack channel/DM channel ID
    channel_type = Column(String(50), nullable=True)  # "channel", "im", "mpim", etc.
    processed = Column(Boolean, default=False, nullable=False)
    intent = Column(SQLEnum(MessageIntent), nullable=True)
    entities = Column(JSON, default=dict)  # Extracted entities
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    # Foreign Keys
    user_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)

    # Relationships
    action_items = relationship("ActionItem", back_populates="message", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<Message {self.platform} from {self.sender_email}>"
