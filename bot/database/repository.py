"""
Репозиторий: получение/создание пользователя, настройки (курс Stars), заказы и рефералы.
"""
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional

from bot.database.models import User, Order, Referral, AppSettings
from bot.utils.helpers import generate_referral_code
SETTING_TON_PER_100STARS = "ton_per_100stars"
SETTING_MARGIN_PERCENT = "margin_percent"
SETTING_PREMIUM_PRICE_3M = "premium_price_3m_usd"
SETTING_PREMIUM_PRICE_6M = "premium_price_6m_usd"
SETTING_PREMIUM_PRICE_12M = "premium_price_12m_usd"


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


async def get_ton_per_100stars(session: AsyncSession, default: float | None = None) -> float | None:
    """Возвращает цену: сколько TON стоит 100 ⭐ (из БД) или default."""
    raw = await get_setting(session, SETTING_TON_PER_100STARS)
    if raw is None:
        return default
    try:
        val = float(raw)
        return val
    except (ValueError, TypeError):
        return default


async def set_ton_per_100stars(session: AsyncSession, value: float) -> None:
    """Сохраняет цену: сколько TON стоит 100 ⭐ в БД."""
    await set_setting(session, SETTING_TON_PER_100STARS, str(value))


async def get_margin_percent(session: AsyncSession, default: float = 0.0) -> float:
    """Возвращает маржу в процентах (из БД) или default."""
    raw = await get_setting(session, SETTING_MARGIN_PERCENT)
    if raw is None:
        return default
    try:
        return float(raw)
    except (ValueError, TypeError):
        return default


async def set_margin_percent(session: AsyncSession, value: float) -> None:
    """Сохраняет маржу в процентах (из БД)."""
    await set_setting(session, SETTING_MARGIN_PERCENT, str(value))


async def get_premium_price_usd(session: AsyncSession, months: int) -> Optional[float]:
    """Возвращает цену Premium в USD для указанного срока (3/6/12 месяцев)."""
    key = None
    if months == 3:
        key = SETTING_PREMIUM_PRICE_3M
    elif months == 6:
        key = SETTING_PREMIUM_PRICE_6M
    elif months == 12:
        key = SETTING_PREMIUM_PRICE_12M
    if not key:
        return None
    raw = await get_setting(session, key)
    if raw is None:
        return None
    try:
        return float(raw)
    except (ValueError, TypeError):
        return None


async def set_premium_price_usd(session: AsyncSession, months: int, value_usd: float) -> None:
    """Сохраняет цену Premium в USD для указанного срока (3/6/12 месяцев)."""
    key = None
    if months == 3:
        key = SETTING_PREMIUM_PRICE_3M
    elif months == 6:
        key = SETTING_PREMIUM_PRICE_6M
    elif months == 12:
        key = SETTING_PREMIUM_PRICE_12M
    if not key:
        return
    await set_setting(session, key, str(value_usd))


async def get_premium_prices_usd(session: AsyncSession) -> dict[int, float]:
    """Возвращает цены Premium (3/6/12 месяцев) в USD."""
    out: dict[int, float] = {}
    for m in (3, 6, 12):
        price = await get_premium_price_usd(session, m)
        if price is not None:
            out[m] = price
    return out
