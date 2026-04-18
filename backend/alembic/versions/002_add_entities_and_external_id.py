"""add entities and ensure external_id columns exist

Revision ID: 002_add_entities
Revises: 001_add_channel_fields
Create Date: 2026-03-17
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '002_add_entities'
down_revision = '001_add_channel_fields'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Use IF NOT EXISTS so this is idempotent on PostgreSQL
    op.execute("ALTER TABLE messages ADD COLUMN IF NOT EXISTS entities JSON DEFAULT '{}'")
    op.execute("ALTER TABLE messages ADD COLUMN IF NOT EXISTS external_id VARCHAR(255)")


def downgrade() -> None:
    with op.batch_alter_table('messages', schema=None) as batch_op:
        batch_op.drop_column('entities')
