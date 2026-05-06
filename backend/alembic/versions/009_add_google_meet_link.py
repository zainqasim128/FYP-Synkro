"""add google_meet_link to meetings

Adds:
  - meetings.google_meet_link  (stores Google Meet URL from calendar conferenceData)

Revision ID: 009_add_google_meet_link
Revises: 008_add_calendar_automation
Create Date: 2026-05-06
"""
from alembic import op
import sqlalchemy as sa

revision = '009_add_google_meet_link'
down_revision = '008_add_calendar_automation'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE meetings ADD COLUMN IF NOT EXISTS google_meet_link VARCHAR(500)")


def downgrade() -> None:
    op.execute("ALTER TABLE meetings DROP COLUMN IF EXISTS google_meet_link")
