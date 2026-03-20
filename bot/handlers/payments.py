"""
Обработка платежей: успешная оплата (Telegram Stars / CryptoBot), webhook FreeKassa.
Уведомления пользователю и админу.
"""
from aiogram import Router, Bot, F
from aiogram.types import Message, PreCheckoutQuery, LabeledPrice
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update

from bot.database.models import Order, User, Referral, Transaction
from bot.config import AppConfig
from bot.utils.logger import get_logger
from bot.utils.helpers import format_stars

router = Router(name="payments")
logger = get_logger(__name__)


async def _notify_user_order_paid(bot: Bot, telegram_id: int, order: Order):
    """Уведомление пользователю: заказ оплачен."""
    try:
        order_type = (getattr(order, "order_type", None) or "stars").lower()
        if order_type == "premium":
            months = getattr(order, "premium_months", 0) or 0
            text = f"✅ Ваш заказ #{order.id} оплачен. Ожидайте активации Premium ({months} месяцев)."
        else:
            stars = getattr(order, "stars_amount", 0) or 0
            text = f"✅ Ваш заказ #{order.id} оплачен. Ожидайте отправки Stars ({format_stars(stars)})."

        await bot.send_message(telegram_id, text)
    except Exception as e:
        logger.warning("Notify user %s failed: %s", telegram_id, e)


async def send_payment_received_message(
    bot: Bot, telegram_id: int, amount_usd: float, amount_rub: float
) -> None:
    """Сообщение о получении оплаты (для сценария «оплата заказа», без зачисления на баланс)."""
    try:
        await bot.send_message(
            telegram_id,
            f"✅ На ваш баланс зачислено {amount_usd:.2f} $ ({amount_rub:.2f} ₽). Спасибо за пополнение!",
        )
    except Exception as e:
        logger.warning("Send payment received to %s failed: %s", telegram_id, e)


async def _notify_user_order_completed(bot: Bot, telegram_id: int, order: Order):
    """Уведомление пользователю: заказ выполнен."""
    try:
        order_type = (getattr(order, "order_type", None) or "stars").lower()
        if order_type == "premium":
            months = getattr(order, "premium_months", 0) or 0
            text = f"✅ Ваш заказ #{order.id} выполнен. Premium на {months} месяцев активирована."
        else:
            stars = getattr(order, "stars_amount", 0) or 0
            text = f"✅ Ваш заказ #{order.id} выполнен. Вам отправлено {format_stars(stars)}."
        await bot.send_message(
            telegram_id,
            text,
        )
    except Exception as e:
        logger.warning("Notify user %s failed: %s", telegram_id, e)


async def _notify_admins_new_order(bot: Bot, admin_ids: list[int], order: Order, user: User):
    """Уведомление админам: новый оплаченный заказ."""
    order_type = (getattr(order, "order_type", None) or "stars").lower()
    if order_type == "premium":
        from bot.keyboards import order_premium_sent_kb
        months = getattr(order, "premium_months", 0) or 0
        recipient_username = getattr(order, "recipient_username", None)
        recipient = f"@{recipient_username}" if recipient_username else "себе"
        text = (
            f"🆕 Оплачен Premium заказ #{order.id}\n"
            f"👤 Покупатель: {user.telegram_id} (@{user.username or '—'})\n"
            f"🎁 Получатель: {recipient}\n"
            f"🗓️ Срок: {months} месяцев\n"
            f"💵 Сумма: {order.price} $ ({order.payment_method})"
        )
        reply_markup = order_premium_sent_kb(order.id)
    else:
        from bot.keyboards import order_stars_sent_kb
        text = (
            f"🆕 Оплачен заказ #{order.id}\n"
            f"👤 User: {user.telegram_id} (@{user.username or '—'})\n"
            f"⭐ Stars: {order.stars_amount}\n"
            f"💵 Сумма: {order.price} $ ({order.payment_method})"
        )
        reply_markup = order_stars_sent_kb(order.id)

    for aid in admin_ids:
        try:
            await bot.send_message(aid, text, reply_markup=reply_markup)
        except Exception as e:
            logger.warning("Notify admin %s failed: %s", aid, e)


async def _send_order_to_channel(bot: Bot, channel_id: int, order: Order, user: User):
    """Отправка оплаченного заказа в канал/группу."""
    order_type = (getattr(order, "order_type", None) or "stars").lower()
    from bot.keyboards import order_stars_sent_kb, order_premium_sent_kb
    if order_type == "premium":
        recipient_username = getattr(order, "recipient_username", None)
        recipient = f"@{recipient_username}" if recipient_username else "себе"
        months = getattr(order, "premium_months", 0) or 0
        text = (
            f"🆕 <b>Оплачен Premium заказ #{order.id}</b>\n\n"
            f"👤 Покупатель: <code>{user.telegram_id}</code> (@{user.username or '—'})\n"
            f"📤 Получатель Premium: {recipient}\n"
            f"🗓️ Срок: {months} месяцев\n"
            f"💵 Сумма: {order.price} $ ({order.payment_method})\n\n"
            f"⏳ Ожидает активации."
        )
    else:
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
        await bot.send_message(
            channel_id,
            text,
            parse_mode="HTML",
            reply_markup=(order_premium_sent_kb(order.id) if order_type == "premium" else order_stars_sent_kb(order.id)),
        )
    except Exception as e:
        logger.warning("Send order to channel %s failed: %s", channel_id, e)


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
    Помечает заказ оплаченным: списание баланса (balance_used), Transaction,
    реферальные начисления, уведомления.
    """
    # Идемпотентность: если из-за ретраев/параллельных вызовов функция
    # будет запущена повторно, то только первый вызов реально переведёт заказ в paid.
    # Второй вызов должен выйти без повторных уведомлений.
    res = await session.execute(
        update(Order)
        .where(Order.id == order.id, Order.payment_status != "paid")
        .values(payment_status="paid")
    )
    if getattr(res, "rowcount", 0) == 0:
        return
    order.payment_status = "paid"
    session.add(
        Transaction(order_id=order.id, amount=order.price, currency="USD", status="confirmed")
    )
    user = await session.get(User, order.user_id)
    if user:
        balance_used = getattr(order, "balance_used", 0.0) or 0.0
        if balance_used > 0:
            user.balance_usd = (user.balance_usd or 0.0) - balance_used
            if user.balance_usd < 0:
                user.balance_usd = 0.0
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
        await _notify_user_order_paid(bot, user.telegram_id, order)
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
            await _notify_user_order_paid(message.bot, user.telegram_id, order)
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
            f"✅ Пополнение выполнено. На ваш баланс зачислено {amount_usd:.2f} $ ({amount_rub:.2f} ₽).\n\n"
            f"Теперь вы можете вернуться в бот и оплатить заказ Stars с баланса.",
        )
    except Exception as e:
        logger.warning("Notify user %s about topup failed: %s", user.telegram_id, e)
    logger.info("Topup: user_id=%s amount_usd=%.2f", user_id, amount_usd)
    return True
