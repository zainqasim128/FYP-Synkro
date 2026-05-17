"""add team_invitations table

Creates the team_invitations table used by the team invitation system.
Admins generate invite tokens; new users register with a token to join the team.

Revision ID: 011_add_team_invitations
Revises: 010_add_meeting_fields_to_tasks
Create Date: 2026-05-16
"""
from alembic import op
import sqlalchemy as sa

revision = '011_add_team_invitations'
down_revision = '010_add_meeting_fields_to_tasks'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS team_invitations (
            id VARCHAR(36) PRIMARY KEY,
            team_id VARCHAR(36) NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
            email VARCHAR(255),
            role VARCHAR(50) NOT NULL DEFAULT 'developer',
            token VARCHAR(128) NOT NULL UNIQUE,
            invited_by_id VARCHAR(36) REFERENCES users(id) ON DELETE SET NULL,
            expires_at TIMESTAMP NOT NULL,
            used_at TIMESTAMP,
            created_at TIMESTAMP NOT NULL DEFAULT NOW()
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_team_invitations_token ON team_invitations (token)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_team_invitations_team_id ON team_invitations (team_id)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS team_invitations")
