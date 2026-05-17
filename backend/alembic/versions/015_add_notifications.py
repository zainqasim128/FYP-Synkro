"""add notifications table

Revision ID: 015_add_notifications
Revises: 014_add_task_comments
Create Date: 2026-05-16
"""
from alembic import op
import sqlalchemy as sa

revision = '015_add_notifications'
down_revision = '014_add_task_comments'
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        "DO $$ BEGIN "
        "CREATE TYPE notificationtype AS ENUM "
        "('task_assigned', 'task_status_changed', 'meeting_completed', 'comment_added'); "
        "EXCEPTION WHEN duplicate_object THEN NULL; "
        "END $$"
    )

    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if 'notifications' not in inspector.get_table_names():
        op.create_table(
            'notifications',
            sa.Column('id', sa.String(36), primary_key=True),
            sa.Column('user_id', sa.String(36), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
            sa.Column(
                'type',
                sa.Enum(
                    'task_assigned', 'task_status_changed', 'meeting_completed', 'comment_added',
                    name='notificationtype', create_type=False,
                ),
                nullable=False,
            ),
            sa.Column('title', sa.String(255), nullable=False),
            sa.Column('body', sa.Text(), nullable=True),
            sa.Column('link', sa.String(500), nullable=True),
            sa.Column('is_read', sa.Boolean(), nullable=False, server_default='false'),
            sa.Column('created_at', sa.DateTime(), nullable=False),
        )

    existing_indexes = {idx['name'] for idx in inspector.get_indexes('notifications')}
    if 'idx_notification_user_id' not in existing_indexes:
        op.create_index('idx_notification_user_id', 'notifications', ['user_id'])
    if 'idx_notification_created_at' not in existing_indexes:
        op.create_index('idx_notification_created_at', 'notifications', ['created_at'])


def downgrade():
    op.drop_index('idx_notification_created_at', 'notifications')
    op.drop_index('idx_notification_user_id', 'notifications')
    op.drop_table('notifications')
    op.execute("DROP TYPE IF EXISTS notificationtype")
