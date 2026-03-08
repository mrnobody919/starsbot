"""
Антифрод: ограничение заказов по времени, блокировки, проверка подозрительной активности.
"""
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession

from bot.config import AntifraudConfig
from bot.database.models import User, Order
from bot.utils.logger import get_logger

logger = get_logger(__name__)


class AntifraudService:
    """Проверки антифрода и ограничения."""

    def __init__(self, config: AntifraudConfig):
        self.config = config

    async def count_orders_last_minute(self, session: AsyncSession, user_id: int) -> int:
        """Считает заказы пользователя за последнюю минуту."""
        since = datetime.utcnow() - timedelta(minutes=1)
        result = await session.execute(
            select(func.count(Order.id)).where(
                and_(Order.user_id == user_id, Order.created_at >= since)
            )
        )
        return result.scalar() or 0

    async def can_create_order(self, session: AsyncSession, user_id: int) -> tuple[bool, str]:
        """
        Проверяет, может ли пользователь создать новый заказ.
        Возвращает (разрешено, сообщение об ошибке).
        """
        user = await session.get(User, user_id)
        if not user:
            return False, "Пользователь не найден"
        if user.is_blocked:
            return False, "Ваш аккаунт заблокирован. Обратитесь в поддержку."

        count = await self.count_orders_last_minute(session, user_id)
        if count >= self.config.max_orders_per_minute:
            return False, f"Слишком много заказов. Подождите минуту (лимит: {self.config.max_orders_per_minute} в минуту)."
        return True, ""

    def validate_stars_amount(self, stars: int) -> tuple[bool, str]:
        """Проверяет допустимое количество Stars в одном заказе."""
        if stars < self.config.min_stars_per_order:
            return False, f"Минимум {self.config.min_stars_per_order} Stars"
        if stars > self.config.max_stars_per_order:
            return False, f"Максимум {self.config.max_stars_per_order} Stars"
        return True, ""
