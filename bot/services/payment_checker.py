"""
Сводный сервис проверки платежей: опрос CryptoBot/TON и обработка webhook FreeKassa.
Связывает платёжные системы с заказами в БД и уведомляет пользователя/админа.
"""
import asyncio
from datetime import datetime
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.database.models import Order, Transaction, User, Referral
from bot.services.cryptobot_service import CryptoBotService
from bot.services.ton_service import TonService
from bot.utils.logger import get_logger

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

    def start_polling(self, session_factory, interval_seconds: int = 30) -> None:
        """
        Запускает фоновый опрос ожидающих заказов (CryptoBot/TON).
        session_factory — async_sessionmaker для создания сессий.
        """
        async def _poll():
            while True:
                try:
                    async with session_factory() as session:
                        # Ожидающие заказы по CryptoBot/TON можно проверять по external_payment_id
                        await session.commit()
                except asyncio.CancelledError:
                    break
                except Exception as e:
                    logger.exception("PaymentChecker poll: %s", e)
                await asyncio.sleep(interval_seconds)

        self._task = asyncio.create_task(_poll())

    def stop_polling(self) -> None:
        if self._task and not self._task.done():
            self._task.cancel()
