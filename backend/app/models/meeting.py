"""Meeting model - represents recorded/scheduled meetings"""
from sqlalchemy import Column, String, Text, Integer, DateTime, ForeignKey, Enum as SQLEnum, Index
from sqlalchemy.orm import relationship
from datetime import datetime
import uuid
import enum

from app.database import Base


class MeetingStatus(str, enum.Enum):
    """Meeting processing status"""
    AWAITING_UPLOAD = "awaiting_upload"  # Created from Zoom webhook, waiting for file
    SCHEDULED = "scheduled"
    PROCESSING = "processing"
    TRANSCRIBED = "transcribed"
    COMPLETED = "completed"
    FAILED = "failed"


class Meeting(Base):
    """Meeting model"""
    __tablename__ = "meetings"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    title = Column(String(500), nullable=False)
    scheduled_at = Column(DateTime, nullable=True)
    duration_minutes = Column(Integer, nullable=True)
    recording_url = Column(String(1000), nullable=True)  # S3 URL or Cloudinary URL
    transcript = Column(Text, nullable=True)
    diarized_transcript = Column(Text, nullable=True)  # JSON: [{speaker, start, end, text, context_type}]
    speaker_names = Column(Text, nullable=True)         # JSON: {"Speaker A": "Alice", "Speaker B": "Bob"}
    summary = Column(Text, nullable=True)
    status = Column(SQLEnum(MeetingStatus), default=MeetingStatus.SCHEDULED, nullable=False, index=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Zoom integration fields
    zoom_meeting_id = Column(String(100), nullable=True, index=True)
    zoom_recording_id = Column(String(100), nullable=True)  # dedup guard

    # Google Calendar integration fields
    calendar_event_id = Column(String(500), nullable=True)
    google_meet_link = Column(String(500), nullable=True)

    # Foreign Keys
    team_id = Column(String(36), ForeignKey("teams.id", ondelete="CASCADE"), nullable=False)
    created_by_id = Column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    # Relationships
    team = relationship("Team", back_populates="meetings")
    creator = relationship("User", back_populates="meetings_created")
    action_items = relationship("ActionItem", back_populates="meeting", cascade="all, delete-orphan")

    # Indexes
    __table_args__ = (
        Index('idx_meeting_team_status', 'team_id', 'status'),
    )

    def __repr__(self):
        return f"<Meeting {self.title[:50]}>"
