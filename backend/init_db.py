"""Initialize database schema from SQLAlchemy models"""
import asyncio
import sys
from sqlalchemy.ext.asyncio import create_async_engine

import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.config import settings
from app.database import Base
from app.models import (
    User, Team, Meeting, Task, Email, Integration, 
    Message, ActionItem
)


async def init_db():
    engine = create_async_engine(settings.database_url_async, echo=False)
    
    print("=" * 60)
    print("Synkro Database Initialization")
    print("=" * 60)
    print(f"\n[*] Database URL: {settings.DATABASE_URL}")
    
    async with engine.begin() as conn:
        print("[*] Creating all tables from models...")
        await conn.run_sync(Base.metadata.create_all)
        print("[OK] Tables created successfully!")
    
    await engine.dispose()
    print("\n[*] Database initialized and ready to use!")


if __name__ == "__main__":
    asyncio.run(init_db())
