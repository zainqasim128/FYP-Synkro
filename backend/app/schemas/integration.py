"""Pydantic schemas for Integration model"""
from pydantic import BaseModel, Field
from datetime import datetime
from typing import Optional, Dict, Any


class IntegrationResponse(BaseModel):
    """Schema for integration response"""
    id: str
    platform: str
    is_active: bool
    last_synced_at: Optional[datetime] = None
    created_at: datetime
    metadata: Dict[str, Any] = Field(default_factory=dict, alias="platform_metadata")

    model_config = {"from_attributes": True, "populate_by_name": True}


class IntegrationSyncResponse(BaseModel):
    """Schema for sync trigger response"""
    message: str
    integration_id: str
