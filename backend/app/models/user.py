"""User model - represents a team member"""
from sqlalchemy import Column, String, Boolean, DateTime, ForeignKey, Enum as SQLEnum
from sqlalchemy.orm import relationship
from datetime import datetime
import uuid
import enum

from app.database import Base


class UserRole(str, enum.Enum):
    """User role hierarchy within a software house"""
    ADMIN = "admin"                    # Full access: upload meetings, manage users
    PROJECT_MANAGER = "project_manager"  # Can assign tasks, view all meetings
    TEAM_LEAD = "team_lead"            # Can assign tasks, view team meetings
    SENIOR_DEVELOPER = "senior_developer"  # Can integrate email, manage own tasks
    DEVELOPER = "developer"            # Standard access, email integration
    INTERN = "intern"                  # Limited access, email integration


class User(Base):
    """User model"""
    __tablename__ = "users"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    email = Column(String(255), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=False)
    full_name = Column(String(255), nullable=False)
    avatar_url = Column(String(500), nullable=True)
    timezone = Column(String(50), default="UTC")
    role = Column(SQLEnum(UserRole, values_callable=lambda x: [e.value for e in x]), default=UserRole.DEVELOPER, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    is_verified = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Password reset fields
    password_reset_token = Column(String(255), nullable=True)
    password_reset_expires = Column(DateTime, nullable=True)

    # Foreign Keys
    team_id = Column(String(36), ForeignKey("teams.id", ondelete="CASCADE"), nullable=True)

    # Relationships
    team = relationship("Team", back_populates="members")
    created_tasks = relationship(
        "Task",
        foreign_keys="Task.created_by_id",
        back_populates="creator"
    )
    assigned_tasks = relationship(
        "Task",
        foreign_keys="Task.assignee_id",
        back_populates="assignee"
    )
    integrations = relationship("Integration", back_populates="user", cascade="all, delete-orphan")
    meetings_created = relationship("Meeting", back_populates="creator")
    calendar_preferences = relationship("CalendarPreferences", back_populates="user", uselist=False, cascade="all, delete-orphan")

    @property
    def is_admin(self) -> bool:
        return self.role == UserRole.ADMIN

    @property
    def can_upload_meetings(self) -> bool:
        """Only admin can upload meetings"""
        return self.role == UserRole.ADMIN

    @property
    def can_manage_users(self) -> bool:
        """Only admin can manage users"""
        return self.role == UserRole.ADMIN

    def __repr__(self):
        return f"<User {self.email}>"
