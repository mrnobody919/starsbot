"""
Инициализация БД: создание engine, сессий, миграции таблиц.
Используется async SQLAlchemy + asyncpg.
"""
import asyncio
import os
from typing import AsyncGenerator

from sqlalchemy import text
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
    При старте на Railway повторяет попытки подключения (DNS/сеть могут быть не готовы).
    """
    max_attempts = int(os.getenv("DB_CONNECT_ATTEMPTS", "5"))
    delay_sec = float(os.getenv("DB_CONNECT_DELAY", "5"))
    last_error = None
    engine = create_engine(database_url)
    for attempt in range(1, max_attempts + 1):
        if attempt > 1:
            await asyncio.sleep(delay_sec)
        try:
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
                # Добавить колонку balance_usd, если таблица users уже была без неё (миграция)
                await conn.execute(text(
                    "ALTER TABLE users ADD COLUMN IF NOT EXISTS balance_usd DOUBLE PRECISION DEFAULT 0.0"
                ))
            break
        except Exception as e:
            last_error = e
            if attempt >= max_attempts:
                raise last_error
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
