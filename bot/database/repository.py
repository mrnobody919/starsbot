"""
Репозиторий: получение/создание пользователя, настройки (курс Stars), заказы и рефералы.
"""
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.database.models import User, Order, Referral, AppSettings
from bot.utils.helpers import generate_referral_code

SETTING_USD_PER_STAR = "usd_per_star"


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


async def get_setting(session: AsyncSession, key: str) -> str | None:
    """Возвращает значение настройки по ключу или None."""
    result = await session.execute(select(AppSettings).where(AppSettings.key == key))
    row = result.scalar_one_or_none()
    return row.value if row else None


async def set_setting(session: AsyncSession, key: str, value: str) -> None:
    """Сохраняет настройку (создаёт или обновляет)."""
    result = await session.execute(select(AppSettings).where(AppSettings.key == key))
    row = result.scalar_one_or_none()
    if row:
        row.value = value
    else:
        session.add(AppSettings(key=key, value=value))


async def get_usd_per_star(session: AsyncSession, default: float) -> float:
    """Возвращает курс 1 Star = X USD из БД или default из конфига."""
    raw = await get_setting(session, SETTING_USD_PER_STAR)
    if raw is None:
        return default
    try:
        return float(raw)
    except (ValueError, TypeError):
        return default


async def set_usd_per_star(session: AsyncSession, value: float) -> None:
    """Сохраняет курс 1 Star = X USD в БД (для админки)."""
    await set_setting(session, SETTING_USD_PER_STAR, str(value))
