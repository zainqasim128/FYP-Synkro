"""
Migration: Add Google Calendar columns to tasks and action_items.

Run once:
    cd backend
    python migrate_google_calendar.py
"""
import asyncio
import sys
import os

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from app.config import settings


async def migrate():
    engine = create_async_engine(settings.database_url_async, echo=False)
    db_url = settings.DATABASE_URL

    print("=" * 60)
    print("Synkro Migration: Google Calendar Columns")
    print("=" * 60)

    async with engine.begin() as conn:
        # tasks: calendar_event_id + calendar_synced_at
        try:
            await conn.execute(text(
                "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS calendar_event_id VARCHAR(500)"
            ))
            print("    [OK] tasks.calendar_event_id")
        except Exception as exc:
            print(f"    [!] tasks.calendar_event_id: {exc}")

        try:
            await conn.execute(text(
                "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS calendar_synced_at TIMESTAMP"
            ))
            print("    [OK] tasks.calendar_synced_at")
        except Exception as exc:
            print(f"    [!] tasks.calendar_synced_at: {exc}")

        # action_items: calendar_event_id
        try:
            await conn.execute(text(
                "ALTER TABLE action_items ADD COLUMN IF NOT EXISTS calendar_event_id VARCHAR(500)"
            ))
            print("    [OK] action_items.calendar_event_id")
        except Exception as exc:
            print(f"    [!] action_items.calendar_event_id: {exc}")

        # meetings: calendar_event_id (Feature A)
        try:
            await conn.execute(text(
                "ALTER TABLE meetings ADD COLUMN IF NOT EXISTS calendar_event_id VARCHAR(500)"
            ))
            print("    [OK] meetings.calendar_event_id")
        except Exception as exc:
            print(f"    [!] meetings.calendar_event_id: {exc}")

        # calendar_preferences table
        try:
            await conn.execute(text("""
                CREATE TABLE IF NOT EXISTS calendar_preferences (
                    id VARCHAR(36) PRIMARY KEY,
                    user_id VARCHAR(36) REFERENCES users(id) ON DELETE CASCADE,
                    auto_sync_tasks BOOLEAN DEFAULT true NOT NULL,
                    auto_sync_meetings BOOLEAN DEFAULT true NOT NULL,
                    auto_sync_actions BOOLEAN DEFAULT false NOT NULL,
                    reminder_urgent_minutes JSONB DEFAULT '[2880, 120]',
                    reminder_high_minutes JSONB DEFAULT '[1440, 120]',
                    reminder_medium_minutes JSONB DEFAULT '[1440, 60]',
                    reminder_low_minutes JSONB DEFAULT '[360]',
                    daily_digest_enabled BOOLEAN DEFAULT false NOT NULL,
                    daily_digest_time VARCHAR(5) DEFAULT '08:00',
                    created_at TIMESTAMP DEFAULT NOW() NOT NULL,
                    updated_at TIMESTAMP DEFAULT NOW() NOT NULL,
                    UNIQUE(user_id)
                )
            """))
            print("    [OK] calendar_preferences table")
        except Exception as exc:
            print(f"    [!] calendar_preferences: {exc}")

        # auto_reschedule_overdue toggle (Feature C)
        try:
            await conn.execute(text(
                "ALTER TABLE calendar_preferences ADD COLUMN IF NOT EXISTS "
                "auto_reschedule_overdue BOOLEAN DEFAULT false NOT NULL"
            ))
            print("    [OK] calendar_preferences.auto_reschedule_overdue")
        except Exception as exc:
            print(f"    [!] calendar_preferences.auto_reschedule_overdue: {exc}")

    print("\n[*] Migration complete!")
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(migrate())
