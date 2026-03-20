"""
Админ-панель: заказы, статистика, пользователи, рассылка, блокировки.
"""
from datetime import datetime, timedelta
from aiogram import Router, F
from aiogram.types import CallbackQuery, Message, FSInputFile
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from bot.database.models import User, Order, Transaction, AdminLog
from bot.database.repository import (
    get_margin_percent,
    set_margin_percent,
    get_ton_per_100stars,
    set_ton_per_100stars,
)
from bot.keyboards import (
    admin_main_kb,
    admin_orders_filter_kb,
    admin_order_actions_kb,
    admin_user_actions_kb,
    admin_confirm_broadcast_kb,
    admin_price_back_kb,
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


class PriceStates(StatesGroup):
    entering_ton_per_100stars = State()
    entering_margin_percent = State()


async def _log_admin(session: AsyncSession, admin_id: int, action: str, details: str | None = None):
    """Логирование действия админа."""
    session.add(AdminLog(admin_id=admin_id, action=action, details=details))


@router.message(F.text == "/admin")
async def admin_entry(message: Message, state: FSMContext, session: AsyncSession, config: AppConfig):
    """Вход в админ-панель по команде /admin."""
    if not _is_admin(message.from_user.id, config):
        await message.answer("Доступ запрещён. Ваш ID не в списке администраторов.")
        return
    await state.clear()
    await message.answer("🔐 Админ-панель", reply_markup=admin_main_kb())


@router.callback_query(F.data == "admin:close")
async def admin_close(callback: CallbackQuery):
    """Закрыть админку."""
    await callback.message.delete()
    await callback.answer()


@router.callback_query(F.data == "admin:main")
async def admin_main(callback: CallbackQuery, state: FSMContext, config: AppConfig):
    """Главное меню админки."""
    if not _is_admin(callback.from_user.id, config):
        await callback.answer("Доступ запрещён.", show_alert=True)
        return
    await state.clear()
    from bot.utils.helpers import edit_or_send_text
    await edit_or_send_text(callback, "🔐 Админ-панель", admin_main_kb())
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
    # Под сообщением «Оплачен заказ» (админ/канал) убираем кнопку; в админ-панели — меняем на действия по заказу
    text = callback.message.text or callback.message.caption or ""
    if "🆕" in text and "Оплачен заказ" in text:
        try:
            from aiogram.types import InlineKeyboardMarkup
            await callback.message.edit_reply_markup(reply_markup=InlineKeyboardMarkup(inline_keyboard=[]))
        except Exception:
            await callback.message.edit_reply_markup(reply_markup=admin_order_actions_kb(order_id))
    else:
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
    """Экспорт всех пользователей в Excel (.xlsx)."""
    if not _is_admin(callback.from_user.id, config):
        await callback.answer()
        return
    await callback.answer("Готовлю Excel с пользователями...")

    result = await session.execute(select(User).order_by(User.created_at.desc()))
    users = list(result.scalars().all())

    # Локальные импорты, чтобы не грузить openpyxl без надобности
    import os
    import tempfile

    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = "Users"

    headers = [
        "id",
        "telegram_id",
        "username",
        "balance_stars",
        "balance_usd",
        "referral_code",
        "referred_by",
        "referral_reward_total",
        "referrals_count",
        "is_blocked",
        "created_at",
    ]
    ws.append(headers)

    for u in users:
        ws.append(
            [
                u.id,
                u.telegram_id,
                u.username or "",
                float(u.balance_stars or 0),
                float(u.balance_usd or 0),
                u.referral_code or "",
                u.referred_by if u.referred_by is not None else "",
                float(u.referral_reward_total or 0),
                u.referrals_count,
                bool(u.is_blocked),
                u.created_at,
            ]
        )

    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx")
    tmp_path = tmp.name
    tmp.close()
    try:
        wb.save(tmp_path)
        await callback.bot.send_document(
            chat_id=callback.from_user.id,
            document=FSInputFile(tmp_path),
            caption=f"✅ Excel экспорт: пользователей {len(users)}",
        )
    finally:
        try:
            os.unlink(tmp_path)
        except Exception:
            pass

    # Вернёмся в главное меню админки
    await callback.message.edit_text("🔐 Экспорт готов. Вы в админ-меню.", reply_markup=admin_main_kb())


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


@router.callback_query(F.data == "admin:price")
async def admin_price_show(callback: CallbackQuery, state: FSMContext, session: AsyncSession, config: AppConfig):
    """Показать текущую цену Stars (через TON за 100 ⭐) и попросить ввести новую."""
    if not _is_admin(callback.from_user.id, config):
        await callback.answer("Доступ запрещён.", show_alert=True)
        return

    ton_per_100stars = await get_ton_per_100stars(session, default=None)
    margin_percent = await get_margin_percent(session, default=0.0)

    # Пытаемся вывести справочные USD/₽ значения, если доступен TON/USD
    usd_per_star = None
    rub_per_star = None
    ton_per_star_with_margin = None
    if ton_per_100stars:
        try:
            from bot.services.price_engine import PriceEngine
            engine = PriceEngine(config.price)
            ton_usd = await engine.get_ton_usd()
            ton_rub = await engine.get_ton_rub()
            if ton_usd and ton_usd > 0:
                ton_per_star_base = ton_per_100stars / 100.0
                ton_per_star_with_margin = ton_per_star_base * (1.0 + margin_percent / 100.0)
                usd_per_star = ton_per_star_with_margin * ton_usd
                if ton_rub and ton_rub > 0:
                    rub_per_star = ton_per_star_with_margin * ton_rub
                else:
                    rub_per_star = usd_per_star * (getattr(config, "rub_per_usd", 100) or 100)
        except Exception:
            pass

    await state.set_state(PriceStates.entering_ton_per_100stars)
    await callback.message.edit_text(
        "💎 <b>Цена Stars</b>\n\n"
        + (f"Сейчас: 100 ⭐ = <b>{ton_per_100stars:.6f} TON</b>\n" if ton_per_100stars else "Сейчас: не задано\n")
        + f"Маржа: <b>{margin_percent:.2f}%</b>\n\n"
        + (
            "1 ⭐ с маржой: "
            f"<b>{ton_per_star_with_margin:.6f} TON</b> / "
            f"<b>{usd_per_star:.4f}$</b> / "
            f"<b>{rub_per_star:.0f} ₽</b>\n\n"
            if usd_per_star is not None and rub_per_star is not None and ton_per_star_with_margin is not None
            else "\n"
        )
        + "Введите цену за <b>100 ⭐</b> в TON (одно число), например <code>0.751</code>:",
        reply_markup=admin_price_back_kb(),
        parse_mode="HTML",
    )
    await callback.answer()

@router.message(PriceStates.entering_ton_per_100stars, F.text)
async def admin_price_save_ton(message: Message, state: FSMContext, session: AsyncSession, config: AppConfig):
    """Сохранить введённую цену за 100 ⭐ в TON и попросить маржу."""
    if not _is_admin(message.from_user.id, config):
        return
    text = (message.text or "").strip().replace(",", ".")
    try:
        ton_per_100stars = float(text)
    except ValueError:
        await message.answer("Введите число, например 0.751")
        return
    if ton_per_100stars <= 0:
        await message.answer("Цена должна быть больше 0.")
        return
    await state.update_data(ton_per_100stars=ton_per_100stars)
    await state.set_state(PriceStates.entering_margin_percent)
    await message.answer("Введите маржу в % (например 10):")


@router.message(PriceStates.entering_margin_percent, F.text)
async def admin_price_save_margin(message: Message, state: FSMContext, session: AsyncSession, config: AppConfig):
    """Сохранить маржу и применить новую цену."""
    if not _is_admin(message.from_user.id, config):
        return
    text = (message.text or "").strip().replace(",", ".")
    try:
        margin_percent = float(text)
    except ValueError:
        await message.answer("Введите число, например 10")
        return
    if margin_percent < 0 or margin_percent > 500:
        await message.answer("Маржа должна быть в диапазоне 0..500%.")
        return

    data = await state.get_data()
    ton_per_100stars = data.get("ton_per_100stars")
    if not ton_per_100stars or float(ton_per_100stars) <= 0:
        await message.answer("Сначала задайте цену за 100 ⭐.")
        return

    ton_per_100stars = float(ton_per_100stars)
    await set_ton_per_100stars(session, ton_per_100stars)
    await set_margin_percent(session, margin_percent)
    await session.commit()
    await _log_admin(
        session,
        message.from_user.id,
        "price_change",
        f"ton_per_100stars={ton_per_100stars}, margin_percent={margin_percent}",
    )

    await state.clear()

    # Пытаемся посчитать USD/₽ для удобства админа
    usd_per_star = None
    rub_per_star = None
    ton_per_star_with_margin = ton_per_100stars / 100.0 * (1.0 + margin_percent / 100.0)
    try:
        from bot.services.price_engine import PriceEngine
        engine = PriceEngine(config.price)
        ton_usd = await engine.get_ton_usd()
        ton_rub = await engine.get_ton_rub()
        if ton_usd and ton_usd > 0:
            usd_per_star = ton_per_star_with_margin * ton_usd
            if ton_rub and ton_rub > 0:
                rub_per_star = ton_per_star_with_margin * ton_rub
            else:
                rub_per_star = usd_per_star * (getattr(config, "rub_per_usd", 100) or 100)
    except Exception:
        pass

    if usd_per_star is not None and rub_per_star is not None:
        await message.answer(
            f"✅ Цена обновлена.\n"
            f"100 ⭐ = {ton_per_100stars:.6f} TON\n"
            f"Маржа: {margin_percent:.2f}%\n\n"
            f"Итого 1 ⭐: {ton_per_star_with_margin:.6f} TON / {usd_per_star:.4f}$ / {rub_per_star:.0f} ₽"
        )
    else:
        await message.answer(
            f"✅ Цена обновлена.\n"
            f"100 ⭐ = {ton_per_100stars:.6f} TON\n"
            f"Маржа: {margin_percent:.2f}%\n\n"
            f"Итого 1 ⭐: {ton_per_star_with_margin:.6f} TON (USD/₽ временно не посчитаны — нет курса TON/USD)"
        )


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
