"""add jira_synced_at to tasks

Tracks the last time a task was updated by an inbound Jira webhook (Jira → Synkro sync).
Used by the task card to display "last synced from Jira" and by admins to audit sync health.

Revision ID: 012_add_jira_synced_at
Revises: 011_add_team_invitations
Create Date: 2026-05-16
"""
from alembic import op
import sqlalchemy as sa

revision = '012_add_jira_synced_at'
down_revision = '011_add_team_invitations'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('tasks', sa.Column('jira_synced_at', sa.DateTime(), nullable=True))


def downgrade():
    op.drop_column('tasks', 'jira_synced_at')
