"""Authentication endpoints - register, login, refresh, me, forgot/reset password"""
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
import secrets
from datetime import datetime, timedelta

from app.database import get_db
from app.models import User, Team
from app.models.user import UserRole
from app.schemas.user import (
    UserCreate, UserUpdate, UserResponse, Token, TokenRefresh,
    ForgotPasswordRequest, ResetPasswordRequest,
    InviteCreateRequest, InviteValidateResponse, InviteResponse
)
from app.utils.security import (
    get_password_hash,
    verify_password,
    create_access_token,
    create_refresh_token,
    verify_token
)
from app.dependencies import get_current_user, get_current_admin_user
from app.models.team_invitation import TeamInvitation

router = APIRouter(prefix="/api/auth", tags=["Authentication"])

# Valid roles that can be chosen during registration
VALID_REGISTRATION_ROLES = {
    "admin", "project_manager", "team_lead",
    "senior_developer", "developer", "intern"
}


@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def register(user_data: UserCreate, db: AsyncSession = Depends(get_db)):
    """
    Register a new user account.

    - **email**: Valid email address (must be unique)
    - **password**: Password (minimum 8 characters)
    - **full_name**: User's full name
    - **role**: User role (admin, project_manager, team_lead, senior_developer, developer, intern)
    - **invite_token**: Optional invite token — joins the inviting admin's team and uses the invited role
    """
    # Check if email already exists
    result = await db.execute(select(User).where(User.email == user_data.email))
    existing_user = result.scalar_one_or_none()

    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already registered"
        )

    # --- Invite token path ---
    invitation = None
    if user_data.invite_token:
        result = await db.execute(
            select(TeamInvitation).where(TeamInvitation.token == user_data.invite_token)
        )
        invitation = result.scalar_one_or_none()
        if not invitation:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid invite token")
        if invitation.used_at:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invite token has already been used")
        if invitation.expires_at < datetime.utcnow():
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invite token has expired")
        if invitation.email and invitation.email.lower() != user_data.email.lower():
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="This invite was sent to a different email address")

    # Validate role
    role_str = (user_data.role or "developer").lower()
    if role_str not in VALID_REGISTRATION_ROLES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid role. Must be one of: {', '.join(sorted(VALID_REGISTRATION_ROLES))}"
        )

    # Map role string to UserRole enum
    role_map = {
        "admin": UserRole.ADMIN,
        "project_manager": UserRole.PROJECT_MANAGER,
        "team_lead": UserRole.TEAM_LEAD,
        "senior_developer": UserRole.SENIOR_DEVELOPER,
        "developer": UserRole.DEVELOPER,
        "intern": UserRole.INTERN,
    }

    if invitation:
        # Invitation overrides the requested role and team
        user_role = invitation.role
        team_id = invitation.team_id
    else:
        user_role = role_map[role_str]

        # Enforce single admin: only one admin can exist in the system
        if user_role == UserRole.ADMIN:
            result = await db.execute(select(User).where(User.role == UserRole.ADMIN).limit(1))
            existing_admin = result.scalar_one_or_none()
            if existing_admin:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="An administrator already exists. Please choose a different role to register."
                )

        # Determine team assignment
        team_id = user_data.team_id
        if team_id:
            # Validate the provided team_id
            result = await db.execute(select(Team).where(Team.id == team_id))
            team = result.scalar_one_or_none()
            if not team:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Team not found"
                )
        elif user_role != UserRole.ADMIN:
            # Non-admin: join the admin's team if one exists, otherwise create a new team
            result = await db.execute(select(User).where(User.role == UserRole.ADMIN).limit(1))
            admin_user = result.scalar_one_or_none()
            if admin_user and admin_user.team_id:
                team_id = admin_user.team_id
            else:
                # No admin yet, create a personal team
                from app.models import TeamPlan
                import uuid
                new_team = Team(
                    id=str(uuid.uuid4()),
                    name=f"{user_data.full_name}'s Team",
                    plan=TeamPlan.FREE,
                    settings={}
                )
                db.add(new_team)
                await db.flush()
                team_id = new_team.id
        else:
            # Admin: create a new team for the organization
            from app.models import TeamPlan
            import uuid
            new_team = Team(
                id=str(uuid.uuid4()),
                name=f"{user_data.full_name}'s Team",
                plan=TeamPlan.FREE,
                settings={}
            )
            db.add(new_team)
            await db.flush()
            team_id = new_team.id

    # Create new user
    hashed_password = get_password_hash(user_data.password)
    new_user = User(
        email=user_data.email,
        password_hash=hashed_password,
        full_name=user_data.full_name,
        team_id=team_id,
        role=user_role,
    )

    db.add(new_user)
    await db.flush()  # get new_user.id before commit

    # Auto-provision Slack integration for every new user (demo mode)
    try:
        import uuid as _uuid
        from app.models import Integration, IntegrationPlatform
        from app.utils.security import encrypt_value
        from app.config import settings as _settings
        _slack_token = _settings.DEMO_SLACK_TOKEN
        if _slack_token:
            _enc = encrypt_value(_slack_token)
            _slack_int = Integration(
                id=str(_uuid.uuid4()),
                user_id=new_user.id,
                platform=IntegrationPlatform.SLACK,
                access_token=_enc,
                is_active=True,
                platform_metadata={
                    "team_id": _settings.DEMO_SLACK_TEAM_ID,
                    "team_name": "Synkro Workspace",
                    "default_channel": "#general",
                },
            )
            db.add(_slack_int)
    except Exception:
        pass  # Never block registration if Slack auto-provision fails

    # Mark invitation as used
    if invitation:
        invitation.used_at = datetime.utcnow()

    await db.commit()
    await db.refresh(new_user)

    return new_user


