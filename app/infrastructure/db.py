from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import get_settings


def create_engine(database_url: str | None = None) -> AsyncEngine:
    settings = get_settings()
    return create_async_engine(database_url or settings.database_url, pool_pre_ping=True)


engine = create_engine()
async_session_factory = async_sessionmaker(
    engine,
    expire_on_commit=False,
    class_=AsyncSession,
)
