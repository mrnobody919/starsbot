"""
Обработка платежей: успешная оплата (Telegram Stars / CryptoBot), webhook FreeKassa.
Уведомления пользователю и админу.
"""
from aiogram import Router, Bot, F
from aiogram.types import Message, PreCheckoutQuery, LabeledPrice
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from bot.database.models import Order, User, Referral, Transaction
from bot.config import AppConfig
from bot.utils.logger import get_logger
from bot.utils.helpers import format_stars

router = Router(name="payments")
logger = get_logger(__name__)


async def _notify_user_order_paid(bot: Bot, telegram_id: int, order_id: int, stars: int):
    """Уведомление пользователю: заказ оплачен, ожидайте отправки."""
    try:
        await bot.send_message(
            telegram_id,
            f"✅ Ваш заказ #{order_id} оплачен. Ожидайте отправки Stars ({format_stars(stars)}).",
        )
    except Exception as e:
        logger.warning("Notify user %s failed: %s", telegram_id, e)


async def send_payment_received_message(
    bot: Bot, telegram_id: int, amount_usd: float, amount_rub: float
) -> None:
    """Сообщение о получении оплаты (для сценария «оплата заказа», без зачисления на баланс)."""
    try:
        await bot.send_message(
            telegram_id,
            f"✅ На ваш баланс зачислено {amount_usd:.2f} $ ({amount_rub:.0f} ₽). Спасибо за пополнение!",
        )
    except Exception as e:
        logger.warning("Send payment received to %s failed: %s", telegram_id, e)


async def _notify_user_order_completed(bot: Bot, telegram_id: int, order_id: int, stars: int):
    """Уведомление пользователю: заказ выполнен, Stars отправлены."""
    try:
        await bot.send_message(
            telegram_id,
            f"✅ Ваш заказ #{order_id} выполнен. Вам отправлено {format_stars(stars)}.",
        )
    except Exception as e:
        logger.warning("Notify user %s failed: %s", telegram_id, e)


async def _notify_admins_new_order(bot: Bot, admin_ids: list[int], order: Order, user: User):
    """Уведомление админам: новый оплаченный заказ для ручной отправки Stars."""
    text = (
        f"🆕 Оплачен заказ #{order.id}\n"
        f"👤 User: {user.telegram_id} (@{user.username or '—'})\n"
        f"⭐ Stars: {order.stars_amount}\n"
        f"💵 Сумма: {order.price} {order.payment_method}"
    )
    for aid in admin_ids:
        try:
            await bot.send_message(aid, text)
        except Exception as e:
            logger.warning("Notify admin %s failed: %s", aid, e)


async def _send_order_to_channel(bot: Bot, channel_id: int, order: Order, user: User):
    """Отправка оплаченного заказа в канал/группу (если задан ORDERS_CHANNEL_ID)."""
    recipient = getattr(order, "recipient_username", None) or "себе"
    if recipient and recipient != "себе" and not recipient.startswith("@"):
        recipient = f"@{recipient}"
    text = (
        f"🆕 <b>Оплачен заказ #{order.id}</b>\n\n"
        f"👤 Покупатель: <code>{user.telegram_id}</code> (@{user.username or '—'})\n"
        f"📤 Получатель Stars: {recipient}\n"
        f"⭐ Количество: {order.stars_amount}\n"
        f"💵 Сумма: {order.price} $ ({order.payment_method})\n\n"
        f"⏳ Ожидает отправки."
    )
    try:
        await bot.send_message(channel_id, text, parse_mode="HTML")
    except Exception as e:
        logger.warning("Send order to channel %s failed: %s", channel_id, e)


async def complete_order_payment(
    session: AsyncSession,
    bot: Bot,
    config: AppConfig,
    order: Order,
) -> bool:
    """
    Помечает заказ как оплаченный: Transaction, реферальные начисления,
    уведомление пользователю, админам и в канал заказов.
    Вызывается из successful_payment, handle_freekassa_paid и из payment_checker.
    """
    if order.payment_status == "paid":
        return True
    order.payment_status = "paid"
    session.add(
        Transaction(order_id=order.id, amount=order.price, currency="USD", status="confirmed")
    )
    user = await session.get(User, order.user_id)
    if user:
        if user.referred_by:
            referrer = await session.get(User, user.referred_by)
            if referrer:
                reward_usd = order.price * (config.referral_percent / 100)
                referrer.referral_reward_total += reward_usd
                referrer.balance_usd = getattr(referrer, "balance_usd", 0.0) + reward_usd
                session.add(
                    Referral(
                        referrer_id=referrer.id,
                        referred_user_id=user.id,
                        reward=reward_usd,
                        order_id=order.id,
                    )
                )
        await session.flush()
        await _notify_user_order_paid(bot, user.telegram_id, order.id, order.stars_amount)
        if config.admin_ids:
            await _notify_admins_new_order(bot, config.admin_ids, order, user)
        if config.orders_channel_id:
            await _send_order_to_channel(bot, config.orders_channel_id, order, user)
    logger.info("Order %s marked paid", order.id)
    return True


def _build_stars_invoice_payload(order_id: int) -> str:
    """Payload для pre_checkout/successful_payment — идентификация заказа."""
    return f"order_{order_id}"


