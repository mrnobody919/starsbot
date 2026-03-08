"""
Антифлуд: ограничение частоты сообщений от пользователя.
"""
import asyncio
from collections import defaultdict
from typing import Any, Awaitable, Callable, Dict, cast

from aiogram import BaseMiddleware
from aiogram.types import Message, TelegramObject

from bot.utils.logger import get_logger

logger = get_logger(__name__)


class AntifloodMiddleware(BaseMiddleware):
    """
    Middleware: если пользователь шлёт сообщения чаще чем rate_limit раз в period_sec,
    игнорируем (или предупреждаем).
    """

    def __init__(self, rate_limit: int = 5, period_sec: float = 3.0):
        self.rate_limit = rate_limit
        self.period_sec = period_sec
        self._user_timestamps: Dict[int, list[float]] = defaultdict(list)
        self._lock = asyncio.Lock()

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        if not isinstance(event, Message):
            return await handler(event, data)

        user_id = event.from_user.id if event.from_user else 0
        if user_id == 0:
            return await handler(event, data)

        now = asyncio.get_event_loop().time()
        async with self._lock:
            timestamps = self._user_timestamps[user_id]
            # Удаляем старые
            while timestamps and timestamps[0] < now - self.period_sec:
                timestamps.pop(0)
            if len(timestamps) >= self.rate_limit:
                logger.debug("Antiflood: user %s rate limited", user_id)
                try:
                    await event.answer("Слишком много запросов. Подождите несколько секунд.")
                except Exception:
                    pass
                return None
            timestamps.append(now)

        return await handler(event, data)
