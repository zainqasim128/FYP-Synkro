"""Integration model - third-party service connections"""
from sqlalchemy import Column, String, Boolean, DateTime, ForeignKey, Enum as SQLEnum, JSON
from sqlalchemy.orm import relationship
from datetime import datetime
import uuid
import enum

from app.database import Base


class IntegrationPlatform(str, enum.Enum):
    """Supported integration platforms"""
    GMAIL = "gmail"
    SLACK = "slack"
    GOOGLE_CALENDAR = "google_calendar"
    JIRA = "jira"
    MICROSOFT_TEAMS = "microsoft_teams"


class Integration(Base):
    """Integration model - stores OAuth tokens and connection info"""
    __tablename__ = "integrations"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    platform = Column(SQLEnum(IntegrationPlatform), nullable=False)
    access_token = Column(String(1000), nullable=False)  # Should be encrypted in production
    refresh_token = Column(String(1000), nullable=True)
    expires_at = Column(DateTime, nullable=True)
    scope = Column(String(500), nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)
    platform_metadata = Column(JSON, default=dict)  # Platform-specific data
    last_synced_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Foreign Keys
    user_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)

    # Relationships
    user = relationship("User", back_populates="integrations")

    def __repr__(self):
        return f"<Integration {self.platform} for user {self.user_id}>"
