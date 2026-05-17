"""TaskComment model — stores comments on tasks with Jira sync tracking."""
from datetime import datetime
import enum
import uuid

from sqlalchemy import Column, String, Text, DateTime, ForeignKey, Enum as SQLEnum
from sqlalchemy.orm import relationship

from app.database import Base


class CommentSource(str, enum.Enum):
    SYNKRO = "synkro"
    JIRA = "jira"


class TaskComment(Base):
    __tablename__ = "task_comments"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    task_id = Column(String(36), ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False, index=True)
    body = Column(Text, nullable=False)
    author_id = Column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    # Jira comment ID — set when comment was created in / synced from Jira
    jira_comment_id = Column(String(64), nullable=True, unique=True)
    # Display name from Jira for inbound comments (author_id will be null)
    jira_author_name = Column(String(255), nullable=True)
    source = Column(SQLEnum(CommentSource), default=CommentSource.SYNKRO, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    task = relationship("Task", back_populates="comments")
    author = relationship("User", foreign_keys=[author_id])

    def __repr__(self):
        return f"<TaskComment {self.id[:8]} task={self.task_id[:8]}>"
