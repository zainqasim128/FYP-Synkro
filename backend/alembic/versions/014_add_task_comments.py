"""add task_comments table

Revision ID: 014_add_task_comments
Revises: 013_add_jira_sync_error
Create Date: 2026-05-16
"""
from alembic import op
import sqlalchemy as sa

revision = '014_add_task_comments'
down_revision = '013_add_jira_sync_error'
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        "DO $$ BEGIN "
        "CREATE TYPE commentsource AS ENUM ('synkro', 'jira'); "
        "EXCEPTION WHEN duplicate_object THEN NULL; "
        "END $$"
    )

    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if 'task_comments' not in inspector.get_table_names():
        op.create_table(
            'task_comments',
            sa.Column('id', sa.String(36), primary_key=True),
            sa.Column('task_id', sa.String(36), sa.ForeignKey('tasks.id', ondelete='CASCADE'), nullable=False),
            sa.Column('body', sa.Text(), nullable=False),
            sa.Column('author_id', sa.String(36), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
            sa.Column('jira_comment_id', sa.String(64), nullable=True, unique=True),
            sa.Column('jira_author_name', sa.String(255), nullable=True),
            sa.Column('source', sa.Enum('synkro', 'jira', name='commentsource', create_type=False), nullable=False),
            sa.Column('created_at', sa.DateTime(), nullable=False),
            sa.Column('updated_at', sa.DateTime(), nullable=True),
        )

    existing_indexes = {idx['name'] for idx in inspector.get_indexes('task_comments')}
    if 'idx_task_comment_task_id' not in existing_indexes:
        op.create_index('idx_task_comment_task_id', 'task_comments', ['task_id'])
    if 'idx_task_comment_created_at' not in existing_indexes:
        op.create_index('idx_task_comment_created_at', 'task_comments', ['created_at'])


def downgrade():
    op.drop_index('idx_task_comment_created_at', 'task_comments')
    op.drop_index('idx_task_comment_task_id', 'task_comments')
    op.drop_table('task_comments')
    op.execute("DROP TYPE IF EXISTS commentsource")
