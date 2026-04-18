"""add zoom integration - enum value and meeting columns

Revision ID: 004_add_zoom_integration
Revises: 003
Create Date: 2026-03-29
"""
from alembic import op
import sqlalchemy as sa

revision = '004_add_zoom_integration'
down_revision = '003'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add ZOOM to IntegrationPlatform enum (PostgreSQL-specific)
    # Use a raw SQL approach that works with both PostgreSQL and SQLite
    bind = op.get_bind()
    dialect = bind.dialect.name

    if dialect == 'postgresql':
        op.execute("ALTER TYPE integrationplatform ADD VALUE IF NOT EXISTS 'zoom'")
        op.execute("ALTER TYPE meetingstatus ADD VALUE IF NOT EXISTS 'awaiting_upload'")

    # Add zoom columns to meetings table
    with op.batch_alter_table('meetings', schema=None) as batch_op:
        batch_op.add_column(sa.Column('zoom_meeting_id', sa.String(100), nullable=True))
        batch_op.add_column(sa.Column('zoom_recording_id', sa.String(100), nullable=True))

    # Create indexes
    op.create_index('ix_meetings_zoom_meeting_id', 'meetings', ['zoom_meeting_id'])
    op.create_index('ix_meetings_zoom_recording_id', 'meetings', ['zoom_recording_id'])


def downgrade() -> None:
    op.drop_index('ix_meetings_zoom_recording_id', table_name='meetings')
    op.drop_index('ix_meetings_zoom_meeting_id', table_name='meetings')

    with op.batch_alter_table('meetings', schema=None) as batch_op:
        batch_op.drop_column('zoom_recording_id')
        batch_op.drop_column('zoom_meeting_id')

    # Note: PostgreSQL does not support removing enum values; downgrade leaves enum as-is
