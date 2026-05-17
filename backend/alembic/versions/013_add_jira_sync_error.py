"""add jira_sync_error to tasks

Stores the last sync error message for Jira-linked tasks.
Used by the Jira Sync Dashboard to highlight failed syncs and let admins retry.

Revision ID: 013_add_jira_sync_error
Revises: 012_add_jira_synced_at
Create Date: 2026-05-16
"""
from alembic import op
import sqlalchemy as sa

revision = '013_add_jira_sync_error'
down_revision = '012_add_jira_synced_at'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('tasks', sa.Column('jira_sync_error', sa.Text(), nullable=True))


def downgrade():
    op.drop_column('tasks', 'jira_sync_error')
