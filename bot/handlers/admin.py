"""
Админ-панель: заказы, статистика, пользователи, рассылка, блокировки.
"""
from datetime import datetime, timedelta
from aiogram import Router, F
from aiogram.types import CallbackQuery, Message
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from bot.database.models import User, Order, Transaction, AdminLog
from bot.keyboards import (
    admin_main_kb,
    admin_orders_filter_kb,
    admin_order_actions_kb,
    admin_user_actions_kb,
    admin_confirm_broadcast_kb,
)
from bot.config import AppConfig
from bot.utils.helpers import format_datetime, format_stars
from bot.handlers.payments import _notify_user_order_completed
from bot.utils.logger import get_logger

router = Router(name="admin")
logger = get_logger(__name__)


def _is_admin(telegram_id: int, config: AppConfig) -> bool:
    return telegram_id in config.admin_ids


class BroadcastStates(StatesGroup):
    waiting_text = State()


async def _log_admin(session: AsyncSession, admin_id: int, action: str, details: str | None = None):
    """Логирование действия админа."""
    session.add(AdminLog(admin_id=admin_id, action=action, details=details))


@router.message(F.text == "/admin")
async def admin_entry(message: Message, session: AsyncSession, config: AppConfig):
    """Вход в админ-панель по команде /admin."""
    if not _is_admin(message.from_user.id, config):
        return
    await message.answer("🔐 Админ-панель", reply_markup=admin_main_kb())


@router.callback_query(F.data == "admin:close")
async def admin_close(callback: CallbackQuery):
    """Закрыть админку."""
    await callback.message.delete()
    await callback.answer()


@router.callback_query(F.data == "admin:main")
async def admin_main(callback: CallbackQuery, config: AppConfig):
    """Главное меню админки."""
    if not _is_admin(callback.from_user.id, config):
        await callback.answer("Доступ запрещён.", show_alert=True)
        return
    await callback.message.edit_text("🔐 Админ-панель", reply_markup=admin_main_kb())
    await callback.answer()


@router.callback_query(F.data == "admin:orders")
async def admin_orders_list(callback: CallbackQuery, session: AsyncSession, config: AppConfig):
    """Список заказов (оплаченные, ожидающие отправки)."""
    if not _is_admin(callback.from_user.id, config):
        await callback.answer()
        return
    result = await session.execute(
        select(Order).where(Order.payment_status == "paid").order_by(Order.created_at.desc()).limit(50)
    )
    orders = list(result.scalars().all())
    lines = ["📋 Оплаченные заказы (ожидают отправки):\n"]
    for o in orders[:15]:
        if o.delivery_status == "waiting":
            lines.append(f"⏳ #{o.id} | {o.stars_amount} ⭐ | user_id={o.user_id} | {format_datetime(o.created_at)}")
    if not lines[1:]:
        lines.append("Нет заказов в ожидании.")
    await callback.message.edit_text(
        "\n".join(lines),
        reply_markup=admin_orders_filter_kb(),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("admin:orders:filter:"))
async def admin_orders_filter(callback: CallbackQuery, session: AsyncSession, config: AppConfig):
    """Фильтр заказов: показать ожидающие или все."""
    if not _is_admin(callback.from_user.id, config):
        await callback.answer()
        return
    kind = callback.data.split(":")[-1]
    if kind == "waiting":
        result = await session.execute(
            select(Order).where(
                Order.payment_status == "paid",
                Order.delivery_status == "waiting",
            ).order_by(Order.created_at.desc()).limit(30)
        )
    else:
        result = await session.execute(
            select(Order).where(Order.payment_status == "paid").order_by(Order.created_at.desc()).limit(30)
        )
    orders = list(result.scalars().all())
    lines = ["📋 Заказы:\n"]
    for o in orders[:20]:
        status = "✅" if o.delivery_status == "completed" else "⏳"
        lines.append(f"{status} #{o.id} | {o.stars_amount} ⭐ | user_id={o.user_id}")
    await callback.message.edit_text("\n".join(lines) if lines[1:] else "Нет заказов.", reply_markup=admin_orders_filter_kb())
    await callback.answer()


@router.callback_query(F.data.startswith("admin:order:complete:"))
async def admin_order_complete(
    callback: CallbackQuery,
    session: AsyncSession,
    config: AppConfig,
):
    """Админ нажал «Отправил Stars» — помечаем заказ выполненным, уведомляем пользователя."""
    if not _is_admin(callback.from_user.id, config):
        await callback.answer()
        return
    try:
        order_id = int(callback.data.split(":")[-1])
    except ValueError:
        await callback.answer()
        return
    order = await session.get(Order, order_id)
    if not order:
        await callback.answer("Заказ не найден.", show_alert=True)
        return
    order.delivery_status = "completed"
    order.completed_at = datetime.utcnow()
    user = await session.get(User, order.user_id)
    await _log_admin(session, callback.from_user.id, "order_complete", f"order_id={order_id}")
    await session.flush()
    if user:
        await _notify_user_order_completed(callback.bot, user.telegram_id, order.id, order.stars_amount)
    await callback.answer("Заказ отмечен выполненным.")
    await callback.message.edit_reply_markup(reply_markup=admin_order_actions_kb(order_id))


