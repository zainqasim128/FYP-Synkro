"""Pydantic schemas for Task model"""
from pydantic import BaseModel, Field, field_validator
from datetime import datetime, timezone
from typing import Optional


class TaskBase(BaseModel):
    """Base task schema"""
    title: str = Field(..., min_length=1, max_length=500)
    description: Optional[str] = None
    status: str = Field(default="todo")
    priority: str = Field(default="medium")
    due_date: Optional[datetime] = None
    estimated_hours: Optional[int] = Field(None, ge=0)

    @field_validator("due_date", mode="before")
    @classmethod
    def strip_timezone(cls, v):
        """Strip timezone so it matches TIMESTAMP WITHOUT TIME ZONE columns."""
        if v is None:
            return v
        if isinstance(v, str):
            # Parse ISO string and strip timezone
            v = datetime.fromisoformat(v.replace("Z", "+00:00"))
        if isinstance(v, datetime) and v.tzinfo is not None:
            return v.replace(tzinfo=None)
        return v


class TaskCreate(TaskBase):
    """Schema for creating a new task"""
    assignee_id: Optional[str] = None
    source_type: str = Field(default="manual")
    source_id: Optional[str] = None


class TaskUpdate(BaseModel):
    """Schema for updating a task"""
    title: Optional[str] = Field(None, min_length=1, max_length=500)
    description: Optional[str] = None
    status: Optional[str] = None
    priority: Optional[str] = None
    assignee_id: Optional[str] = None
    due_date: Optional[datetime] = None
    estimated_hours: Optional[int] = Field(None, ge=0)

    @field_validator("due_date", mode="before")
    @classmethod
    def strip_timezone(cls, v):
        if v is None:
            return v
        if isinstance(v, str):
            v = datetime.fromisoformat(v.replace("Z", "+00:00"))
        if isinstance(v, datetime) and v.tzinfo is not None:
            return v.replace(tzinfo=None)
        return v


class TaskResponse(TaskBase):
    """Schema for task response"""
    id: str
    assignee_id: Optional[str] = None
    created_by_id: Optional[str] = None
    team_id: str
    source_type: str
    source_id: Optional[str] = None
    external_id: Optional[str] = None
    created_at: datetime
    updated_at: Optional[datetime] = None

    # Optional nested objects
    assignee: Optional[dict] = None
    creator: Optional[dict] = None

    model_config = {"from_attributes": True}


class TaskStats(BaseModel):
    """Schema for task statistics"""
    total: int
    todo: int
    in_progress: int
    done: int
    blocked: int
    overdue: int
    completion_rate: float
