"""
Инициализация БД: создание engine, сессий, миграции таблиц.
Используется async SQLAlchemy + asyncpg.
"""
from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from .models import Base


def get_async_database_url(sync_url: str) -> str:
    """
    Преобразует postgresql:// в postgresql+asyncpg:// для async драйвера.
    """
    if sync_url.startswith("postgresql://"):
        return sync_url.replace("postgresql://", "postgresql+asyncpg://", 1)
    if sync_url.startswith("postgres://"):
        return sync_url.replace("postgres://", "postgresql+asyncpg://", 1)
    return sync_url


def create_engine(database_url: str):
    """
    Создаёт async engine. NullPool удобен для serverless/Railway.
    """
    url = get_async_database_url(database_url)
    return create_async_engine(
        url,
        poolclass=NullPool,
        echo=False,
    )


async def init_db(database_url: str) -> async_sessionmaker[AsyncSession]:
    """
    Создаёт таблицы и возвращает фабрику сессий.
    Вызывать при старте приложения.
    """
    engine = create_engine(database_url)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autocommit=False,
        autoflush=False,
    )
    return session_factory


async def get_session(
    session_factory: async_sessionmaker[AsyncSession],
) -> AsyncGenerator[AsyncSession, None]:
    """
    Dependency: выдаёт сессию для одного запроса и закрывает её после.
    """
    async with session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
