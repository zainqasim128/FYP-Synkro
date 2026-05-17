"""Task model - represents a work item"""
from sqlalchemy import Column, String, Text, Integer, Boolean, DateTime, ForeignKey, Enum as SQLEnum, Index
from sqlalchemy.orm import relationship
from datetime import datetime
import uuid
import enum

from app.database import Base


class TaskStatus(str, enum.Enum):
    """Task status"""
    TODO = "todo"
    IN_PROGRESS = "in_progress"
    DONE = "done"
    BLOCKED = "blocked"


class TaskPriority(str, enum.Enum):
    """Task priority"""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    URGENT = "urgent"


class TaskSourceType(str, enum.Enum):
    """Where the task originated from"""
    MANUAL = "manual"
    MEETING = "meeting"
    MESSAGE = "message"
    AI = "ai"


class Task(Base):
    """Task model"""
    __tablename__ = "tasks"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    title = Column(String(500), nullable=False)
    description = Column(Text, nullable=True)
    status = Column(SQLEnum(TaskStatus), default=TaskStatus.TODO, nullable=False)
    priority = Column(SQLEnum(TaskPriority), default=TaskPriority.MEDIUM, nullable=False)
    due_date = Column(DateTime, nullable=True)
    estimated_hours = Column(Integer, nullable=True)
    source_type = Column(SQLEnum(TaskSourceType), default=TaskSourceType.MANUAL, nullable=False)
    source_id = Column(String(36), nullable=True)  # ID of meeting/message/etc
    external_id = Column(String(255), nullable=True)  # ID from external system (Jira, etc)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Foreign Keys
    assignee_id = Column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    created_by_id = Column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    team_id = Column(String(36), ForeignKey("teams.id", ondelete="CASCADE"), nullable=False)

    # Relationships
    assignee = relationship("User", foreign_keys=[assignee_id], back_populates="assigned_tasks")
    creator = relationship("User", foreign_keys=[created_by_id], back_populates="created_tasks")
    team = relationship("Team", back_populates="tasks")

    # Google Calendar sync
    calendar_event_id = Column(String(500), nullable=True)
    calendar_synced_at = Column(DateTime, nullable=True)

    # Google Meet auto-generation
    is_meeting_task = Column(Boolean, default=False, nullable=False, server_default="false")
    google_meet_link = Column(String(500), nullable=True)
    meeting_scheduled_at = Column(DateTime, nullable=True)
    meeting_duration_minutes = Column(Integer, default=60, nullable=False, server_default="60")

    # Jira bi-directional sync
    jira_synced_at = Column(DateTime, nullable=True)
    jira_sync_error = Column(Text, nullable=True)

    # Comments (Synkro + Jira-synced)
    comments = relationship("TaskComment", back_populates="task", cascade="all, delete-orphan", order_by="TaskComment.created_at")

    # Indexes for common queries
    __table_args__ = (
        Index('idx_task_status_assignee', 'status', 'assignee_id'),
        Index('idx_task_team_status', 'team_id', 'status'),
    )

    def __repr__(self):
        return f"<Task {self.title[:50]}>"
