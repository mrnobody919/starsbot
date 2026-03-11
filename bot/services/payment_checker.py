"""
Сводный сервис проверки платежей: опрос CryptoBot/TON и обработка webhook FreeKassa.
Связывает платёжные системы с заказами в БД и уведомляет пользователя/админа.
"""
import asyncio
from datetime import datetime, timezone, timedelta
from typing import TYPE_CHECKING, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.database.models import Order, Transaction, User
from bot.services.cryptobot_service import CryptoBotService
from bot.services.ton_service import TonService
from bot.utils.logger import get_logger

if TYPE_CHECKING:
    from bot.config import AppConfig

logger = get_logger(__name__)


class PaymentChecker:
    """
    Периодическая проверка ожидающих платежей (CryptoBot, TON)
    и обработка webhook от FreeKassa (вызывается из HTTP handler).
    """

    def __init__(
        self,
        cryptobot: CryptoBotService,
        ton: TonService,
    ):
        self.cryptobot = cryptobot
        self.ton = ton
        self._task: Optional[asyncio.Task] = None

    async def mark_order_paid(
        self,
        session: AsyncSession,
        order_id: int,
        tx_hash: Optional[str] = None,
        amount: float = 0,
        currency: str = "USD",
    ) -> bool:
        """
        Отмечает заказ как оплаченный, создаёт запись Transaction.
        Возвращает True при успехе.
        """
        order = await session.get(Order, order_id)
        if not order:
            return False
        if order.payment_status == "paid":
            return True

        order.payment_status = "paid"
        trans = Transaction(
            order_id=order.id,
            tx_hash=tx_hash,
            amount=amount,
            currency=currency,
            status="confirmed",
        )
        session.add(trans)
        await session.flush()
        logger.info("Order %s marked paid, tx %s", order_id, tx_hash)
        return True

    async def process_freekassa_webhook(
        self,
        session: AsyncSession,
        payload: dict,
        verify_signature: bool,
    ) -> Optional[int]:
        """
        Обрабатывает webhook от FreeKassa. Проверяет подпись, находит заказ, помечает оплаченным.
        Возвращает order_id при успехе, иначе None.
        """
        if verify_signature is False:
            logger.warning("FreeKassa webhook signature invalid")
            return None

        order_id_str = payload.get("MERCHANT_ORDER_ID")
        if not order_id_str:
            return None
        try:
            order_id = int(order_id_str)
        except ValueError:
            return None

        amount = float(payload.get("AMOUNT", 0))
        currency = str(payload.get("CUR_ID", "RUB"))

        ok = await self.mark_order_paid(
            session, order_id,
            tx_hash=payload.get("intid"),
            amount=amount,
            currency=currency,
        )
        return order_id if ok else None

    def start_polling(
        self,
        session_factory,
        bot,
        config: "AppConfig",
        price_engine=None,
        interval_seconds: int = 45,
    ) -> None:
        """
        Запускает фоновый опрос ожидающих заказов (CryptoBot, TON).
        После обнаружения оплаты помечает заказ оплаченным и уведомляет пользователя.
        """
        from bot.handlers.payments import complete_order_payment, send_payment_received_message

        async def _poll():
            while True:
                try:
                    async with session_factory() as session:
                        # CryptoBot: заказы с сохранённым invoice_id
                        pending_crypto = await session.execute(
                            select(Order).where(
                                Order.payment_status == "pending",
                                Order.payment_method == "cryptobot",
                                Order.external_payment_id.isnot(None),
                                Order.external_payment_id != "",
                            )
                        )
                        for row in pending_crypto.scalars():
                            order = row
                            try:
                                inv_id = int(order.external_payment_id)
                            except (ValueError, TypeError):
                                continue
                            inv = await self.cryptobot.get_invoice(inv_id)
                            if not inv:
                                continue
                            if (inv.get("status") or "").lower() != "paid":
                                continue
                            user = await session.get(User, order.user_id)
                            if user:
                                rub = getattr(config, "rub_per_usd", 100) or 100
                                await send_payment_received_message(
                                    bot, user.telegram_id, order.price, order.price * rub
                                )
                            await complete_order_payment(session, bot, config, order)
                            await session.commit()
                            logger.info("PaymentChecker: order %s paid via CryptoBot", order.id)
                            break  # по одному за раз, следующий цикл подхватит остальные

                        # TON: заказы с external_payment_id вида "ton_123"
                        if self.ton.enabled and price_engine:
                            ton_usd = await price_engine.get_ton_usd()
                            if ton_usd and ton_usd > 0:
                                incoming = await self.ton.get_recent_incoming_transfers(limit=30)
                                if incoming:
                                    logger.debug("TON incoming transfers: %s", [(t.get("amount_ton"), t.get("comment")) for t in incoming])
                                pending_ton = await session.execute(
                                    select(Order).where(
                                        Order.payment_status == "pending",
                                        Order.payment_method == "ton",
                                        Order.external_payment_id.isnot(None),
                                    )
                                )
                                orders_list = list(pending_ton.scalars())
                                for order in orders_list:
                                    if not (order.external_payment_id or "").startswith("ton_"):
                                        continue
                                    amount_to_match = order.price - (getattr(order, "balance_used", 0) or 0)
                                    if amount_to_match <= 0:
                                        amount_to_match = order.price
                                    expected_ton = amount_to_match / ton_usd
                                    expected_comment = f"order_{order.id}"
                                    matched = False
                                    for tr in incoming:
                                        amount_ton = tr.get("amount_ton") or 0
                                        comment = (tr.get("comment") or "").strip()
                                        amount_ok = abs(amount_ton - expected_ton) / max(expected_ton, 1e-9) <= 0.05
                                        comment_ok = comment == expected_comment or expected_comment in comment
                                        if comment_ok and amount_ok:
                                            user = await session.get(User, order.user_id)
                                            if user:
                                                rub = getattr(config, "rub_per_usd", 100) or 100
                                                await send_payment_received_message(
                                                    bot, user.telegram_id, order.price, order.price * rub
                                                )
                                            await complete_order_payment(session, bot, config, order)
                                            await session.commit()
                                            logger.info("PaymentChecker: order %s paid via TON (comment match)", order.id)
                                            matched = True
                                            break
                                    if matched:
                                        break
                                    # Резерв: комментарий не пришёл — сопоставление по сумме для заказа не старше 2 ч
                                    created = getattr(order, "created_at", None)
                                    if created:
                                        created_utc = created if getattr(created, "tzinfo", None) else created.replace(tzinfo=timezone.utc)
                                        if datetime.now(timezone.utc) - created_utc <= timedelta(hours=2):
                                            for tr in incoming:
                                                if (tr.get("comment") or "").strip():
                                                    continue
                                                amount_ton = tr.get("amount_ton") or 0
                                                if abs(amount_ton - expected_ton) / max(expected_ton, 1e-9) <= 0.05:
                                                    user = await session.get(User, order.user_id)
                                                    if user:
                                                        rub = getattr(config, "rub_per_usd", 100) or 100
                                                        await send_payment_received_message(
                                                            bot, user.telegram_id, order.price, order.price * rub
                                                        )
                                                    await complete_order_payment(session, bot, config, order)
                                                    await session.commit()
                                                    logger.info("PaymentChecker: order %s paid via TON (amount match)", order.id)
                                                    matched = True
                                                    break
                                    if matched:
                                        break
                except asyncio.CancelledError:
                    break
                except Exception as e:
                    logger.exception("PaymentChecker poll: %s", e)
                await asyncio.sleep(interval_seconds)

        self._task = asyncio.create_task(_poll())

    def stop_polling(self) -> None:
        if self._task and not self._task.done():
            self._task.cancel()