@router.post("/login", response_model=Token)
async def login(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: AsyncSession = Depends(get_db)
):
    """
    Login with email and password to get access tokens.

    Uses OAuth2PasswordRequestForm:
    - **username**: User's email address
    - **password**: User's password

    Returns:
    - **access_token**: Short-lived token for API access
    - **refresh_token**: Long-lived token to get new access tokens
    """
    # Find user by email (username field contains email)
    result = await db.execute(select(User).where(User.email == form_data.username))
    user = result.scalar_one_or_none()

    # Verify credentials
    if not user or not verify_password(form_data.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User account is inactive"
        )

    # Create tokens
    access_token = create_access_token(data={"sub": user.id})
    refresh_token = create_refresh_token(data={"sub": user.id})

    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer"
    }


@router.post("/refresh", response_model=dict)
async def refresh_token(token_data: TokenRefresh, db: AsyncSession = Depends(get_db)):
    """
    Refresh access token using a valid refresh token.

    - **refresh_token**: Valid refresh token from login

    Returns new access_token.
    """
    # Verify refresh token
    payload = verify_token(token_data.refresh_token, token_type="refresh")

    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid refresh token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token payload"
        )

    # Verify user still exists and is active
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()

    if not user or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or inactive"
        )

    # Create new access token
    access_token = create_access_token(data={"sub": user.id})

    return {
        "access_token": access_token,
        "token_type": "bearer"
    }


@router.get("/me", response_model=UserResponse)
async def get_current_user_info(current_user: User = Depends(get_current_user)):
    """
    Get current authenticated user's information.

    Requires valid access token in Authorization header.
    """
    return current_user


@router.post("/logout")
async def logout():
    """
    Logout endpoint (client-side token discard).

    Since we use stateless JWT tokens, logout is handled client-side
    by discarding the tokens from storage.
    """
    return {"message": "Successfully logged out"}


