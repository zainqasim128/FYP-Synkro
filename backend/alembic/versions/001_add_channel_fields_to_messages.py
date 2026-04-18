"""add channel_id and channel_type to messages

Revision ID: 001_add_channel_fields
Revises:
Create Date: 2026-03-17
"""
from alembic import op
import sqlalchemy as sa

revision = '001_add_channel_fields'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE messages ADD COLUMN IF NOT EXISTS channel_id VARCHAR(255)")
    op.execute("ALTER TABLE messages ADD COLUMN IF NOT EXISTS channel_type VARCHAR(50)")


def downgrade() -> None:
    with op.batch_alter_table('messages', schema=None) as batch_op:
        batch_op.drop_column('channel_type')
        batch_op.drop_column('channel_id')
