"""add calendar automation columns

Adds:
  - meetings.calendar_event_id       (tracks synced GCal event for upsert/delete)
  - tasks.calendar_event_id          (tracks synced GCal event for tasks)
  - tasks.calendar_synced_at         (last sync timestamp)
  - calendar_preferences table       (user calendar preferences)

Revision ID: 008_add_calendar_automation
Revises: 007_add_action_item_cols
Create Date: 2026-05-06
"""
from alembic import op
import sqlalchemy as sa

revision = '008_add_calendar_automation'
down_revision = '007_add_action_item_cols'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add calendar_event_id to meetings
    op.execute("ALTER TABLE meetings ADD COLUMN IF NOT EXISTS calendar_event_id VARCHAR(500)")

    # Add calendar fields to tasks
    op.execute("ALTER TABLE tasks ADD COLUMN IF NOT EXISTS calendar_event_id VARCHAR(500)")
    op.execute("ALTER TABLE tasks ADD COLUMN IF NOT EXISTS calendar_synced_at TIMESTAMP")

    # Create calendar_preferences table if not exists
    op.execute("""
        CREATE TABLE IF NOT EXISTS calendar_preferences (
            id VARCHAR(36) PRIMARY KEY,
            user_id VARCHAR(36) NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            auto_sync_tasks BOOLEAN NOT NULL DEFAULT TRUE,
            auto_sync_meetings BOOLEAN NOT NULL DEFAULT TRUE,
            auto_sync_actions BOOLEAN NOT NULL DEFAULT FALSE,
            reminder_urgent_minutes TEXT NOT NULL DEFAULT '[10, 30]',
            reminder_high_minutes TEXT NOT NULL DEFAULT '[30]',
            reminder_medium_minutes TEXT NOT NULL DEFAULT '[60]',
            reminder_low_minutes TEXT NOT NULL DEFAULT '[]',
            daily_digest_enabled BOOLEAN NOT NULL DEFAULT FALSE,
            daily_digest_time VARCHAR(10) NOT NULL DEFAULT '08:00',
            auto_reschedule_overdue BOOLEAN NOT NULL DEFAULT FALSE,
            created_at TIMESTAMP NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMP
        )
    """)

    # Add auto_reschedule_overdue if table already existed without it
    op.execute(
        "ALTER TABLE calendar_preferences ADD COLUMN IF NOT EXISTS auto_reschedule_overdue BOOLEAN NOT NULL DEFAULT FALSE"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS calendar_preferences")
    op.execute("ALTER TABLE tasks DROP COLUMN IF EXISTS calendar_synced_at")
    op.execute("ALTER TABLE tasks DROP COLUMN IF EXISTS calendar_event_id")
    op.execute("ALTER TABLE meetings DROP COLUMN IF EXISTS calendar_event_id")
