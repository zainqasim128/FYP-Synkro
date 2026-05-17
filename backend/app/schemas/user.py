"""Pydantic schemas for User model"""
from pydantic import BaseModel, EmailStr, Field
from datetime import datetime
from typing import Optional


class UserBase(BaseModel):
    """Base user schema"""
    email: EmailStr
    full_name: str = Field(..., min_length=1, max_length=255)


class UserCreate(UserBase):
    """Schema for creating a new user"""
    password: str = Field(..., min_length=8, max_length=100)
    team_id: Optional[str] = None
    role: Optional[str] = "developer"
    invite_token: Optional[str] = None  # when set, overrides team and role from invitation


class UserLogin(BaseModel):
    """Schema for user login"""
    email: EmailStr
    password: str


class UserUpdate(BaseModel):
    """Schema for updating user"""
    full_name: Optional[str] = Field(None, min_length=1, max_length=255)
    avatar_url: Optional[str] = None
    timezone: Optional[str] = None


class UserResponse(BaseModel):
    """Schema for user response (without password)"""
    id: str
    email: str
    full_name: str
    avatar_url: Optional[str] = None
    timezone: str
    role: str
    is_active: bool
    is_verified: bool
    team_id: Optional[str] = None
    created_at: datetime
    updated_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class Token(BaseModel):
    """Schema for token response"""
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class TokenRefresh(BaseModel):
    """Schema for token refresh request"""
    refresh_token: str


class TokenPayload(BaseModel):
    """Schema for decoded token payload"""
    sub: Optional[str] = None
    exp: Optional[int] = None
    type: Optional[str] = None


class ForgotPasswordRequest(BaseModel):
    """Schema for forgot password request"""
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    """Schema for password reset"""
    token: str
    new_password: str = Field(..., min_length=8, max_length=100)


class InviteCreateRequest(BaseModel):
    """Schema for creating a team invitation"""
    email: Optional[str] = None
    role: str = "developer"
    expires_in_days: int = Field(default=7, ge=1, le=30)


class InviteValidateResponse(BaseModel):
    """Public info returned when validating an invite token"""
    valid: bool
    team_name: Optional[str] = None
    role: Optional[str] = None
    email: Optional[str] = None
    expires_at: Optional[datetime] = None


class InviteResponse(BaseModel):
    """Schema for an invitation record"""
    id: str
    email: Optional[str] = None
    role: str
    token: str
    expires_at: datetime
    used_at: Optional[datetime] = None
    created_at: datetime
    invited_by_name: Optional[str] = None

    model_config = {"from_attributes": True}