@router.callback_query(F.data.startswith("admin:order:cancel:"))
async def admin_order_cancel(
    callback: CallbackQuery,
    session: AsyncSession,
    config: AppConfig,
):
    """Отмена заказа админом."""
    if not _is_admin(callback.from_user.id, config):
        await callback.answer()
        return
    try:
        order_id = int(callback.data.split(":")[-1])
    except ValueError:
        await callback.answer()
        return
    order = await session.get(Order, order_id)
    if not order:
        await callback.answer("Заказ не найден.", show_alert=True)
        return
    order.delivery_status = "cancelled"
    await _log_admin(session, callback.from_user.id, "order_cancel", f"order_id={order_id}")
    await callback.answer("Заказ отменён.")
    await callback.message.edit_reply_markup(reply_markup=admin_order_actions_kb(order_id))


@router.callback_query(F.data == "admin:stats")
async def admin_stats(callback: CallbackQuery, session: AsyncSession, config: AppConfig):
    """Статистика: пользователи, заказы, рефералы."""
    if not _is_admin(callback.from_user.id, config):
        await callback.answer()
        return
    users_count = (await session.execute(select(func.count(User.id)))).scalar() or 0
    orders_result = await session.execute(
        select(
            func.count(Order.id).label("total"),
            func.coalesce(func.sum(Order.stars_amount), 0).label("stars"),
            func.coalesce(func.sum(Order.price), 0).label("revenue"),
        ).where(Order.payment_status == "paid")
    )
    row = orders_result.one()
    revenue = float(row.revenue or 0)
    text = (
        f"📊 <b>Статистика</b>\n\n"
        f"👥 Пользователей: {users_count}\n"
        f"📋 Оплаченных заказов: {row.total or 0}\n"
        f"⭐ Stars продано: {row.stars or 0}\n"
        f"💵 Выручка (USD): {revenue:.2f}"
    )
    await callback.message.edit_text(text, reply_markup=admin_main_kb(), parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data == "admin:users")
async def admin_users(callback: CallbackQuery, session: AsyncSession, config: AppConfig):
    """Список пользователей (краткий)."""
    if not _is_admin(callback.from_user.id, config):
        await callback.answer()
        return
    result = await session.execute(select(User).order_by(User.created_at.desc()).limit(30))
    users = list(result.scalars().all())
    lines = ["👥 Последние пользователи:\n"]
    for u in users[:15]:
        block = "🚫" if u.is_blocked else ""
        lines.append(f"{block} {u.telegram_id} @{u.username or '—'}")
    await callback.message.edit_text("\n".join(lines), reply_markup=admin_main_kb())
    await callback.answer()


@router.callback_query(F.data.startswith("admin:user:block:"))
async def admin_user_block(callback: CallbackQuery, session: AsyncSession, config: AppConfig):
    """Заблокировать пользователя."""
    if not _is_admin(callback.from_user.id, config):
        await callback.answer()
        return
    try:
        user_id = int(callback.data.split(":")[-1])
    except ValueError:
        await callback.answer()
        return
    user = await session.get(User, user_id)
    if not user:
        await callback.answer("Пользователь не найден.", show_alert=True)
        return
    user.is_blocked = True
    await _log_admin(session, callback.from_user.id, "user_block", f"user_id={user_id}")
    await callback.answer("Пользователь заблокирован.")
    await callback.message.edit_reply_markup(reply_markup=admin_user_actions_kb(user_id, True))


@router.callback_query(F.data.startswith("admin:user:unblock:"))
async def admin_user_unblock(callback: CallbackQuery, session: AsyncSession, config: AppConfig):
    """Разблокировать пользователя."""
    if not _is_admin(callback.from_user.id, config):
        await callback.answer()
        return
    try:
        user_id = int(callback.data.split(":")[-1])
    except ValueError:
        await callback.answer()
        return
    user = await session.get(User, user_id)
    if not user:
        await callback.answer("Пользователь не найден.", show_alert=True)
        return
    user.is_blocked = False
    await _log_admin(session, callback.from_user.id, "user_unblock", f"user_id={user_id}")
    await callback.answer("Пользователь разблокирован.")
    await callback.message.edit_reply_markup(reply_markup=admin_user_actions_kb(user_id, False))


@router.callback_query(F.data == "admin:broadcast")
async def admin_broadcast_start(callback: CallbackQuery, state: FSMContext, config: AppConfig):
    """Начать рассылку: просим ввести текст."""
    if not _is_admin(callback.from_user.id, config):
        await callback.answer()
        return
    await state.set_state(BroadcastStates.waiting_text)
    await callback.message.edit_text("📤 Введите текст рассылки (одним сообщением):")
    await callback.answer()


@router.message(BroadcastStates.waiting_text, F.text)
async def admin_broadcast_send(message: Message, state: FSMContext, session: AsyncSession, config: AppConfig):
    """Отправка рассылки всем пользователям."""
    if not _is_admin(message.from_user.id, config):
        return
    if message.text == "/cancel":
        await state.clear()
        await message.answer("Отменено.")
        return
    result = await session.execute(select(User.telegram_id).where(User.is_blocked == False))
    tg_ids = [r[0] for r in result.all()]
    sent = 0
    for tid in tg_ids:
        try:
            await message.bot.send_message(tid, message.text)
            sent += 1
        except Exception:
            pass
    await state.clear()
    await message.answer(f"✅ Рассылка отправлена: {sent} из {len(tg_ids)}")
    await _log_admin(session, message.from_user.id, "broadcast", f"sent={sent}")


# Фильтр админ-роутера: только для админов
@router.callback_query(F.data.startswith("admin:"))
async def admin_guard(callback: CallbackQuery, config: AppConfig):
    """Общий guard: если callback admin: и пользователь не админ — не обрабатывать в других хендлерах."""
    pass  # каждый хендлер сам проверяет _is_admin
