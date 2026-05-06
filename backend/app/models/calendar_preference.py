"""CalendarPreferences model — per-user Google Calendar sync settings"""
from sqlalchemy import Column, String, Boolean, DateTime, JSON, ForeignKey
from sqlalchemy.orm import relationship
from datetime import datetime
import uuid

from app.database import Base


class CalendarPreferences(Base):
    __tablename__ = "calendar_preferences"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    auto_sync_tasks = Column(Boolean, default=True, nullable=False)
    auto_sync_meetings = Column(Boolean, default=True, nullable=False)
    auto_sync_actions = Column(Boolean, default=False, nullable=False)
    # Stored as JSON arrays of integer minutes
    reminder_urgent_minutes = Column(JSON, default=lambda: [2880, 120])
    reminder_high_minutes = Column(JSON, default=lambda: [1440, 120])
    reminder_medium_minutes = Column(JSON, default=lambda: [1440, 60])
    reminder_low_minutes = Column(JSON, default=lambda: [360])
    daily_digest_enabled = Column(Boolean, default=False, nullable=False)
    daily_digest_time = Column(String(5), default="08:00")
    auto_reschedule_overdue = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    user = relationship("User", back_populates="calendar_preferences")
