"""
Покупка Telegram Premium: выбор получателя -> срок -> выбор оплаты.

Реализация построена по аналогии с покупкой Stars: создаём Order, просим оплату
и после оплаты админ вручную подтверждает выполнение.
"""

from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.filters import StateFilter
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.database.models import User, Order
from bot.database.repository import (
    get_or_create_user as get_user,
    get_premium_prices_usd,
)
from bot.keyboards import (
    back_to_menu_kb,
    premium_recipient_choice_kb,
    premium_back_to_recipient_kb,
    premium_duration_kb,
    payment_method_kb,
    confirm_order_kb,
    topup_methods_kb,
    cryptobot_pay_button_kb,
    sbp_pay_button_kb,
    ton_pay_button_kb,
)
from bot.config import AppConfig
from bot.services.price_engine import PriceEngine
from bot.services.antifraud import AntifraudService
from bot.services.freekassa_service import FreeKassaService
from bot.services.ton_service import TonService
from bot.services.cryptobot_service import CryptoBotService
from bot.utils.helpers import format_price, edit_or_send_text
from bot.utils.logger import get_logger

logger = get_logger(__name__)
router = Router(name="premium")


class PremiumStates(StatesGroup):
    choosing_recipient = State()
    entering_recipient_username = State()
    choosing_duration = State()
    choosing_payment = State()
    confirmed = State()


def _get_price_engine(config: AppConfig) -> PriceEngine:
    return PriceEngine(config.price)


def _get_antifraud(config: AppConfig) -> AntifraudService:
    return AntifraudService(config.antifraud)


def _normalize_username(username: str) -> str:
    text = (username or "").strip()
    if text.startswith("@"):
        text = text[1:]
    return text