@router.patch("/me", response_model=UserResponse)
async def update_profile(
    user_update: UserUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Update current user's profile information.

    - **full_name**: Update user's full name
    - **avatar_url**: Update user's avatar URL
    - **timezone**: Update user's timezone
    """
    # Update only provided fields
    update_data = user_update.model_dump(exclude_unset=True)

    for field, value in update_data.items():
        setattr(current_user, field, value)

    await db.commit()
    await db.refresh(current_user)

    return current_user


@router.post("/forgot-password")
async def forgot_password(
    request: ForgotPasswordRequest,
    db: AsyncSession = Depends(get_db)
):
    """
    Request a password reset token.

    - **email**: The email address associated with the account

    Generates a reset token valid for 1 hour.
    Returns the reset token directly (for development; in production, this would be emailed).
    """
    result = await db.execute(select(User).where(User.email == request.email))
    user = result.scalar_one_or_none()

    # Always return success to prevent email enumeration attacks
    if not user:
        return {
            "message": "If this email exists, a reset code has been generated.",
            "reset_token": None
        }

    # Generate secure token
    reset_token = secrets.token_urlsafe(32)
    user.password_reset_token = reset_token
    user.password_reset_expires = datetime.utcnow() + timedelta(hours=1)

    await db.commit()

    # In production: send email with reset link
    # For now: return token directly so it works without email setup
    return {
        "message": "Password reset code generated. Use this code to reset your password.",
        "reset_token": reset_token,
        "expires_in": "1 hour"
    }


@router.post("/reset-password")
async def reset_password(
    request: ResetPasswordRequest,
    db: AsyncSession = Depends(get_db)
):
    """
    Reset password using a valid reset token.

    - **token**: The reset token from forgot-password endpoint
    - **new_password**: New password (minimum 8 characters)
    """
    result = await db.execute(
        select(User).where(User.password_reset_token == request.token)
    )
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired reset token"
        )

    if not user.password_reset_expires or user.password_reset_expires < datetime.utcnow():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Reset token has expired. Please request a new one."
        )

    # Update password
    user.password_hash = get_password_hash(request.new_password)
    user.password_reset_token = None
    user.password_reset_expires = None

    await db.commit()

    return {"message": "Password reset successfully. You can now log in with your new password."}


@router.get("/roles")
async def get_available_roles():
    """
    Get list of available roles for registration.
    """
    return {
        "roles": [
            {"value": "admin", "label": "Admin", "description": "Full system access, can upload meetings and manage users"},
            {"value": "project_manager", "label": "Project Manager", "description": "Can manage projects, assign tasks from meetings"},
            {"value": "team_lead", "label": "Team Lead", "description": "Leads a team, can assign tasks and view meetings"},
            {"value": "senior_developer", "label": "Senior Developer", "description": "Experienced developer with email integration"},
            {"value": "developer", "label": "Developer", "description": "Standard developer access with email integration"},
            {"value": "intern", "label": "Intern", "description": "Limited access, email integration for task assignment"},
        ]
    }


@router.post("/invite", response_model=InviteResponse)
async def create_invite(
    invite_data: InviteCreateRequest,
    current_admin: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """Admin creates a team invitation link. Returns the token to share with the invitee."""
    from app.models import TeamPlan
    import uuid

    role_map = {
        "admin": UserRole.ADMIN,
        "project_manager": UserRole.PROJECT_MANAGER,
        "team_lead": UserRole.TEAM_LEAD,
        "senior_developer": UserRole.SENIOR_DEVELOPER,
        "developer": UserRole.DEVELOPER,
        "intern": UserRole.INTERN,
    }
    if invite_data.role not in role_map:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid role")

    token = secrets.token_urlsafe(48)
    expires_at = datetime.utcnow() + timedelta(days=invite_data.expires_in_days)

    invitation = TeamInvitation(
        id=str(uuid.uuid4()),
        team_id=current_admin.team_id,
        email=invite_data.email,
        role=role_map[invite_data.role],
        token=token,
        invited_by_id=current_admin.id,
        expires_at=expires_at,
    )
    db.add(invitation)
    await db.commit()
    await db.refresh(invitation)

    return InviteResponse(
        id=invitation.id,
        email=invitation.email,
        role=invitation.role.value if hasattr(invitation.role, "value") else invitation.role,
        token=invitation.token,
        expires_at=invitation.expires_at,
        used_at=invitation.used_at,
        created_at=invitation.created_at,
        invited_by_name=current_admin.full_name,
    )


@router.get("/invite/validate")
async def validate_invite(token: str, db: AsyncSession = Depends(get_db)):
    """Public endpoint: validate an invite token and return team name + role."""
    result = await db.execute(
        select(TeamInvitation).where(TeamInvitation.token == token)
    )
    invitation = result.scalar_one_or_none()

    if not invitation:
        return InviteValidateResponse(valid=False)
    if invitation.used_at:
        return InviteValidateResponse(valid=False)
    if invitation.expires_at < datetime.utcnow():
        return InviteValidateResponse(valid=False)

    result = await db.execute(select(Team).where(Team.id == invitation.team_id))
    team = result.scalar_one_or_none()

    role_val = invitation.role.value if hasattr(invitation.role, "value") else str(invitation.role)
    return InviteValidateResponse(
        valid=True,
        team_name=team.name if team else None,
        role=role_val,
        email=invitation.email,
        expires_at=invitation.expires_at,
    )


@router.get("/invitations", response_model=list[InviteResponse])
async def list_invitations(
    current_admin: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """Admin: list all invitations for their team (ordered newest first)."""
    from sqlalchemy import desc
    result = await db.execute(
        select(TeamInvitation)
        .where(TeamInvitation.team_id == current_admin.team_id)
        .order_by(desc(TeamInvitation.created_at))
    )
    invitations = result.scalars().all()

    out = []
    for inv in invitations:
        role_val = inv.role.value if hasattr(inv.role, "value") else str(inv.role)
        inviter_name = None
        if inv.invited_by_id:
            r = await db.execute(select(User).where(User.id == inv.invited_by_id))
            inviter = r.scalar_one_or_none()
            inviter_name = inviter.full_name if inviter else None
        out.append(InviteResponse(
            id=inv.id,
            email=inv.email,
            role=role_val,
            token=inv.token,
            expires_at=inv.expires_at,
            used_at=inv.used_at,
            created_at=inv.created_at,
            invited_by_name=inviter_name,
        ))
    return out


@router.delete("/invitations/{invitation_id}")
async def revoke_invitation(
    invitation_id: str,
    current_admin: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """Admin: revoke (delete) a pending invitation."""
    result = await db.execute(
        select(TeamInvitation).where(
            TeamInvitation.id == invitation_id,
            TeamInvitation.team_id == current_admin.team_id,
        )
    )
    invitation = result.scalar_one_or_none()
    if not invitation:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invitation not found")
    if invitation.used_at:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot revoke a used invitation")

    await db.delete(invitation)
    await db.commit()
    return {"message": "Invitation revoked"}


@router.get("/admin-exists")
async def check_admin_exists(db: AsyncSession = Depends(get_db)):
    """
    Check whether an admin user already exists in the system.
    Used by the registration page to conditionally show/hide the Admin role option.
    """
    result = await db.execute(select(User).where(User.role == UserRole.ADMIN).limit(1))
    admin = result.scalar_one_or_none()
    return {"admin_exists": admin is not None}
