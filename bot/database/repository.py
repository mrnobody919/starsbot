"""
Репозиторий: получение/создание пользователя, работа с заказами и рефералами.
"""
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.database.models import User, Order, Referral
from bot.utils.helpers import generate_referral_code


async def get_or_create_user(
    session: AsyncSession,
    telegram_id: int,
    username: str | None = None,
    referral_code_from_start: str | None = None,
) -> tuple[User, bool]:
    """
    Возвращает пользователя по telegram_id или создаёт нового.
    referral_code_from_start — реферальный код из /start ref_XXXX.
    Возвращает (user, created).
    """
    result = await session.execute(select(User).where(User.telegram_id == telegram_id))
    user = result.scalar_one_or_none()
    if user:
        if username is not None and user.username != username:
            user.username = username
        return user, False

    ref_code = generate_referral_code(telegram_id)
    user = User(
        telegram_id=telegram_id,
        username=username,
        referral_code=ref_code,
    )
    session.add(user)
    await session.flush()

    # Если перешли по реферальной ссылке — находим реферера и связываем
    if referral_code_from_start:
        ref_result = await session.execute(
            select(User).where(User.referral_code == referral_code_from_start)
        )
        referrer = ref_result.scalar_one_or_none()
        if referrer and referrer.id != user.id:
            user.referred_by = referrer.id
            referrer.referrals_count += 1
            session.add(Referral(referrer_id=referrer.id, referred_user_id=user.id))

    return user, True