@router.callback_query(F.data == "menu:premium")
async def start_premium(callback: CallbackQuery, state: FSMContext):
    """Начало покупки Premium: выбор получателя."""
    await state.clear()
    await state.set_state(PremiumStates.choosing_recipient)
    await edit_or_send_text(
        callback,
        "✨ <b>Выбор имени пользователя</b>\n\n"
        "❗️ Важно: У пользователя не должно быть активной подписки Premium\n\n"
        "Выберите, кому вы хотите купить Telegram Premium",
        premium_recipient_choice_kb(),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(PremiumStates.choosing_recipient, F.data == "premium:recipient_self")
async def premium_for_self(callback: CallbackQuery, state: FSMContext, session: AsyncSession):
    """Купить Premium себе."""
    # Визуальная подготовка, проверку подписки сделаем в момент ввода/выбора срока.
    await state.set_state(PremiumStates.choosing_duration)
    username = callback.from_user.username or callback.from_user.first_name or "Вы"
    display = f"@{username}" if callback.from_user.username else username
    await state.update_data(
        recipient_type="self",
        recipient_username=None,
        recipient_display=display,
    )
    prices = await get_premium_prices_usd(session)
    await callback.message.edit_text(
        "👤 Получатель: "
        f"{display}\n\n"
        "💫 Выберите срок премиума, который хотите купить:",
        reply_markup=premium_duration_kb(prices),
    )
    await callback.answer()


@router.callback_query(PremiumStates.choosing_recipient, F.data == "premium:recipient_gift")
async def premium_for_gift(callback: CallbackQuery, state: FSMContext):
    """Подарить Premium: ввод @username получателя."""
    await state.set_state(PremiumStates.entering_recipient_username)
    await callback.message.edit_text(
        "👤 Введите @username пользователя, которому вы хотите подарить Telegram Premium:",
        reply_markup=premium_back_to_recipient_kb(),
        parse_mode=None,
    )
    await callback.answer()


@router.callback_query(PremiumStates.entering_recipient_username, F.data == "premium:back_recipient")
@router.callback_query(PremiumStates.choosing_duration, F.data == "premium:back_recipient")
@router.callback_query(PremiumStates.choosing_payment, F.data == "premium:back_recipient")
async def premium_back_to_recipient(callback: CallbackQuery, state: FSMContext):
    """Назад к выбору получателя."""
    await state.set_state(PremiumStates.choosing_recipient)
    await edit_or_send_text(
        callback,
        "✨ <b>Выбор имени пользователя</b>\n\n"
        "❗️ Важно: У пользователя не должно быть активной подписки Premium\n\n"
        "Выберите, кому вы хотите купить Telegram Premium",
        premium_recipient_choice_kb(),
        parse_mode="HTML",
    )
    await callback.answer()


@router.message(PremiumStates.entering_recipient_username, F.text)
async def premium_process_recipient_username(message: Message, state: FSMContext, session: AsyncSession):
    """Обработка введённого @username для подарка."""
    username = _normalize_username(message.text)
    if not username or len(username) < 2:
        await message.answer("Введите корректный username (например @username или username).")
        return
    if len(username) > 32:
        await message.answer("Слишком длинный username. Введите снова:")
        return

    db_recipient = await session.execute(select(User).where(User.username == username))
    recipient_user = db_recipient.scalar_one_or_none()
    recipient_display = f"@{username}"

    if not recipient_user:
        await message.answer(
            "❌ Пользователь не найден в базе бота.\n"
            "Попросите его сначала зайти в бота командой `/start`, затем повторите покупку Premium.",
            reply_markup=premium_recipient_choice_kb(),
            parse_mode="Markdown",
        )
        await state.set_state(PremiumStates.choosing_recipient)
        return

    # Проверяем активность подписки Premium у получателя (если нашли пользователя в БД).
    premium_until = getattr(recipient_user, "premium_until", None)
    if premium_until:
        # premium_until хранится как datetime (UTC/naive зависит от БД), поэтому сравниваем аккуратно.
        from datetime import datetime, timezone

        now = datetime.now(timezone.utc).replace(tzinfo=None)
        if premium_until.replace(tzinfo=None) > now:
            await message.answer(
                "❌ У этого пользователя уже активна подписка Premium.\n"
                "Выберите другого получателя или срок.",
                reply_markup=premium_recipient_choice_kb(),
            )
            await state.set_state(PremiumStates.choosing_recipient)
            return

    await state.update_data(
        recipient_type="gift",
        recipient_username=username,
        recipient_display=recipient_display,
    )
    await state.set_state(PremiumStates.choosing_duration)

    prices = await get_premium_prices_usd(session)
    await message.answer(
        f"👤 Получатель: {recipient_display}\n\n"
        "💫 Выберите срок премиума, который хотите купить:",
        reply_markup=premium_duration_kb(prices),
    )


@router.callback_query(PremiumStates.choosing_duration, F.data.startswith("premium:duration:"))
async def premium_choose_duration(callback: CallbackQuery, state: FSMContext, session: AsyncSession, config: AppConfig):
    """Выбор срока Premium (3/6/12 месяцев) и отображение суммы/выбор оплаты."""
    try:
        months = int(callback.data.split(":")[-1])
    except ValueError:
        await callback.answer("Ошибка срока.", show_alert=True)
        return

    prices = await get_premium_prices_usd(session)
    if months not in prices:
        await callback.answer("Цены Premium ещё не настроены администратором.", show_alert=True)
        return

    price_usd = float(prices[months])
    engine = _get_price_engine(config)
    ton_usd = await engine.get_ton_usd()
    ton_rub = await engine.get_ton_rub()
    rub_per_usd = getattr(config, "rub_per_usd", 100) or 100
    if not ton_usd or ton_usd <= 0:
        ton_usd = 1.33
    if not ton_rub or ton_rub <= 0:
        # если тон_руб недоступен — считаем RUB через rub_per_usd.
        total_rub = round(price_usd * rub_per_usd, 2)
        ton_amount = None
    else:
        ton_amount = price_usd / ton_usd
        total_rub = round(ton_amount * ton_rub, 2)

    data = await state.get_data()
    recipient_type = data.get("recipient_type")
    recipient_username = data.get("recipient_username")

    # Проверяем, что у получателя нет активной подписки (если это подарок).
    if recipient_type == "gift" and recipient_username:
        recipient_user = await session.execute(select(User).where(User.username == recipient_username))
        recipient_user = recipient_user.scalar_one_or_none()
        if recipient_user:
            premium_until = getattr(recipient_user, "premium_until", None)
            if premium_until:
                from datetime import datetime, timezone

                now = datetime.now(timezone.utc).replace(tzinfo=None)
                if premium_until.replace(tzinfo=None) > now:
                    await callback.answer("У получателя уже есть Premium.", show_alert=True)
                    return

    # Берём баланс покупателя (внутренний).
    result = await session.execute(select(User).where(User.telegram_id == callback.from_user.id))
    db_user = result.scalar_one_or_none()
    if not db_user:
        db_user, _ = await get_user(session, callback.from_user.id, callback.from_user.username)
        await session.flush()
    balance_usd = (db_user.balance_usd or 0.0) or 0.0

    # Для покупки "себе" проверяем, что у покупателя нет активной подписки Premium.
    if recipient_type == "self":
        premium_until = getattr(db_user, "premium_until", None)
        if premium_until:
            from datetime import datetime, timezone

            now = datetime.now(timezone.utc).replace(tzinfo=None)
            if premium_until.replace(tzinfo=None) > now:
                await callback.answer("У вас уже активна подписка Premium.", show_alert=True)
                return

    quote_usd = price_usd
    quote_ton = (quote_usd / ton_usd) if ton_amount is not None else None

    if balance_usd < quote_usd:
        shortage_usd = quote_usd - balance_usd
        if ton_rub and ton_usd and ton_rub > 0:
            shortage_rub = round((shortage_usd / max(ton_usd, 1e-9)) * ton_rub, 2)
        else:
            shortage_rub = round(shortage_usd * rub_per_usd, 2)

        await state.update_data(
            premium_months=months,
            quote_usd=quote_usd,
            quote_ton=quote_ton,
            shortage_usd=shortage_usd,
            recipient_type=recipient_type,
            recipient_username=recipient_username,
        )
        await state.set_state(PremiumStates.choosing_payment)

        text = (
            f"👑 Premium — {months} месяцев — стоимость заказа: {quote_usd:.2f}$ ({total_rub:.2f} ₽)\n\n"
            f"❌ Вам не хватает {shortage_usd:.2f}$ ({shortage_rub:.2f} ₽) на балансе\n\n"
            f"💰 На балансе: {balance_usd:.2f}$ · К оплате: {shortage_usd:.2f}$ ({shortage_rub:.2f} ₽)\n\n"
            "👇🏻 Выберите способ оплаты из предложенных: 👇🏻\n\n"
            "💳 СБП — оплата рублями через QR-код\n"
            "💳 Карты — оплата рублями банковской картой\n"
            "🔹 TON — оплата через нативный токен сети TON\n"
            "💸 USDT TON — оплата через USDT в сети TON\n"
            "💎 Cryptobot — оплата через Cryptobot\n"
            "🔸 Другая криптовалюта — оплата в любой криптовалюте"
        )
        await callback.message.answer(text, reply_markup=topup_methods_kb())
        await callback.answer()
        return

    await state.update_data(
        premium_months=months,
        quote_usd=quote_usd,
        quote_ton=quote_ton,
    )
    await state.set_state(PremiumStates.choosing_payment)

    ton_part = f" (~ {quote_ton:.4f} TON)" if quote_ton else ""
    text = (
        f"👑 <b>Telegram Premium — {months} месяцев</b>\n\n"
        f"Стоимость: {format_price(quote_usd)} ({total_rub:.2f} ₽){ton_part}\n\n"
        f"💰 На балансе: {balance_usd:.2f}$\n\n"
        "Выберите способ оплаты:"
    )
    await callback.message.answer(
        text,
        reply_markup=payment_method_kb(show_balance=True),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(PremiumStates.choosing_payment, F.data == "pay:balance")
async def premium_choose_balance(callback: CallbackQuery, state: FSMContext, session: AsyncSession, config: AppConfig):
    """Оплатить Premium с баланса."""
    data = await state.get_data()
    premium_months = data.get("premium_months")
    quote_usd = data.get("quote_usd") or 0.0
    if not premium_months or quote_usd <= 0:
        await callback.answer("Сессия истекла. Начните заново.", show_alert=True)
        return

    result = await session.execute(select(User).where(User.telegram_id == callback.from_user.id))
    db_user = result.scalar_one_or_none()
    if not db_user:
        db_user, _ = await get_user(session, callback.from_user.id, callback.from_user.username)
        await session.flush()

    balance_usd = (db_user.balance_usd or 0.0) or 0.0
    if balance_usd < quote_usd:
        await callback.answer("Недостаточно средств на балансе.", show_alert=True)
        return

    antifraud = _get_antifraud(config)
    can_order, msg = await antifraud.can_create_order(session, db_user.id)
    if not can_order:
        await callback.answer(msg, show_alert=True)
        return

    data = await state.get_data()
    recipient_username = data.get("recipient_username") if data.get("recipient_type") == "gift" else None
    recipient_display = data.get("recipient_display") if data.get("recipient_type") == "gift" else None

    order = Order(
        user_id=db_user.id,
        username=callback.from_user.username,
        recipient_username=recipient_username,
        stars_amount=0,
        premium_months=int(premium_months),
        order_type="premium",
        price=float(quote_usd),
        payment_method="balance",
        payment_status="pending",
        delivery_status="waiting",
        balance_used=float(quote_usd),
    )
    session.add(order)
    await session.flush()
    from bot.handlers.payments import complete_order_payment

    await complete_order_payment(session, callback.bot, config, order)
    await session.commit()
    await state.clear()

    await callback.message.edit_text(
        f"✅ Заказ #{order.id} оплачен с баланса ({format_price(quote_usd)}).\n\n"
        f"Ожидайте активации Premium на {premium_months} месяцев.",
        reply_markup=back_to_menu_kb(),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(
    PremiumStates.choosing_payment,
    F.data.in_(["pay:cryptobot", "pay:ton", "pay:freekassa"]),
)
async def premium_choose_payment(callback: CallbackQuery, state: FSMContext, session: AsyncSession, config: AppConfig):
    """Выбор способа оплаты: cryptobot, ton, freekassa."""
    method = callback.data.replace("pay:", "")
    if method not in ("cryptobot", "ton", "freekassa"):
        await callback.answer("Неизвестный способ.", show_alert=True)
        return

    data = await state.get_data()
    premium_months = data.get("premium_months")
    quote_usd = data.get("quote_usd")
    quote_ton = data.get("quote_ton")
    if not premium_months or quote_usd is None:
        await callback.answer("Сессия истекла. Начните заново.", show_alert=True)
        return

    result = await session.execute(select(User).where(User.telegram_id == callback.from_user.id))
    db_user = result.scalar_one_or_none()
    if not db_user:
        db_user, _ = await get_user(session, callback.from_user.id, callback.from_user.username)
        await session.flush()

    antifraud = _get_antifraud(config)
    can_order, msg = await antifraud.can_create_order(session, db_user.id)
    if not can_order:
        await callback.answer(msg, show_alert=True)
        return

    recipient_username = data.get("recipient_username") if data.get("recipient_type") == "gift" else None

    order = Order(
        user_id=db_user.id,
        username=callback.from_user.username,
        recipient_username=recipient_username,
        stars_amount=0,
        premium_months=int(premium_months),
        order_type="premium",
        price=float(quote_usd),
        payment_method=method,
        payment_status="pending",
        delivery_status="waiting",
        balance_used=0.0,
    )
    session.add(order)
    await session.flush()

    await state.update_data(order_id=order.id, payment_method=method, quote_ton=quote_ton)
    await state.set_state(PremiumStates.confirmed)

    method_name = {"cryptobot": "CryptoBot (Premium)", "ton": "Toncoin", "freekassa": "FreeKassa"}[method]
    text = (
        f"📋 <b>Подтверждение заказа #{order.id}</b>\n\n"
        f"👑 Premium: {premium_months} месяцев\n"
        f"💵 {format_price(float(quote_usd))}\n"
        f"Способ: {method_name}\n\n"
        "Подтвердить и перейти к оплате?"
    )
    await callback.message.edit_text(text, reply_markup=confirm_order_kb(order.id), parse_mode="HTML")
    await callback.answer()


@router.callback_query(PremiumStates.confirmed, F.data.startswith("confirm_order:"))
async def premium_confirm_and_pay(callback: CallbackQuery, state: FSMContext, session: AsyncSession, config: AppConfig):
    """После подтверждения: создаём инвойс/ссылку Premium."""
    try:
        order_id = int(callback.data.split(":")[1])
    except (IndexError, ValueError):
        await callback.answer("Ошибка.", show_alert=True)
        return

    data = await state.get_data()
    if data.get("order_id") != order_id:
        await callback.answer("Сессия не совпадает.", show_alert=True)
        return

    order = await session.get(Order, order_id)
    if not order or order.payment_status == "paid":
        await callback.answer("Заказ уже оплачен или не найден.", show_alert=True)
        return

    method = order.payment_method
    quote_usd = float(order.price or 0.0)

    # Получаем курсы для TON/RUB где нужно.
    engine = _get_price_engine(config)
    ton_usd = await engine.get_ton_usd()
    ton_rub = await engine.get_ton_rub()
    rub_per_usd = getattr(config, "rub_per_usd", 100) or 100
    if not ton_usd or ton_usd <= 0:
        ton_usd = 1.33

    if method == "freekassa":
        fk = FreeKassaService(config.freekassa)
        notification_url = (
            f"{config.webhook_base_url.rstrip('/')}/webhook/freekassa" if config.webhook_base_url else None
        )
        if ton_rub and ton_rub > 0:
            ton_amount = quote_usd / ton_usd
            amount_rub = round(ton_amount * ton_rub, 2)
        else:
            amount_rub = round(quote_usd * rub_per_usd, 2)

        pay_url = fk.create_order(
            amount=amount_rub,
            currency="RUB",
            order_id=str(order.id),
            notification_url=notification_url,
        )
        if not pay_url:
            await callback.answer("Ошибка создания платежа FreeKassa.", show_alert=True)
            return
        order.external_payment_id = str(order.id)
        await session.flush()
        await callback.message.edit_text(
            f"✅ Заказ #{order.id} создан.\n\n"
            f"Оплатите по ссылке:\n{pay_url}\n\n"
            f"После оплаты мы уведомим вас.",
            reply_markup=back_to_menu_kb(),
        )
        await state.clear()
        await callback.answer()
        return

    if method == "ton":
        ton = TonService(config.ton)
        if not ton.enabled:
            await callback.answer("Оплата TON временно недоступна.", show_alert=True)
            return
        if not ton_rub or ton_rub <= 0:
            # TON/RUB не обязателен для deep link.
            pass
        quote_ton = data.get("quote_ton")
        if not quote_ton:
            quote_ton = quote_usd / max(float(ton_usd), 1e-9)
        link = ton.build_payment_link(float(quote_ton), f"order_{order.id}")
        if not link:
            await callback.answer("Не удалось сформировать ссылку TON.", show_alert=True)
            return
        order.external_payment_id = f"ton_{order.id}"
        await session.flush()
        await callback.message.edit_text(
            f"✅ Заказ #{order.id}\n\n"
            f"Переведите {quote_ton:.4f} TON по ссылке:\n{link}\n\n"
            f"После подтверждения транзакции заказ будет выполнен.",
            reply_markup=back_to_menu_kb(),
        )
        await state.clear()
        await callback.answer()
        return

    if method == "cryptobot":
        crypto = CryptoBotService(config.cryptobot)
        if not crypto.enabled:
            await callback.answer("CryptoBot временно недоступен.", show_alert=True)
            return
        result = await crypto.create_invoice_usdt(
            amount_usd=quote_usd * 1.03,
            description=f"Premium #{order.id} — {order.premium_months} месяцев",
            payload=f"order_{order.id}",
        )
        if not result:
            await callback.answer("Ошибка создания счёта CryptoBot.", show_alert=True)
            return
        invoice_id = result.get("invoice_id")
        pay_url = result.get("mini_app_invoice_url") or result.get("bot_invoice_url") or result.get("pay_url")
        if invoice_id is not None:
            order.external_payment_id = str(invoice_id)
            await session.flush()

        if not pay_url:
            await callback.answer("Не удалось получить ссылку CryptoBot.", show_alert=True)
            return

        await callback.message.edit_text(
            f"⚡️ Оплата заказа #{order.id}\n"
            f"👑 Premium: {order.premium_months} месяцев\n"
            f"💵 К оплате: {quote_usd * 1.03:.2f}$ (USDT)\n"
            f"❗️ Комиссия Cryptobot ~3%\n"
            f"ID счёта: <code>{invoice_id}</code>\n\n"
            f"💳 Для оплаты нажмите «Перейти к оплате» и следуйте дальнейшим инструкциям\n\n"
            f"Счёт для оплаты действителен 60 минут!",
            reply_markup=cryptobot_pay_button_kb(pay_url),
            parse_mode="HTML",
        )
        await state.clear()
        await callback.answer()
        return

    await callback.answer("Метод оплаты недоступен.", show_alert=True)


# --- Оплата при недостатке баланса (topup:*) ---
@router.callback_query(PremiumStates.choosing_payment, F.data == "topup:cryptobot")
async def premium_topup_cryptobot(callback: CallbackQuery, state: FSMContext, session: AsyncSession, config: AppConfig):
    """Создаём внешнюю оплату CryptoBot (USDT) для Premium при недостатке баланса."""
    await callback.answer("Создаём счёт...")
    data = await state.get_data()
    quote_usd = float(data.get("quote_usd") or 0.0)
    shortage_usd = float(data.get("shortage_usd") or 0.0)
    premium_months = data.get("premium_months")
    if quote_usd <= 0 or not premium_months:
        await callback.answer("Сессия истекла. Начните заново.", show_alert=True)
        return

    if shortage_usd <= 0:
        shortage_usd = quote_usd

    # Забираем актуальный баланс.
    result = await session.execute(select(User).where(User.telegram_id == callback.from_user.id))
    db_user = result.scalar_one_or_none()
    if not db_user:
        db_user, _ = await get_user(session, callback.from_user.id, callback.from_user.username)
        await session.flush()
    balance_usd = float(db_user.balance_usd or 0.0)

    amount_to_pay = min(shortage_usd, quote_usd - balance_usd) if balance_usd < quote_usd else quote_usd
    if amount_to_pay <= 0:
        amount_to_pay = quote_usd
    balance_used = quote_usd - amount_to_pay
    if balance_used < 0:
        balance_used = 0.0

    amount_to_pay_with_fee = amount_to_pay * 1.03

    antifraud = _get_antifraud(config)
    can_order, msg = await antifraud.can_create_order(session, db_user.id)
    if not can_order:
        await callback.answer(msg, show_alert=True)
        return

    recipient_username = data.get("recipient_username") if data.get("recipient_type") == "gift" else None

    order = Order(
        user_id=db_user.id,
        username=callback.from_user.username,
        recipient_username=recipient_username,
        stars_amount=0,
        premium_months=int(premium_months),
        order_type="premium",
        price=float(quote_usd),
        payment_method="cryptobot",
        payment_status="pending",
        delivery_status="waiting",
        balance_used=float(balance_used),
    )
    session.add(order)
    await session.flush()

    crypto = CryptoBotService(config.cryptobot)
    if not crypto.enabled:
        await callback.answer("CryptoBot временно недоступен.", show_alert=True)
        return

    result_inv = await crypto.create_invoice_usdt(
        amount_usd=amount_to_pay_with_fee,
        description=f"Premium #{order.id} — {order.premium_months} месяцев",
        payload=f"order_{order.id}",
    )
    if not result_inv:
        await callback.answer("Ошибка создания счёта CryptoBot.", show_alert=True)
        return

    invoice_id = result_inv.get("invoice_id")
    if invoice_id is not None:
        order.external_payment_id = str(invoice_id)
        await session.flush()
    pay_url = result_inv.get("mini_app_invoice_url") or result_inv.get("bot_invoice_url") or result_inv.get("pay_url")
    if not pay_url:
        await callback.answer("Не удалось получить ссылку CryptoBot.", show_alert=True)
        return

    await state.update_data(order_id=order.id, payment_method="cryptobot")
    await state.set_state(PremiumStates.confirmed)

    await callback.message.edit_text(
        f"⚡️ К оплате: {amount_to_pay_with_fee:.2f}$ (USDT)"
        + (f" (с баланса списано: {balance_used:.2f}$)" if balance_used > 0 else "")
        + "\n❗️ Комиссия Cryptobot ~3%\n"
        f"ID счёта: <code>{invoice_id}</code>\n\n"
        "💳 Нажмите «Перейти к оплате». Счёт действителен 60 минут!",
        reply_markup=cryptobot_pay_button_kb(pay_url),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(PremiumStates.choosing_payment, F.data == "topup:ton")
async def premium_topup_ton(callback: CallbackQuery, state: FSMContext, session: AsyncSession, config: AppConfig):
    """Создаём external TON-ссылку для Premium при недостатке баланса."""
    await callback.answer("Создаём ссылку...")
    data = await state.get_data()
    quote_usd = float(data.get("quote_usd") or 0.0)
    shortage_usd = float(data.get("shortage_usd") or 0.0)
    premium_months = data.get("premium_months")
    if quote_usd <= 0 or not premium_months:
        await callback.answer("Сессия истекла. Начните заново.", show_alert=True)
        return

    if shortage_usd <= 0:
        shortage_usd = quote_usd

    result = await session.execute(select(User).where(User.telegram_id == callback.from_user.id))
    db_user = result.scalar_one_or_none()
    if not db_user:
        db_user, _ = await get_user(session, callback.from_user.id, callback.from_user.username)
        await session.flush()
    balance_usd = float(db_user.balance_usd or 0.0)

    amount_to_pay = min(shortage_usd, quote_usd - balance_usd) if balance_usd < quote_usd else quote_usd
    if amount_to_pay <= 0:
        amount_to_pay = quote_usd
    balance_used = quote_usd - amount_to_pay
    if balance_used < 0:
        balance_used = 0.0

    antifraud = _get_antifraud(config)
    can_order, msg = await antifraud.can_create_order(session, db_user.id)
    if not can_order:
        await callback.answer(msg, show_alert=True)
        return

    recipient_username = data.get("recipient_username") if data.get("recipient_type") == "gift" else None

    order = Order(
        user_id=db_user.id,
        username=callback.from_user.username,
        recipient_username=recipient_username,
        stars_amount=0,
        premium_months=int(premium_months),
        order_type="premium",
        price=float(quote_usd),
        payment_method="ton",
        payment_status="pending",
        delivery_status="waiting",
        balance_used=float(balance_used),
    )
    session.add(order)
    await session.flush()

    ton = TonService(config.ton)
    if not ton.enabled:
        await callback.answer("TON временно недоступен.", show_alert=True)
        return

    engine = _get_price_engine(config)
    ton_usd = await engine.get_ton_usd()
    if not ton_usd or ton_usd <= 0:
        ton_usd = 1.33
    amount_ton = float(amount_to_pay) / float(ton_usd)

    link = ton.build_payment_link(amount_ton, f"order_{order.id}")
    if not link:
        await callback.answer("Не удалось сформировать ссылку TON.", show_alert=True)
        return

    order.external_payment_id = f"ton_{order.id}"
    await session.flush()

    await state.update_data(order_id=order.id, payment_method="ton", quote_ton=amount_ton)
    await state.set_state(PremiumStates.confirmed)

    wallet = config.ton.wallet_address or ""
    await callback.message.edit_text(
        f"⚡️ К оплате: {amount_to_pay:.2f}$ (~ {amount_ton:.4f} TON)"
        + (f" (с баланса списано: {balance_used:.2f}$)" if balance_used > 0 else "")
        + f"\nID счёта: <code>{order.id}</code>\n\n"
        f"💷 Переведите ТОЧНУЮ СУММУ: {amount_ton:.4f} TON\n\n"
        f"👛 Кошелёк:\n<code>{wallet}</code>\n\n"
        "После транзакции бот подтвердит платёж. Счёт действителен 60 минут!",
        reply_markup=ton_pay_button_kb(link),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(PremiumStates.choosing_payment, F.data == "topup:sbp")
async def premium_topup_sbp(callback: CallbackQuery, state: FSMContext, session: AsyncSession, config: AppConfig):
    """Создаём внешнюю оплату FreeKassa SCI (SBP) для Premium при недостатке баланса."""
    await callback.answer("Создаём ссылку на оплату...")
    data = await state.get_data()
    quote_usd = float(data.get("quote_usd") or 0.0)
    shortage_usd = float(data.get("shortage_usd") or 0.0)
    premium_months = data.get("premium_months")
    if quote_usd <= 0 or not premium_months:
        await callback.answer("Сессия истекла. Начните заново.", show_alert=True)
        return

    if shortage_usd <= 0:
        shortage_usd = quote_usd

    result = await session.execute(select(User).where(User.telegram_id == callback.from_user.id))
    db_user = result.scalar_one_or_none()
    if not db_user:
        db_user, _ = await get_user(session, callback.from_user.id, callback.from_user.username)
        await session.flush()
    balance_usd = float(db_user.balance_usd or 0.0)

    amount_to_pay = min(shortage_usd, quote_usd - balance_usd) if balance_usd < quote_usd else quote_usd
    if amount_to_pay <= 0:
        amount_to_pay = quote_usd
    balance_used = quote_usd - amount_to_pay
    if balance_used < 0:
        balance_used = 0.0

    antifraud = _get_antifraud(config)
    can_order, msg = await antifraud.can_create_order(session, db_user.id)
    if not can_order:
        await callback.answer(msg, show_alert=True)
        return

    recipient_username = data.get("recipient_username") if data.get("recipient_type") == "gift" else None

    order = Order(
        user_id=db_user.id,
        username=callback.from_user.username,
        recipient_username=recipient_username,
        stars_amount=0,
        premium_months=int(premium_months),
        order_type="premium",
        price=float(quote_usd),
        payment_method="freekassa",
        payment_status="pending",
        delivery_status="waiting",
        balance_used=float(balance_used),
    )
    session.add(order)
    await session.flush()

    engine = _get_price_engine(config)
    ton_usd = await engine.get_ton_usd()
    ton_rub = await engine.get_ton_rub()
    rub_per_usd_dynamic = (ton_rub / ton_usd) if (ton_rub and ton_usd and ton_usd > 0) else None
    if rub_per_usd_dynamic:
        amount_rub = round(amount_to_pay * rub_per_usd_dynamic, 2)
    else:
        rub_per_usd = getattr(config, "rub_per_usd", 100) or 100
        amount_rub = round(amount_to_pay * rub_per_usd, 2)

    fk = FreeKassaService(config.freekassa)
    notification_url = (
        f"{config.webhook_base_url.rstrip('/')}/webhook/freekassa" if config.webhook_base_url else None
    )
    pay_url = fk.create_order(
        amount=amount_rub,
        currency="RUB",
        order_id=str(order.id),
        notification_url=notification_url,
    )
    if not pay_url:
        await callback.message.edit_text(
            "❌ Не удалось создать платёж СБП. Попробуйте позже или выберите другой способ.",
            reply_markup=back_to_menu_kb(),
        )
        return
    order.external_payment_id = str(order.id)
    await session.flush()

    await state.update_data(order_id=order.id, payment_method="freekassa")
    await state.set_state(PremiumStates.confirmed)

    await callback.message.edit_text(
        f"⚡️ К оплате: {amount_to_pay:.2f}$ ({amount_rub:.2f} ₽)"
        + (f" (с баланса списано: {balance_used:.2f}$)" if balance_used > 0 else "")
        + "\n❗️ Комиссия кассы 4%\n"
        f"ID счёта: <code>{order.id}</code>\n\n"
        "💳 Нажмите «💷 Оплатить счёт» и следуйте инструкциям.\n\n"
        "Счёт действителен 60 минут!",
        reply_markup=sbp_pay_button_kb(pay_url),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data == "menu:main", StateFilter(PremiumStates.choosing_recipient))
@router.callback_query(F.data == "menu:main", StateFilter(PremiumStates.entering_recipient_username))
@router.callback_query(F.data == "menu:main", StateFilter(PremiumStates.choosing_duration))
@router.callback_query(F.data == "menu:main", StateFilter(PremiumStates.choosing_payment))
@router.callback_query(F.data == "menu:main", StateFilter(PremiumStates.confirmed))
async def premium_back_to_menu(callback: CallbackQuery, state: FSMContext, config: AppConfig):
    """Возврат в меню из сценария Premium."""
    await state.clear()
    from bot.keyboards import main_menu_kb
    from bot.handlers.start import _get_menu_banner_path
    from aiogram.types import FSInputFile

    is_admin = callback.from_user.id in (config.admin_ids or [])
    caption = "Выберите действие:"
    banner_path = _get_menu_banner_path()
    if banner_path:
        await callback.message.delete()
        await callback.message.answer_photo(
            photo=FSInputFile(banner_path),
            caption=caption,
            reply_markup=main_menu_kb(is_admin=is_admin),
        )
    else:
        await callback.message.edit_text(caption, reply_markup=main_menu_kb(is_admin=is_admin))
    await callback.answer()