async def complete_order_payment(
    session: AsyncSession,
    bot: Bot,
    config: AppConfig,
    order: Order,
) -> None:
    """
    Помечает заказ оплаченным: Transaction, реферальные начисления, уведомления.
    Вызывается из successful_payment, handle_freekassa_paid и из PaymentChecker (CryptoBot/TON).
    """
    if order.payment_status == "paid":
        return
    order.payment_status = "paid"
    session.add(
        Transaction(order_id=order.id, amount=order.price, currency="USD", status="confirmed")
    )
    user = await session.get(User, order.user_id)
    if user:
        if user.referred_by:
            referrer = await session.get(User, user.referred_by)
            if referrer:
                reward_usd = order.price * (config.referral_percent / 100)
                referrer.referral_reward_total += reward_usd
                referrer.balance_usd = getattr(referrer, "balance_usd", 0.0) + reward_usd
                session.add(
                    Referral(
                        referrer_id=referrer.id,
                        referred_user_id=user.id,
                        reward=reward_usd,
                        order_id=order.id,
                    )
                )
        await session.flush()
        await _notify_user_order_paid(bot, user.telegram_id, order.id, order.stars_amount)
        if config.admin_ids:
            await _notify_admins_new_order(bot, config.admin_ids, order, user)
        if config.orders_channel_id:
            await _send_order_to_channel(bot, config.orders_channel_id, order, user)
    logger.info("Order %s marked paid (complete_order_payment)", order.id)


@router.pre_checkout_query()
async def pre_checkout(pre_checkout_query: PreCheckoutQuery, session: AsyncSession):
    """Подтверждение pre_checkout для Telegram Stars (оплата в боте)."""
    payload = pre_checkout_query.invoice_payload or ""
    if not payload.startswith("order_"):
        await pre_checkout_query.answer(ok=False, error_message="Неверный заказ")
        return
    try:
        order_id = int(payload.replace("order_", ""))
    except ValueError:
        await pre_checkout_query.answer(ok=False, error_message="Неверный заказ")
        return
    order = await session.get(Order, order_id)
    if not order or order.payment_status == "paid":
        await pre_checkout_query.answer(ok=False, error_message="Заказ уже оплачен или не найден")
        return
    await pre_checkout_query.answer(ok=True)


@router.message(F.successful_payment)
async def successful_payment(message: Message, session: AsyncSession, config: AppConfig):
    """
    Успешная оплата через Telegram (Stars). Обновляем заказ, начисляем рефералу бонус, уведомляем.
    """
    pay = message.successful_payment
    payload = pay.invoice_payload or ""
    if not payload.startswith("order_"):
        return
    try:
        order_id = int(payload.replace("order_", ""))
    except ValueError:
        return

    order = await session.get(Order, order_id)
    if not order:
        return
    if order.payment_status == "paid":
        user = await session.get(User, order.user_id)
        if user:
            await _notify_user_order_paid(message.bot, user.telegram_id, order.id, order.stars_amount)
        return

    await complete_order_payment(session, message.bot, config, order)


# Экспорт для вызова из webhook (FreeKassa)
async def handle_freekassa_paid(
    session: AsyncSession,
    bot: Bot,
    config: AppConfig,
    order_id: int,
    amount_rub: float | None = None,
) -> bool:
    """
    Вызывается после верификации webhook FreeKassa: помечаем заказ оплаченным,
    начисляем рефералу бонус, уведомляем пользователя и админов.
    Если передан amount_rub, сначала отправляем сообщение «На ваш баланс зачислено...».
    """
    order = await session.get(Order, order_id)
    if not order or order.payment_status == "paid":
        return False
    user = await session.get(User, order.user_id)
    if user and amount_rub is not None and amount_rub > 0:
        await send_payment_received_message(bot, user.telegram_id, order.price, amount_rub)
    await complete_order_payment(session, bot, config, order)
    logger.info("Order %s paid (FreeKassa)", order_id)
    return True


async def handle_freekassa_topup(
    session: AsyncSession,
    bot: Bot,
    config: AppConfig,
    order_id_str: str,
    amount_rub: float,
) -> bool:
    """
    Обработка webhook FreeKassa для пополнения баланса.
    order_id_str вида "topup_{user_id}_{uuid}". Зачисляем amount_rub/100 USD на balance_usd.
    """
    if not order_id_str.startswith("topup_"):
        return False
    parts = order_id_str.split("_")
    if len(parts) < 3:
        return False
    try:
        user_id = int(parts[1])
    except ValueError:
        return False
    user = await session.get(User, user_id)
    if not user:
        logger.warning("Topup webhook: user id %s not found", user_id)
        return False
    rate = getattr(config, "rub_per_usd", 100.0) or 100.0
    amount_usd = amount_rub / rate
    user.balance_usd = (user.balance_usd or 0) + amount_usd
    await session.flush()
    try:
        await bot.send_message(
            user.telegram_id,
            f"✅ Пополнение выполнено. На ваш баланс зачислено {amount_usd:.2f} $ ({amount_rub:.0f} ₽).\n\n"
            f"Теперь вы можете вернуться в бот и оплатить заказ Stars с баланса.",
        )
    except Exception as e:
        logger.warning("Notify user %s about topup failed: %s", user.telegram_id, e)
    logger.info("Topup: user_id=%s amount_usd=%.2f", user_id, amount_usd)
    return True
