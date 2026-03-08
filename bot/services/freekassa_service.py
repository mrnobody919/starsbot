"""
Интеграция FreeKassa: создание платежа, проверка подписи webhook.
"""
import hashlib
from typing import Any, Optional
from urllib.parse import urlencode

import httpx

from bot.config import FreeKassaConfig
from bot.utils.logger import get_logger

logger = get_logger(__name__)

FREEKASSA_CREATE_URL = "https://api.freekassa.ru/v1/orders/create"


class FreeKassaService:
    """Создание заказа в FreeKassa и верификация webhook."""

    def __init__(self, config: FreeKassaConfig):
        self.config = config

    def _sign(self, *parts: str) -> str:
        """Подпись для FreeKassa (MD5 от конкатенации секретного слова и полей)."""
        s = "".join(str(p) for p in parts)
        return hashlib.md5(s.encode()).hexdigest()

    async def create_order(
        self,
        amount: float,
        currency: str,
        order_id: str,
        email: str = "",
        success_url: str = "",
        failure_url: str = "",
        notification_url: Optional[str] = None,
    ) -> Optional[str]:
        """
        Создаёт платёж в FreeKassa и возвращает URL для перенаправления пользователя.
        amount — сумма, currency — например RUB, USD.
        order_id — уникальный ID заказа в нашей системе.
        """
        signature = self._sign(self.config.merchant_id, amount, self.config.secret_word_1, order_id)

        payload = {
            "shopId": self.config.merchant_id,
            "nonce": order_id,
            "paymentId": order_id,
            "amount": amount,
            "currency": currency,
            "email": email or "noreply@example.com",
            "success_url": success_url or "https://t.me/",
            "failure_url": failure_url or "https://t.me/",
            "sign": signature,
        }
        if notification_url:
            payload["notification_url"] = notification_url

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                r = await client.post(FREEKASSA_CREATE_URL, json=payload)
                if r.status_code != 200:
                    logger.warning("FreeKassa create order: %s %s", r.status_code, r.text)
                    return None
                data = r.json()
                url = data.get("url") or data.get("payment_url")
                if url:
                    return url
                logger.warning("FreeKassa no URL in response: %s", data)
                return None
        except Exception as e:
            logger.exception("FreeKassa create_order: %s", e)
            return None

    def verify_notification(self, payload: dict) -> bool:
        """
        Проверяет подпись уведомления от FreeKassa (MERCHANT_ID:AMOUNT:SECRET_WORD_2:ORDER_ID).
        """
        merchant_id = str(payload.get("MERCHANT_ID", ""))
        amount = str(payload.get("AMOUNT", ""))
        order_id = str(payload.get("MERCHANT_ORDER_ID", ""))
        sign = str(payload.get("SIGN", ""))

        expected = self._sign(
            merchant_id,
            amount,
            self.config.secret_word_2,
            order_id,
        )
        return sign.lower() == expected.lower()
