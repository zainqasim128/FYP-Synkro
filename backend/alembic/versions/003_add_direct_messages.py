"""Add direct_messages table

Revision ID: 003
Revises: 002
Create Date: 2026-03-27
"""
from alembic import op
import sqlalchemy as sa

revision = '003'
down_revision = '002_add_entities'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS direct_messages (
            id VARCHAR(36) PRIMARY KEY,
            sender_id VARCHAR(36) NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            recipient_id VARCHAR(36) NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            content TEXT NOT NULL,
            created_at TIMESTAMP NOT NULL,
            read_at TIMESTAMP,
            slack_ts VARCHAR(32)
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_direct_messages_slack_ts ON direct_messages (slack_ts)")


def downgrade() -> None:
    op.drop_index('ix_direct_messages_slack_ts')
    op.drop_table('direct_messages')
