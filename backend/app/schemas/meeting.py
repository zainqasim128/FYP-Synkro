"""Pydantic schemas for Meeting model"""
from pydantic import BaseModel, Field, field_serializer
from datetime import datetime
from typing import Optional, List


class ActionItemBase(BaseModel):
    """Base action item schema"""
    description: str
    assignee_mentioned: Optional[str] = None
    deadline_mentioned: Optional[datetime] = None
    confidence_score: float = Field(ge=0.0, le=1.0)


class ActionItemResponse(ActionItemBase):
    """Schema for action item response"""
    id: str
    status: str
    task_id: Optional[str] = None
    meeting_id: Optional[str] = None
    created_at: datetime
    # Speaker diarization fields
    speaker_label: Optional[str] = None
    assigned_by: Optional[str] = None
    context_type: Optional[str] = None

    model_config = {"from_attributes": True}

    @field_serializer('created_at', 'deadline_mentioned')
    def serialize_datetime(self, dt: Optional[datetime], _info):
        """Serialize datetime to ISO format with UTC timezone"""
        if dt is None:
            return None
        return dt.isoformat() + 'Z' if not dt.isoformat().endswith('Z') else dt.isoformat()


class MeetingBase(BaseModel):
    """Base meeting schema"""
    title: str = Field(..., min_length=1, max_length=500)
    scheduled_at: Optional[datetime] = None
    duration_minutes: Optional[int] = Field(None, ge=0)


class MeetingCreate(MeetingBase):
    """Schema for creating a meeting"""
    pass


class MeetingUpdate(BaseModel):
    """Schema for updating a meeting"""
    title: Optional[str] = Field(None, min_length=1, max_length=500)
    scheduled_at: Optional[datetime] = None
    duration_minutes: Optional[int] = Field(None, ge=0)


class SpeakerNamesUpdate(BaseModel):
    """Schema for updating speaker display names"""
    speaker_names: dict[str, str]


class MeetingResponse(MeetingBase):
    """Schema for meeting response"""
    id: str
    recording_url: Optional[str] = None
    transcript: Optional[str] = None
    diarized_transcript: Optional[str] = None  # JSON string of speaker-labeled segments
    speaker_names: Optional[str] = None         # JSON string: {"Speaker A": "Alice"}
    summary: Optional[str] = None
    status: str
    team_id: str
    created_by_id: Optional[str] = None
    created_at: datetime
    updated_at: Optional[datetime] = None
    action_items: List[ActionItemResponse] = []
    calendar_event_id: Optional[str] = None
    google_meet_link: Optional[str] = None

    model_config = {"from_attributes": True}

    @field_serializer('created_at', 'updated_at', 'scheduled_at')
    def serialize_datetime(self, dt: Optional[datetime], _info):
        """Serialize datetime to ISO format with UTC timezone"""
        if dt is None:
            return None
        # Ensure it's treated as UTC and format with Z suffix
        return dt.isoformat() + 'Z' if not dt.isoformat().endswith('Z') else dt.isoformat()


class MeetingUploadResponse(BaseModel):
    """Schema for meeting upload response"""
    id: str
    title: str
    status: str
    message: str
