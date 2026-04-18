"""
Pytest configuration and fixtures for testing.
"""
import asyncio
import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.pool import NullPool

from app.main import app
from app.database import Base, get_db
from app.models import User, Team
from app.utils.security import get_password_hash, create_access_token

# Test database URL
TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"


@pytest.fixture(scope="session")
def event_loop():
    """Create an instance of the default event loop for the test session."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture
async def test_engine():
    """Create test database engine."""
    # Use StaticPool for an in-memory SQLite database so that
    # the same connection is reused across the session.  SQLite
    # creates a new database for each connection when using
    # ":memory:" which was causing "no such table" errors in
    # fixtures that opened a fresh connection.
    from sqlalchemy.pool import StaticPool

    engine = create_async_engine(
        TEST_DATABASE_URL,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    yield engine

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)

    await engine.dispose()


@pytest_asyncio.fixture
async def test_db(test_engine):
    """Create test database session."""
    async_session = async_sessionmaker(
        test_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    async with async_session() as session:
        yield session


@pytest_asyncio.fixture
async def client(test_db):
    """Create test client with database override."""
    async def override_get_db():
        yield test_db

    app.dependency_overrides[get_db] = override_get_db

    async with AsyncClient(app=app, base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def test_team(test_db):
    """Create a test team."""
    team = Team(
        name="Test Team",
        plan="free",
        settings={}
    )
    test_db.add(team)
    await test_db.commit()
    await test_db.refresh(team)
    return team


@pytest_asyncio.fixture
async def test_user(test_db, test_team):
    """Create a test user."""
    user = User(
        email="test@example.com",
        password_hash=get_password_hash("testpassword123"),
        full_name="Test User",
        team_id=test_team.id,
        is_active=True,
        is_verified=True,
        role="member"
    )
    test_db.add(user)
    await test_db.commit()
    await test_db.refresh(user)
    return user


@pytest_asyncio.fixture
async def test_admin(test_db, test_team):
    """Create a test admin user."""
    admin = User(
        email="admin@example.com",
        password_hash=get_password_hash("adminpass123"),
        full_name="Admin User",
        team_id=test_team.id,
        is_active=True,
        is_verified=True,
        role="admin"
    )
    test_db.add(admin)
    await test_db.commit()
    await test_db.refresh(admin)
    return admin


@pytest.fixture
def auth_headers(test_user):
    """Generate auth headers for test user."""
    token = create_access_token(data={"sub": test_user.id})
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def admin_headers(test_admin):
    """Generate auth headers for admin user."""
    token = create_access_token(data={"sub": test_admin.id})
    return {"Authorization": f"Bearer {token}"}
