import pytest
from typing import AsyncGenerator
from uuid import uuid4
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.pool import StaticPool

from services.common.database.core import Base
from services.common.auth.models import User
from services.core.app.pipelines.models import Pipeline
from services.core.app.recast.models import RecastTemplate


# Use file-based URI with shared cache to ensure single database instance
TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:?cache=shared"


@pytest.fixture(scope="function")
async def engine():
    # Ensure models are loaded by referencing them
    # This ensures they're registered with Base.metadata
    _ = [Pipeline, RecastTemplate]

    engine = create_async_engine(
        TEST_DATABASE_URL,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        echo=False,
    )

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    yield engine

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)

    await engine.dispose()


@pytest.fixture
async def db_session(engine) -> AsyncGenerator[AsyncSession, None]:
    async_session = async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    async with async_session() as session:
        yield session


@pytest.fixture
def mock_user() -> User:
    return User(
        id=uuid4(),
        email="test@example.com",
    )


@pytest.fixture
def mock_rabbitmq_publisher(mocker):
    publisher = mocker.AsyncMock()
    publisher.publish = mocker.AsyncMock()
    return publisher
