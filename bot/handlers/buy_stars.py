"""
Покупка Stars: ввод количества, выбор способа оплаты, создание заказа.
"""
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.database.models import User, Order
from bot.database.repository import (
    get_or_create_user as get_user,
    get_ton_per_100stars,
    get_margin_percent,
)
from bot.keyboards import back_to_menu_kb
from bot.keyboards.buy import (
    recipient_choice_kb,
    back_to_recipient_kb,
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
from bot.utils.helpers import format_stars, format_price, validate_stars_input, edit_or_send_text
from bot.utils.logger import get_logger

logger = get_logger(__name__)

router = Router(name="buy_stars")


class BuyStates(StatesGroup):
    """Состояния FSM для покупки."""
    choosing_recipient = State()
    entering_recipient_username = State()
    entering_amount = State()
    choosing_payment = State()
    confirmed = State()


def _get_price_engine(config: AppConfig) -> PriceEngine:
    return PriceEngine(config.price)


def _get_antifraud(config: AppConfig) -> AntifraudService:
    return AntifraudService(config.antifraud)


@router.callback_query(F.data == "menu:buy")
async def start_buy(callback: CallbackQuery, state: FSMContext):
    """Начало покупки: выбор получателя (себе / другу)."""
    await state.clear()
    await state.set_state(BuyStates.choosing_recipient)
    await edit_or_send_text(
        callback,
        "✨ <b>Выбор имени пользователя</b>\n\n"
        "Выберите, кому вы хотите купить Telegram Stars",
        recipient_choice_kb(),
    )
    await callback.answer()


@router.callback_query(BuyStates.choosing_recipient, F.data == "buy:recipient_self")
async def buy_for_self(callback: CallbackQuery, state: FSMContext):
    """Купить себе: показываем получателя (никнейм) и просим ввести количество."""
    await state.set_state(BuyStates.entering_amount)
    username = callback.from_user.username or callback.from_user.first_name or "Вы"
    if isinstance(username, str) and not username.startswith("@"):
        display = f"@{username}" if callback.from_user.username else username
    else:
        display = username
    await state.update_data(recipient_type="self", recipient_username=None, recipient_display=display)
    await callback.message.edit_text(
        f"👤 Получатель: {display}\n\n"
        "💫 Введите количество звезд, которое хотите купить:\n\n"
        "📌 Минимальная сумма покупки - от 50 звёзд",
        reply_markup=back_to_recipient_kb(),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(BuyStates.choosing_recipient, F.data == "buy:recipient_gift")
async def buy_for_gift(callback: CallbackQuery, state: FSMContext):
    """Подарить другу: просим ввести @username."""
    await state.set_state(BuyStates.entering_recipient_username)
    await callback.message.edit_text(
        "👤 <b>Введите @username пользователя,\n"
        "которому вы хотите подарить Telegram\nStars:</b>",
        reply_markup=back_to_recipient_kb(),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data == "buy:back_recipient")
async def back_to_recipient_choice(callback: CallbackQuery, state: FSMContext):
    """Возврат к выбору получателя (себе / другу)."""
    await state.set_state(BuyStates.choosing_recipient)
    await callback.message.edit_text(
        "✨ <b>Выбор имени пользователя</b>\n\n"
        "Выберите, кому вы хотите купить Telegram Stars",
        reply_markup=recipient_choice_kb(),
        parse_mode="HTML",
    )
    await callback.answer()


@router.message(BuyStates.entering_recipient_username, F.text)
async def process_recipient_username(message: Message, state: FSMContext):
    """Обработка введённого @username для подарка."""
    text = (message.text or "").strip()
    username = text.lstrip("@") if text else ""
    if not username or len(username) < 2:
        await message.answer("Введите корректный username (например @username или username):")
        return
    if len(username) > 32:
        await message.answer("Слишком длинный username. Введите снова:")
        return
    display = f"@{username}" if not username.startswith("@") else username
    if not display.startswith("@"):
        display = f"@{display}"
    await state.update_data(recipient_type="gift", recipient_username=username, recipient_display=display)
    await state.set_state(BuyStates.entering_amount)
    await message.answer(
        f"👤 Получатель: {display}\n\n"
        "💫 Введите количество звезд, которое хотите купить:\n\n"
        "📌 Минимальная сумма покупки - от 50 звёзд",
        reply_markup=back_to_recipient_kb(),
        parse_mode="HTML",
    )


@router.message(BuyStates.entering_amount, F.text)
async def process_amount(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    config: AppConfig,
):
    """Обработка введённого количества Stars. Проверка баланса перед выбором оплаты."""
    ok, value, err = validate_stars_input(
        message.text,
        config.antifraud.min_stars_per_order,
        config.antifraud.max_stars_per_order,
    )
    if not ok:
        await message.answer(f"❌ {err}\nВведите число от 50 до 50 000:")
        return

    engine = _get_price_engine(config)
    ton_per_100stars = await get_ton_per_100stars(session, default=None)
    margin_percent = await get_margin_percent(session, default=0.0)

    # Расчёт цены:
    # админ задаёт 100 ⭐ в TON -> получаем 1 ⭐ в TON -> переводим в $ (TON/USD) -> в ₽ и применяем маржу.
    if not ton_per_100stars or ton_per_100stars <= 0:
        await message.answer(
            "❌ Цена Stars ещё не настроена администратором.\n"
            "Пожалуйста, попробуйте позже или обратитесь в поддержку.",
            reply_markup=back_to_menu_kb(),
        )
        return

    ton_usd = await engine.get_ton_usd()
    # Если курс TON/USD не удалось обновить, price_engine вернёт fallback
    if not ton_usd or ton_usd <= 0:
        ton_usd = 1.33

    ton_per_star_base = ton_per_100stars / 100.0
    ton_per_star_with_margin = ton_per_star_base * (1.0 + margin_percent / 100.0)
    usd_per_star = ton_per_star_with_margin * ton_usd
    quote = await engine.quote(value, usd_per_star_override=usd_per_star)
    await state.update_data(stars=value, quote_usd=quote.amount_usd, quote_ton=quote.amount_ton)

    # Проверка баланса пользователя
    result = await session.execute(select(User).where(User.telegram_id == message.from_user.id))
    db_user = result.scalar_one_or_none()
    balance_usd = (db_user.balance_usd if db_user else 0.0) or 0.0
    if db_user is None:
        from bot.database.repository import get_or_create_user
        db_user, _ = await get_or_create_user(session, message.from_user.id, message.from_user.username)
        await session.flush()

    rub_per_usd = getattr(config, "rub_per_usd", 100) or 100
    ton_rub = await engine.get_ton_rub()
    if balance_usd < quote.amount_usd:
        shortage = quote.amount_usd - balance_usd
        if ton_rub and quote.amount_ton:
            shortage_rub = round((shortage / max(ton_usd, 1e-9)) * ton_rub, 2)
        else:
            shortage_rub = round(shortage * rub_per_usd, 2)
        await state.update_data(shortage_usd=shortage)
        await state.set_state(BuyStates.choosing_payment)
        if ton_rub and quote.amount_ton:
            total_rub = round(quote.amount_ton * ton_rub, 2)
        else:
            total_rub = round(quote.amount_usd * rub_per_usd, 2)
        ton_part = f" (~ {quote.amount_ton} TON)" if quote.amount_ton else ""
        text = (
            f"⭐ {format_stars(value)} — стоимость заказа: {quote.amount_usd:.2f}$ ({total_rub:.2f} ₽){ton_part}\n\n"
            f"❌ Вам не хватает {shortage:.2f}$ ({shortage_rub:.2f} ₽) на балансе\n\n"
            f"💰 На балансе: {balance_usd:.2f}$ · К оплате: {shortage:.2f}$ ({shortage_rub:.2f} ₽)\n\n"
            "👇🏻 Выберите способ оплаты из предложенных: 👇🏻\n\n"
            "💳 Карты — оплата рублями банковской картой\n"
            "🔹 TON — оплата через нативный токен сети TON\n"
            "💎 Cryptobot — оплата через Cryptobot"
        )
        await message.answer(text, reply_markup=topup_methods_kb())
        return

    await state.set_state(BuyStates.choosing_payment)
    rub_per_usd = getattr(config, "rub_per_usd", 100) or 100
    if ton_rub and quote.amount_ton:
        total_rub = round(quote.amount_ton * ton_rub, 2)
    else:
        total_rub = round(quote.amount_usd * rub_per_usd, 2)
    ton_part = f" (~ {quote.amount_ton} TON)" if quote.amount_ton else ""
    text = (
        f"⭐ <b>{format_stars(value)}</b>\n\n"
        f"Стоимость: {format_price(quote.amount_usd)} ({total_rub:.2f} ₽){ton_part}"
    )
    if quote.amount_ton:
        # уже добавлено выше в ton_part
        pass
    text += f"\n\n💰 На балансе: {balance_usd:.2f}$\n\nВыберите способ оплаты:"

    await message.answer(
        text,
        reply_markup=payment_method_kb(show_balance=True),
        parse_mode="HTML",
    )


@router.callback_query(BuyStates.choosing_payment, F.data.startswith("pay:"))
async def choose_payment(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    config: AppConfig,
):
    """Выбор способа оплаты: баланс, cryptobot, ton, freekassa."""
    method = callback.data.replace("pay:", "")
    if method not in ("balance", "cryptobot", "ton", "freekassa"):
        await callback.answer("Неизвестный способ.", show_alert=True)
        return

    data = await state.get_data()
    stars = data.get("stars")
    quote_usd = data.get("quote_usd")
    quote_ton = data.get("quote_ton")
    if not stars:
        await callback.answer("Сессия истекла. Начните заново.", show_alert=True)
        return

    result = await session.execute(select(User).where(User.telegram_id == callback.from_user.id))
    db_user = result.scalar_one_or_none()
    if not db_user:
        db_user, _ = await get_user(
            session,
            callback.from_user.id,
            callback.from_user.username,
        )
        await session.flush()

    balance_usd = (db_user.balance_usd or 0.0) or 0.0
    if method == "balance":
        if balance_usd < quote_usd:
            await callback.answer("Недостаточно средств на балансе.", show_alert=True)
            return
        antifraud = _get_antifraud(config)
        can_order, msg = await antifraud.can_create_order(session, db_user.id)
        if not can_order:
            await callback.answer(msg, show_alert=True)
            return
        recipient_username = data.get("recipient_display") if data.get("recipient_type") == "gift" else None
        order = Order(
            user_id=db_user.id,
            username=callback.from_user.username,
            recipient_username=recipient_username,
            stars_amount=stars,
            price=quote_usd,
            payment_method="balance",
            payment_status="pending",
            delivery_status="waiting",
            balance_used=quote_usd,
        )
        session.add(order)
        await session.flush()
        from bot.handlers.payments import complete_order_payment
        await complete_order_payment(session, callback.bot, config, order)
        await session.commit()
        await state.clear()
        await callback.message.edit_text(
            f"✅ Заказ #{order.id} оплачен с баланса ({format_price(quote_usd)}).\n\n"
            f"Ожидайте отправки {format_stars(stars)}.",
            reply_markup=back_to_menu_kb(),
            parse_mode="HTML",
        )
        await callback.answer()
        return

    antifraud = _get_antifraud(config)
    can_order, msg = await antifraud.can_create_order(session, db_user.id)
    if not can_order:
        await callback.answer(msg, show_alert=True)
        return

    recipient_username = data.get("recipient_display") if data.get("recipient_type") == "gift" else None
    order = Order(
        user_id=db_user.id,
        username=callback.from_user.username,
        recipient_username=recipient_username,
        stars_amount=stars,
        price=quote_usd,
        payment_method=method,
        payment_status="pending",
        delivery_status="waiting",
    )
    session.add(order)
    await session.flush()
    await state.update_data(order_id=order.id, payment_method=method)
    await state.set_state(BuyStates.confirmed)

    method_name = {"cryptobot": "CryptoBot (Stars)", "ton": "Toncoin", "freekassa": "FreeKassa"}[method]
    text = (
        f"📋 <b>Подтверждение заказа #{order.id}</b>\n\n"
        f"⭐ {format_stars(stars)}\n"
        f"💵 {format_price(quote_usd)}\n"
        f"Способ: {method_name}\n\n"
        f"Подтвердить и перейти к оплате?"
    )
    await callback.message.edit_text(
        text,
        reply_markup=confirm_order_kb(order.id),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(BuyStates.confirmed, F.data.startswith("confirm_order:"))
async def confirm_and_pay(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    config: AppConfig,
):
    """После подтверждения: создаём инвойс/ссылку и отправляем пользователю."""
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
    stars = order.stars_amount
    price_usd = order.price

    if method == "freekassa":
        fk = FreeKassaService(config.freekassa)
        notification_url = None
        if config.webhook_base_url:
            notification_url = f"{config.webhook_base_url.rstrip('/')}/webhook/freekassa"
        pay_url = fk.create_order(
            amount=price_usd,
            currency="USD",
            order_id=str(order.id),
            notification_url=notification_url,
        )
        if pay_url:
            order.external_payment_id = str(order.id)
            await session.flush()
            await callback.message.edit_text(
                f"✅ Заказ #{order.id} создан.\n\n"
                f"Оплатите по ссылке:\n{pay_url}\n\n"
                f"После оплаты мы уведомим вас и отправим Stars.",
                reply_markup=back_to_menu_kb(),
            )
        else:
            await callback.answer("Ошибка создания платежа FreeKassa.", show_alert=True)
        await state.clear()
        await callback.answer()
        return

    if method == "ton":
        ton = TonService(config.ton)
        quote_ton = data.get("quote_ton")
        if ton.enabled and quote_ton:
            link = ton.build_payment_link(quote_ton, f"order_{order.id}")
            if link:
                order.external_payment_id = f"ton_{order.id}"
                await session.flush()
                await callback.message.edit_text(
                    f"✅ Заказ #{order.id}\n\n"
                    f"Переведите {quote_ton} TON по ссылке:\n{link}\n\n"
                    f"После подтверждения транзакции заказ будет выполнен.",
                    reply_markup=back_to_menu_kb(),
                )
                await state.clear()
                await callback.answer()
                return
        await callback.answer("Оплата TON временно недоступна.", show_alert=True)
        return

    if method == "cryptobot":
        crypto = CryptoBotService(config.cryptobot)
        if crypto.enabled:
            result = await crypto.create_invoice(
                amount_stars=stars,
                description=f"Заказ #{order.id} — {stars} Stars",
                payload=f"order_{order.id}",
                user_id=callback.from_user.id,
            )
            if result:
                # Сохраняем invoice_id для последующей проверки оплаты через payment_checker
                invoice_id = result.get("invoice_id")
                if invoice_id is not None:
                    order.external_payment_id = str(invoice_id)
                    await session.flush()
                # mini_app_invoice_url — ссылка на оплату в Mini App (компактный экран), иначе bot_invoice_url
                pay_url = (
                    result.get("mini_app_invoice_url")
                    or result.get("bot_invoice_url")
                    or result.get("pay_url")
                )
                invoice_id_str = str(invoice_id) if invoice_id is not None else ""
                if pay_url:
                    # CryptoBot взимает комиссию; для пользователя показываем сумму с +3%
                    amount_usd = order.price * 1.03
                    text = (
                        f"⚡️ Оплата заказа #{order.id}: {format_stars(stars)} — ${amount_usd:.2f} ( USDT)\n"
                        f"❗️ Комиссия Cryptobot составляет ~3%\n"
                        f"ID счёта: <code>{invoice_id_str}</code>\n\n"
                        f"💳 Для оплаты нажмите «Перейти к оплате» и следуйте дальнейшим инструкциям\n\n"
                        f"Счёт для оплаты действителен 60 минут!"
                    )
                    await callback.message.edit_text(
                        text,
                        reply_markup=cryptobot_pay_button_kb(pay_url),
                        parse_mode="HTML",
                    )
                    await state.clear()
                    await callback.answer()
                    return
        await callback.message.edit_text(
            f"Заказ #{order.id}. Оплатите {stars} Stars через @CryptoBot или выберите другой способ.",
            reply_markup=back_to_menu_kb(),
        )
        await state.clear()
        await callback.answer()
        return

    await callback.answer()


def _recipient_from_state(data: dict) -> str | None:
    """Получатель из state: для подарка — recipient_display, иначе None."""
    if data.get("recipient_type") == "gift":
        return data.get("recipient_display")
    return None


# --- Оплата заказа при недостатке баланса (СБП / TON / Cryptobot) ---
@router.callback_query(BuyStates.choosing_payment, F.data == "topup:cryptobot")
async def topup_cryptobot(callback: CallbackQuery, state: FSMContext, session: AsyncSession, config: AppConfig):
    """Оплата заказа через Cryptobot (при недостатке баланса): к оплате в USDT = цена − баланс."""
    await callback.answer("Создаём счёт...")
    data = await state.get_data()
    stars = data.get("stars")
    quote_usd = data.get("quote_usd") or 1.0
    shortage_usd = data.get("shortage_usd")
    if shortage_usd is None or shortage_usd <= 0:
        shortage_usd = quote_usd
    if not stars or quote_usd <= 0:
        await callback.answer("Введите количество Stars заново.", show_alert=True)
        return
    from bot.database.repository import get_or_create_user
    result_user = await session.execute(select(User).where(User.telegram_id == callback.from_user.id))
    db_user = result_user.scalar_one_or_none()
    if not db_user:
        db_user, _ = await get_or_create_user(session, callback.from_user.id, callback.from_user.username)
        await session.flush()
    balance_usd = (db_user.balance_usd or 0.0) or 0.0
    amount_to_pay = min(shortage_usd, quote_usd - balance_usd) if balance_usd < quote_usd else quote_usd
    if amount_to_pay <= 0:
        amount_to_pay = quote_usd
    balance_used = quote_usd - amount_to_pay
    if balance_used < 0:
        balance_used = 0.0
    # Для внешней оплаты USDT учитываем комиссию CryptoBot ~3%
    amount_to_pay_with_fee = amount_to_pay * 1.03
    antifraud = _get_antifraud(config)
    can_order, msg = await antifraud.can_create_order(session, db_user.id)
    if not can_order:
        await callback.answer(msg, show_alert=True)
        return
    recipient_username = _recipient_from_state(data)
    order = Order(
        user_id=db_user.id,
        username=callback.from_user.username,
        recipient_username=recipient_username,
        stars_amount=stars,
        price=quote_usd,
        payment_method="cryptobot",
        payment_status="pending",
        delivery_status="waiting",
        balance_used=balance_used,
    )
    session.add(order)
    await session.flush()
    crypto = CryptoBotService(config.cryptobot)
    if not crypto.enabled:
        await callback.answer("Cryptobot временно недоступен.", show_alert=True)
        return
    result = await crypto.create_invoice_usdt(
        amount_usd=amount_to_pay_with_fee,
        description=f"Заказ #{order.id} — {stars} Stars ({amount_to_pay_with_fee:.2f} USDT)",
        payload=f"order_{order.id}",
    )
    if not result:
        await callback.answer("Ошибка создания счёта Cryptobot.", show_alert=True)
        return
    invoice_id = result.get("invoice_id")
    if invoice_id is not None:
        order.external_payment_id = str(invoice_id)
        await session.flush()
    pay_url = (
        result.get("mini_app_invoice_url")
        or result.get("bot_invoice_url")
        or result.get("pay_url")
    )
    invoice_id_str = str(invoice_id) if invoice_id is not None else ""
    await state.update_data(order_id=order.id, payment_method="cryptobot")
    await state.set_state(BuyStates.confirmed)
    text = (
        f"⚡️ К оплате: {amount_to_pay_with_fee:.2f}$ (USDT)"
        + (f" (с баланса списано: {balance_used:.2f}$)" if balance_used > 0 else "")
        + "\n❗️ Комиссия Cryptobot ~3%\n"
        f"ID счёта: <code>{invoice_id_str}</code>\n\n"
        "💳 Нажмите «Перейти к оплате». Счёт действителен 60 минут!"
    )
    await callback.message.edit_text(
        text,
        reply_markup=cryptobot_pay_button_kb(pay_url),
        parse_mode="HTML",
    )


@router.callback_query(BuyStates.choosing_payment, F.data == "topup:ton")
async def topup_ton(callback: CallbackQuery, state: FSMContext, session: AsyncSession, config: AppConfig):
    """Оплата заказа через TON (при недостатке баланса): к оплате = цена − баланс."""
    await callback.answer("Создаём ссылку на оплату...")
    data = await state.get_data()
    stars = data.get("stars")
    quote_usd = data.get("quote_usd") or 1.0
    shortage_usd = data.get("shortage_usd")
    if shortage_usd is None or shortage_usd <= 0:
        shortage_usd = quote_usd
    if not stars:
        await callback.answer("Сессия истекла. Введите количество звёзд заново.", show_alert=True)
        return
    from bot.database.repository import get_or_create_user
    result = await session.execute(select(User).where(User.telegram_id == callback.from_user.id))
    db_user = result.scalar_one_or_none()
    if not db_user:
        db_user, _ = await get_or_create_user(session, callback.from_user.id, callback.from_user.username)
        await session.flush()
    balance_usd = (db_user.balance_usd or 0.0) or 0.0
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
    recipient_username = _recipient_from_state(data)
    order = Order(
        user_id=db_user.id,
        username=callback.from_user.username,
        recipient_username=recipient_username,
        stars_amount=stars,
        price=quote_usd,
        payment_method="ton",
        payment_status="pending",
        delivery_status="waiting",
        balance_used=balance_used,
    )
    session.add(order)
    await session.flush()
    ton = TonService(config.ton)
    if not ton.enabled:
        await callback.answer("TON временно недоступен.", show_alert=True)
        return
    engine = _get_price_engine(config)
    ton_usd = await engine.get_ton_usd()
    # Fallback ~1.33 USD за 1 TON, если курс недоступен (раньше было /5 → давало заниженную сумму в TON)
    amount_ton = amount_to_pay / ton_usd if ton_usd and ton_usd > 0 else amount_to_pay / 1.33
    link = ton.build_payment_link(amount_ton, f"order_{order.id}")
    if not link:
        await callback.answer("Не удалось сформировать ссылку TON.", show_alert=True)
        return
    order.external_payment_id = f"ton_{order.id}"
    await session.flush()
    await state.update_data(order_id=order.id, payment_method="ton", quote_ton=amount_ton)
    await state.set_state(BuyStates.confirmed)
    wallet = config.ton.wallet_address or ""
    text = (
        f"⚡️ К оплате: {amount_to_pay:.2f}$ (~ {amount_ton:.4f} TON)"
        + (f" (с баланса списано: {balance_used:.2f}$)" if balance_used > 0 else "")
        + f"\nID счёта: <code>{order.id}</code>\n\n"
        f"💷 Переведите ТОЧНУЮ СУММУ: {amount_ton:.4f} TON\n\n"
        f"👛 Кошелёк:\n<code>{wallet}</code>\n\n"
        "После транзакции бот подтвердит платёж. Счёт действителен 60 минут!"
    )
    await callback.message.edit_text(text, reply_markup=ton_pay_button_kb(link), parse_mode="HTML")
    await callback.answer()


@router.callback_query(BuyStates.choosing_payment, F.data == "topup:usdt_ton")
async def topup_usdt_ton(callback: CallbackQuery, state: FSMContext, config: AppConfig):
    """Пополнение USDT в сети TON — пока перенаправляем на Cryptobot или TON."""
    await callback.answer("Используйте Cryptobot или TON для пополнения USDT.", show_alert=True)


@router.callback_query(BuyStates.choosing_payment, F.data == "topup:sbp")
async def topup_sbp(callback: CallbackQuery, state: FSMContext, session: AsyncSession, config: AppConfig):
    """Оплата заказа через СБП (при недостатке баланса): сумма к оплате = цена − баланс."""
    await callback.answer("Создаём ссылку на оплату...")
    data = await state.get_data()
    stars = data.get("stars")
    quote_usd = data.get("quote_usd") or 1.0
    shortage_usd = data.get("shortage_usd")
    if shortage_usd is None or shortage_usd <= 0:
        shortage_usd = quote_usd
    if not stars:
        await callback.answer("Сессия истекла. Введите количество звёзд заново.", show_alert=True)
        return
    from bot.database.repository import get_or_create_user
    result = await session.execute(select(User).where(User.telegram_id == callback.from_user.id))
    db_user = result.scalar_one_or_none()
    if not db_user:
        db_user, _ = await get_or_create_user(session, callback.from_user.id, callback.from_user.username)
        await session.flush()
    balance_usd = (db_user.balance_usd or 0.0) or 0.0
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
    recipient_username = _recipient_from_state(data)
    order = Order(
        user_id=db_user.id,
        username=callback.from_user.username,
        recipient_username=recipient_username,
        stars_amount=stars,
        price=quote_usd,
        payment_method="freekassa",
        payment_status="pending",
        delivery_status="waiting",
        balance_used=balance_used,
    )
    session.add(order)
    await session.flush()
    await state.update_data(order_id=order.id, payment_method="freekassa")

    # Важно: сумма в ₽ для СБП должна совпадать с тем, что бот показывает пользователю.
    # Сейчас бот считает ₽ из курса TON->RUB, поэтому и здесь делаем конвертацию через TON,
    # а не через фиксированный RUB_PER_USD.
    engine = _get_price_engine(config)
    ton_usd = await engine.get_ton_usd()
    ton_rub = await engine.get_ton_rub()
    if ton_usd and ton_rub and ton_usd > 0:
        # 1 USD = (RUB per TON) / (USD per TON)
        rub_per_usd_dynamic = ton_rub / ton_usd
        amount_rub = round(amount_to_pay * rub_per_usd_dynamic, 2)
    else:
        rub_per_usd = getattr(config, "rub_per_usd", 100) or 100
        amount_rub = round(amount_to_pay * rub_per_usd, 2)
    fk = FreeKassaService(config.freekassa)
    notification_url = f"{config.webhook_base_url.rstrip('/')}/webhook/freekassa" if config.webhook_base_url else None
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
    text = (
        f"⚡️ К оплате: {amount_to_pay:.2f}$ ({amount_rub:.2f} ₽)"
        + (f" (с баланса списано: {balance_used:.2f}$)" if balance_used > 0 else "")
        + "\n❗️ Комиссия кассы 4%\n"
        f"ID счёта: <code>{order.id}</code>\n\n"
        "💳 Нажмите «💷 Оплатить счёт» и следуйте инструкциям.\n\n"
        "Счёт действителен 60 минут!"
    )
    await callback.message.edit_text(text, reply_markup=sbp_pay_button_kb(pay_url), parse_mode="HTML")
    await state.set_state(BuyStates.confirmed)
    await callback.answer()


# Отмена / назад
@router.callback_query(BuyStates.choosing_recipient, F.data == "menu:main")
@router.callback_query(BuyStates.entering_recipient_username, F.data == "menu:main")
@router.callback_query(BuyStates.entering_amount, F.data == "menu:main")
@router.callback_query(BuyStates.choosing_payment, F.data == "menu:main")
async def buy_back_to_menu(callback: CallbackQuery, state: FSMContext, config: AppConfig):
    """Возврат в меню из сценария покупки. Если есть баннер — показываем его над меню."""
    await state.clear()
    from bot.keyboards import main_menu_kb
    from bot.handlers.start import _get_menu_banner_path
    from aiogram.types import FSInputFile
    is_admin = callback.from_user.id in config.admin_ids
    caption = "Выберите действие:"
    banner_path = _get_menu_banner_path()
    try:
        if banner_path:
            await callback.message.delete()
            await callback.message.answer_photo(
                photo=FSInputFile(banner_path),
                caption=caption,
                reply_markup=main_menu_kb(is_admin=is_admin),
            )
        else:
            await callback.message.edit_text(caption, reply_markup=main_menu_kb(is_admin=is_admin))
    except Exception as e:
        logger.warning("buy_back_to_menu: %s", e)
        await callback.message.edit_text(caption, reply_markup=main_menu_kb(is_admin=is_admin))
    await callback.answer()
