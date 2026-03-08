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
from bot.database.repository import get_or_create_user as get_user
from bot.keyboards import back_to_menu_kb
from bot.keyboards.buy import (
    payment_method_kb,
    confirm_order_kb,
    topup_methods_kb,
    cryptobot_pay_button_kb,
)
from bot.config import AppConfig
from bot.services.price_engine import PriceEngine
from bot.services.antifraud import AntifraudService
from bot.services.freekassa_service import FreeKassaService
from bot.services.ton_service import TonService
from bot.services.cryptobot_service import CryptoBotService
from bot.utils.helpers import format_stars, format_price, validate_stars_input
from bot.utils.logger import get_logger

logger = get_logger(__name__)

router = Router(name="buy_stars")


class BuyStates(StatesGroup):
    """Состояния FSM для покупки."""
    entering_amount = State()
    choosing_payment = State()
    confirmed = State()


def _get_price_engine(config: AppConfig) -> PriceEngine:
    return PriceEngine(config.price)


def _get_antifraud(config: AppConfig) -> AntifraudService:
    return AntifraudService(config.antifraud)


@router.callback_query(F.data == "menu:buy")
async def start_buy(callback: CallbackQuery, state: FSMContext):
    """Начало покупки: просим ввести количество Stars."""
    await state.clear()
    await state.set_state(BuyStates.entering_amount)
    await callback.message.edit_text(
        "🛒 <b>Купить Stars</b>\n\n"
        "Введите количество Stars (от 50 до 50 000):",
        reply_markup=back_to_menu_kb(),
        parse_mode="HTML",
    )
    await callback.answer()


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
    quote = await engine.quote(value)
    await state.update_data(stars=value, quote_usd=quote.amount_usd, quote_ton=quote.amount_ton)

    # Проверка баланса пользователя
    result = await session.execute(select(User).where(User.telegram_id == message.from_user.id))
    db_user = result.scalar_one_or_none()
    balance_usd = (db_user.balance_usd if db_user else 0.0) or 0.0
    if db_user is None:
        from bot.database.repository import get_or_create_user
        db_user, _ = await get_or_create_user(session, message.from_user.id, message.from_user.username)
        await session.flush()

    if balance_usd < quote.amount_usd:
        shortage = quote.amount_usd - balance_usd
        shortage_rub = round(shortage * 100)
        await state.update_data(shortage_usd=shortage)
        await state.set_state(BuyStates.choosing_payment)
        text = (
            f"❌ Вам не хватает {shortage:.2f}$ ({shortage_rub} ₽) на балансе\n\n"
            f"👇🏻 Выберите способ пополнения из предложенных: 👇🏻"
        )
        await message.answer(text, reply_markup=topup_methods_kb())
        return

    await state.set_state(BuyStates.choosing_payment)
    text = (
        f"⭐ <b>{format_stars(value)}</b>\n\n"
        f"Стоимость: {format_price(quote.amount_usd)}"
    )
    if quote.amount_ton:
        text += f" (~ {quote.amount_ton} TON)"
    text += "\n\nВыберите способ оплаты:"

    await message.answer(
        text,
        reply_markup=payment_method_kb(freekassa_enabled=config.freekassa.enabled),
        parse_mode="HTML",
    )


