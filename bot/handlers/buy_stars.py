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
)
from bot.config import AppConfig
from bot.services.price_engine import PriceEngine
from bot.services.antifraud import AntifraudService
from bot.services.freekassa_service import FreeKassaService
from bot.services.ton_service import TonService
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
    """Обработка введённого количества Stars."""
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
        reply_markup=payment_method_kb(),
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
        # CryptoBot: можно отправить invoice через Bot API (Stars) или использовать CryptoBot API
        await callback.answer(
            "Оплата через CryptoBot: используйте кнопку оплаты в боте или перейдите в @CryptoBot.",
            show_alert=True,
        )
        await callback.message.edit_text(
            f"Заказ #{order.id}. Оплатите {stars} Stars через @CryptoBot или выберите другой способ.",
            reply_markup=back_to_menu_kb(),
        )
        await state.clear()
        return

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
