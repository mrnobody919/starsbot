"""
Профиль пользователя: ID, реферальная ссылка, рефералы, бонусы, заказы.
"""
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from aiogram import Router, F
from aiogram.types import CallbackQuery

from bot.database.models import User, Order
from bot.keyboards import profile_kb, orders_list_kb, order_detail_kb
from bot.config import AppConfig
from bot.utils.helpers import format_stars, edit_or_send_text, format_datetime, safe_callback_answer
from bot.utils.logger import get_logger

logger = get_logger(__name__)

router = Router(name="profile")


async def _get_user_by_telegram_id(session: AsyncSession, telegram_id: int) -> User | None:
    result = await session.execute(select(User).where(User.telegram_id == telegram_id))
    return result.scalar_one_or_none()


@router.callback_query(F.data == "menu:profile")
async def show_profile(callback: CallbackQuery, session: AsyncSession, config: AppConfig):
    """Показывает профиль: ID, реферальная ссылка, кол-во рефералов, бонусы, заказы."""
    user = await _get_user_by_telegram_id(session, callback.from_user.id)
    if not user:
        await safe_callback_answer(callback, "Ошибка: пользователь не найден.", show_alert=True)
        return

    bot_username = (config.bot.bot_username or "your_bot").lstrip("@")
    ref_link = f"https://t.me/{bot_username}?start=ref_{user.referral_code}"

    # Успешные заказы и куплено звезд
    orders_result = await session.execute(
        select(
            func.count(Order.id).label("total_orders"),
            func.coalesce(func.sum(Order.stars_amount), 0).label("total_stars"),
        ).where(Order.user_id == user.id, Order.delivery_status == "completed")
    )
    row = orders_result.one()
    total_orders = row.total_orders or 0
    total_stars = int(row.total_stars or 0)
    balance_usd = getattr(user, "balance_usd", 0.0) or 0.0
    referral_usd = getattr(user, "referral_reward_total", 0.0) or 0.0

    text = (
        "👤 <b>Ваш профиль</b>\n\n"
        f"🆔 UUID Профиля: <code>{user.telegram_id}</code>\n\n"
        f"💰 Текущий баланс (в боте): {balance_usd:.2f}$\n\n"
        "🚀 <b>Реферальная система</b>\n"
        "<i>Получай +10% от прибыли сервиса за покупки ваших рефералов!</i>\n"
        f"👬 <b>Всего рефералов:</b> {user.referrals_count}\n"
        f"📌 Всего получено от рефералов: {referral_usd:.2f}$\n"
        f"🔗 Ваша реферальная ссылка:\n<code>{ref_link}</code>\n\n"
        "📊 <b>Статистика</b>\n"
        f"📦 Успешных заказов: {total_orders}\n"
        f"⭐ Куплено звёзд: {format_stars(total_stars)}\n"
    )
    await edit_or_send_text(callback, text, profile_kb())
    await safe_callback_answer(callback)


@router.callback_query(F.data == "menu:orders")
async def show_orders_list(callback: CallbackQuery, session: AsyncSession):
    """Список заказов пользователя с пагинацией."""
    user = await _get_user_by_telegram_id(session, callback.from_user.id)
    if not user:
        await callback.answer("Ошибка.", show_alert=True)
        return

    result = await session.execute(
        select(Order).where(Order.user_id == user.id).order_by(Order.created_at.desc())
    )
    orders = list(result.scalars().all())
    if not orders:
        await edit_or_send_text(
            callback,
            "📋 У вас пока нет заказов.",
            orders_list_kb([], 0, 5),
        )
        await safe_callback_answer(callback)
        return

    page = 0
    await edit_or_send_text(
        callback,
        "📋 Ваши заказы:",
        orders_list_kb(orders, page, 5),
    )
    await safe_callback_answer(callback)


@router.callback_query(F.data.startswith("orders:page:"))
async def orders_page(callback: CallbackQuery, session: AsyncSession):
    """Пагинация по заказам."""
    try:
        page = int(callback.data.split(":")[-1])
    except ValueError:
        page = 0
    user = await _get_user_by_telegram_id(session, callback.from_user.id)
    if not user:
        await safe_callback_answer(callback)
        return
    result = await session.execute(
        select(Order).where(Order.user_id == user.id).order_by(Order.created_at.desc())
    )
    orders = list(result.scalars().all())
    await callback.message.edit_reply_markup(reply_markup=orders_list_kb(orders, page, 5))
    await safe_callback_answer(callback)


@router.callback_query(F.data.startswith("order:view:"))
async def order_view(callback: CallbackQuery, session: AsyncSession):
    """Просмотр одного заказа."""
    try:
        order_id = int(callback.data.split(":")[-1])
    except ValueError:
        await safe_callback_answer(callback)
        return
    user = await _get_user_by_telegram_id(session, callback.from_user.id)
    if not user:
        await safe_callback_answer(callback, "Ошибка.", show_alert=True)
        return
    order = await session.get(Order, order_id)
    if not order or order.user_id != user.id:
        await safe_callback_answer(callback, "Заказ не найден.", show_alert=True)
        return

    status_emoji = "✅" if order.delivery_status == "completed" else "⏳"
    pay_emoji = "✅" if order.payment_status == "paid" else "⏳"
    text = (
        f"{status_emoji} Заказ #{order.id}\n\n"
        f"⭐ Stars: {order.stars_amount}\n"
        f"💵 Сумма: {order.price} {order.payment_method}\n"
        f"Оплата: {pay_emoji} {'Оплачен' if order.payment_status == 'paid' else 'Ожидание'}\n"
        f"Доставка: {status_emoji} {'Выполнен' if order.delivery_status == 'completed' else 'Ожидание'}\n"
        f"📅 {format_datetime(order.created_at)}\n"
    )
    await callback.message.edit_text(text, reply_markup=order_detail_kb(order_id))
    await safe_callback_answer(callback)