@router.callback_query(BuyStates.choosing_payment, F.data.startswith("pay:"))
async def choose_payment(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    config: AppConfig,
):
    """Выбор способа оплаты: cryptobot, ton, freekassa."""
    method = callback.data.replace("pay:", "")
    if method not in ("cryptobot", "ton", "freekassa"):
        await callback.answer("Неизвестный способ.", show_alert=True)
        return

    data = await state.get_data()
    stars = data.get("stars")
    quote_usd = data.get("quote_usd")
    quote_ton = data.get("quote_ton")
    if not stars:
        await callback.answer("Сессия истекла. Начните заново.", show_alert=True)
        return

    # Антифрод: можно ли создать заказ
    result = await session.execute(select(User).where(User.telegram_id == callback.from_user.id))
    db_user = result.scalar_one_or_none()
    if not db_user:
        db_user, _ = await get_user(
            session,
            callback.from_user.id,
            callback.from_user.username,
        )
        await session.flush()

    antifraud = _get_antifraud(config)
    can_order, msg = await antifraud.can_create_order(session, db_user.id)
    if not can_order:
        await callback.answer(msg, show_alert=True)
        return

    # Создаём заказ в БД (pending)
    order = Order(
        user_id=db_user.id,
        username=callback.from_user.username,
        stars_amount=stars,
        price=quote_usd if method != "freekassa" else quote_usd,
        payment_method=method,
        payment_status="pending",
        delivery_status="waiting",
    )
    session.add(order)
    await session.flush()
    await state.update_data(order_id=order.id, payment_method=method)
    await state.set_state(BuyStates.confirmed)

    # Подтверждение
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
        if not config.freekassa.enabled:
            await callback.answer("Оплата FreeKassa временно недоступна.", show_alert=True)
            await callback.message.edit_text("Выберите другой способ оплаты.", reply_markup=payment_method_kb(freekassa_enabled=False))
            return
        fk = FreeKassaService(config.freekassa)
        notification_url = None
        if config.webhook_base_url:
            notification_url = f"{config.webhook_base_url.rstrip('/')}/webhook/freekassa"
        pay_url = await fk.create_order(
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
                pay_url = result.get("pay_url") or result.get("bot_invoice_url")
                invoice_id = result.get("invoice_id", "")
                if not pay_url and invoice_id:
                    pay_url = f"https://t.me/CryptoBot/app?startapp=invoice-{invoice_id}&mode=compact"
                if pay_url:
                    amount_usd = order.price
                    text = (
                        f"⚡️ Оплата заказа #{order.id}: {format_stars(stars)} — ${amount_usd:.2f} ( USDT)\n"
                        f"❗️ Комиссия Cryptobot составляет ~3%\n"
                        f"ID счёта: <code>{invoice_id}</code>\n\n"
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


# --- Пополнение баланса (topup) ---
@router.callback_query(BuyStates.choosing_payment, F.data == "topup:cryptobot")
async def topup_cryptobot(callback: CallbackQuery, state: FSMContext, session: AsyncSession, config: AppConfig):
    """Пополнение через Cryptobot: создаём инвойс USDT и показываем кнопку «Перейти к оплате»."""
    data = await state.get_data()
    amount_usd = data.get("shortage_usd") or data.get("quote_usd") or 1.0
    if amount_usd <= 0:
        await callback.answer("Введите количество Stars заново.", show_alert=True)
        return
    crypto = CryptoBotService(config.cryptobot)
    if not crypto.enabled:
        await callback.answer("Cryptobot временно недоступен.", show_alert=True)
        return
    import time
    payload = f"topup_{callback.from_user.id}_{int(time.time())}"
    result = await crypto.create_invoice_usdt(
        amount_usd=amount_usd,
        description=f"Пополнение баланса на ${amount_usd:.2f}",
        payload=payload,
    )
    if not result:
        await callback.answer("Ошибка создания счёта Cryptobot.", show_alert=True)
        return
    pay_url = result.get("pay_url") or result.get("bot_invoice_url")
    invoice_id = result.get("invoice_id", "")
    if not pay_url:
        pay_url = f"https://t.me/CryptoBot/app?startapp=invoice-{invoice_id}&mode=compact"
    amount_usdt = amount_usd  # ~1:1
    text = (
        f"⚡️ Пополнение баланса на: ${amount_usd:.2f} ( {amount_usdt:.2f} USDT)\n"
        f"❗️ Комиссия Cryptobot составляет ~3%\n"
        f"ID счёта: <code>{invoice_id}</code>\n\n"
        f"💳 Для оплаты нажмите «Перейти к оплате» и следуйте дальнейшим инструкциям\n\n"
        f"Счёт для оплаты действителен 60 минут!"
    )
    await callback.message.edit_text(
        text,
        reply_markup=cryptobot_pay_button_kb(pay_url),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(BuyStates.choosing_payment, F.data == "topup:ton")
async def topup_ton(callback: CallbackQuery, state: FSMContext, config: AppConfig):
    """Пополнение через TON: ссылка на перевод."""
    data = await state.get_data()
    amount_usd = data.get("shortage_usd") or data.get("quote_usd") or 1.0
    ton = TonService(config.ton)
    if not ton.enabled:
        await callback.answer("TON временно недоступен.", show_alert=True)
        return
    # Курс TON/USD из price engine
    engine = _get_price_engine(config)
    ton_usd = await engine.get_ton_usd()
    quote_ton = amount_usd / ton_usd if ton_usd and ton_usd > 0 else amount_usd / 5.0
    link = ton.build_payment_link(quote_ton, "topup")
    if not link:
        await callback.answer("Не удалось сформировать ссылку TON.", show_alert=True)
        return
    text = f"🔹 Пополнение баланса на ${amount_usd:.2f}\n\nПереведите ~{quote_ton:.4f} TON по ссылке ниже:"
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💳 Перейти к оплате TON", url=link)],
        [InlineKeyboardButton(text="◀️ В меню", callback_data="menu:main")],
    ])
    await callback.message.edit_text(text, reply_markup=kb)
    await callback.answer()


@router.callback_query(BuyStates.choosing_payment, F.data == "topup:usdt_ton")
async def topup_usdt_ton(callback: CallbackQuery, state: FSMContext, config: AppConfig):
    """Пополнение USDT в сети TON — пока перенаправляем на Cryptobot или TON."""
    await callback.answer("Используйте Cryptobot или TON для пополнения USDT.", show_alert=True)


@router.callback_query(BuyStates.choosing_payment, F.data == "topup:sbp")
async def topup_sbp(callback: CallbackQuery, state: FSMContext, session: AsyncSession, config: AppConfig):
    """Пополнение через СБП (FreeKassa)."""
    if not config.freekassa.enabled:
        await callback.answer("СБП (FreeKassa) временно недоступен.", show_alert=True)
        return
    data = await state.get_data()
    amount_usd = data.get("shortage_usd") or data.get("quote_usd") or 1.0
    amount_rub = round(amount_usd * 100)
    from bot.database.repository import get_or_create_user
    db_user, _ = await get_or_create_user(session, callback.from_user.id, callback.from_user.username)
    await session.flush()
    import uuid
    order_id = f"topup_{db_user.id}_{uuid.uuid4().hex[:8]}"
    fk = FreeKassaService(config.freekassa)
    notification_url = f"{config.webhook_base_url.rstrip('/')}/webhook/freekassa" if config.webhook_base_url else None
    pay_url = await fk.create_order(
        amount=amount_rub,
        currency="RUB",
        order_id=order_id,
        notification_url=notification_url,
    )
    if not pay_url:
        await callback.answer("Ошибка создания платежа СБП.", show_alert=True)
        return
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    text = f"💳 Пополнение баланса на {amount_rub} ₽\n\nОплатите по ссылке (СБП / карта):"
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💳 Перейти к оплате СБП", url=pay_url)],
        [InlineKeyboardButton(text="◀️ В меню", callback_data="menu:main")],
    ])
    await callback.message.edit_text(text, reply_markup=kb)
    await callback.answer()


# Отмена / назад
@router.callback_query(BuyStates.entering_amount, F.data == "menu:main")
@router.callback_query(BuyStates.choosing_payment, F.data == "menu:main")
async def buy_back_to_menu(callback: CallbackQuery, state: FSMContext):
    """Возврат в меню из сценария покупки."""
    await state.clear()
    from bot.keyboards import main_menu_kb
    await callback.message.edit_text("Выберите действие:", reply_markup=main_menu_kb())
    await callback.answer()
