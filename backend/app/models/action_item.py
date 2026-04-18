"""ActionItem model - extracted action items from meetings/messages"""
from sqlalchemy import Column, String, Text, Float, DateTime, ForeignKey, Enum as SQLEnum
from sqlalchemy.orm import relationship
from datetime import datetime
import uuid
import enum

from app.database import Base


class ActionItemStatus(str, enum.Enum):
    """Action item processing status"""
    PENDING = "pending"
    CONVERTED = "converted"
    REJECTED = "rejected"


class ActionItem(Base):
    """Action Item model - extracted from meetings or messages"""
    __tablename__ = "action_items"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    description = Column(Text, nullable=False)
    assignee_mentioned = Column(String(255), nullable=True)  # Name/email mentioned
    deadline_mentioned = Column(DateTime, nullable=True)  # Extracted deadline
    confidence_score = Column(Float, default=0.0)  # AI confidence (0-1)
    status = Column(SQLEnum(ActionItemStatus), default=ActionItemStatus.PENDING, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    # Speaker diarization fields
    speaker_label = Column(String(50), nullable=True)    # e.g. "Speaker A" — who said it
    assigned_by = Column(String(255), nullable=True)     # speaker who assigned the task
    context_type = Column(String(30), nullable=True)     # task_assignment|warning|completion|progress|question|decision

    # Foreign Keys
    meeting_id = Column(String(36), ForeignKey("meetings.id", ondelete="CASCADE"), nullable=True)
    message_id = Column(String(36), ForeignKey("messages.id", ondelete="CASCADE"), nullable=True)
    task_id = Column(String(36), ForeignKey("tasks.id", ondelete="SET NULL"), nullable=True)

    # Relationships
    meeting = relationship("Meeting", back_populates="action_items")
    message = relationship("Message", back_populates="action_items")

    def __repr__(self):
        return f"<ActionItem {self.description[:50]}>"
