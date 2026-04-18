"""
Database models package.
Import all models here for Alembic to detect them.
"""
from app.models.team import Team, TeamPlan
from app.models.user import User, UserRole
from app.models.task import Task, TaskStatus, TaskPriority, TaskSourceType
from app.models.meeting import Meeting, MeetingStatus
from app.models.action_item import ActionItem, ActionItemStatus
from app.models.integration import Integration, IntegrationPlatform
from app.models.message import Message, MessageIntent
from app.models.email import Email
from app.models.direct_message import DirectMessage

__all__ = [
    "Team",
    "TeamPlan",
    "User",
    "UserRole",
    "Task",
    "TaskStatus",
    "TaskPriority",
    "TaskSourceType",
    "Meeting",
    "MeetingStatus",
    "ActionItem",
    "ActionItemStatus",
    "Integration",
    "IntegrationPlatform",
    "Message",
    "MessageIntent",
    "Email",
    "DirectMessage",
]
