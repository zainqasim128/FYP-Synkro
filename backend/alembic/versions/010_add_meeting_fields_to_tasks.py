"""add meeting fields to tasks

Adds four columns to the tasks table to support Google Meet auto-generation:
  - is_meeting_task     (Boolean, default False)
  - google_meet_link    (VARCHAR 500, nullable)
  - meeting_scheduled_at (DateTime, nullable — separate from due_date)
  - meeting_duration_minutes (Integer, default 60)

Revision ID: 010_add_meeting_fields_to_tasks
Revises: 009_add_google_meet_link
Create Date: 2026-05-16
"""
from alembic import op
import sqlalchemy as sa

revision = '010_add_meeting_fields_to_tasks'
down_revision = '009_add_google_meet_link'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS is_meeting_task BOOLEAN NOT NULL DEFAULT FALSE"
    )
    op.execute(
        "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS google_meet_link VARCHAR(500)"
    )
    op.execute(
        "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS meeting_scheduled_at TIMESTAMP"
    )
    op.execute(
        "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS meeting_duration_minutes INTEGER NOT NULL DEFAULT 60"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE tasks DROP COLUMN IF EXISTS meeting_duration_minutes")
    op.execute("ALTER TABLE tasks DROP COLUMN IF EXISTS meeting_scheduled_at")
    op.execute("ALTER TABLE tasks DROP COLUMN IF EXISTS google_meet_link")
    op.execute("ALTER TABLE tasks DROP COLUMN IF EXISTS is_meeting_task")
