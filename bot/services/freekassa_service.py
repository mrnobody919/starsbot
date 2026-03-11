"""
Интеграция FreeKassa: ссылка на оплату по SCI (форма с подписью), проверка webhook.
Подпись формы: MD5(merchant_id:amount:secret_word_1:currency:order_id).
URL оповещения настраивается в личном кабинете FreeKassa.
"""
import hashlib
from typing import Optional
from urllib.parse import urlencode

from bot.config import FreeKassaConfig
from bot.utils.logger import get_logger

logger = get_logger(__name__)

# Форма оплаты FreeKassa (SCI) — GET с параметрами m, oa, currency, o, s
FREEKASSA_PAY_URL = "https://pay.fk.money/"


class FreeKassaService:
    """Формирование ссылки на оплату FreeKassa (СБП/карты) и верификация webhook."""

    def __init__(self, config: FreeKassaConfig):
        self.config = config

    def _sign_sci(self, merchant_id: str, amount: str, secret: str, currency: str, order_id: str) -> str:
        """Подпись для формы оплаты: MD5(merchant_id:amount:secret:currency:order_id)."""
        raw = f"{merchant_id}:{amount}:{secret}:{currency}:{order_id}"
        return hashlib.md5(raw.encode("utf-8")).hexdigest()

    def _sign_notification(self, merchant_id: str, amount: str, secret: str, order_id: str) -> str:
        """Подпись уведомления от FreeKassa (SECRET_WORD_2): MD5(MERCHANT_ID:AMOUNT:SECRET:ORDER_ID) или конкатенация — см. док."""
        raw = f"{merchant_id}:{amount}:{secret}:{order_id}"
        return hashlib.md5(raw.encode("utf-8")).hexdigest()

    def create_order(
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
        Формирует ссылку на оплату FreeKassa (SCI). Не делает запросов к API.
        amount — сумма (число, для RUB — рубли).
        currency — RUB, USD и т.д.
        order_id — уникальный номер заказа в нашей системе.
        URL оповещения задаётся в личном кабинете FreeKassa (URL оповещения).
        """
        if not self.config.merchant_id or not self.config.secret_word_1:
            logger.warning("FreeKassa: не заданы MERCHANT_ID или SECRET_WORD_1")
            return None
        # Сумму передаём как строку без лишних знаков (целое для RUB)
        amount_str = str(int(round(amount))) if currency == "RUB" else str(round(amount, 2))
        sign = self._sign_sci(
            self.config.merchant_id,
            amount_str,
            self.config.secret_word_1,
            currency,
            order_id,
        )
        params = {
            "m": self.config.merchant_id,
            "oa": amount_str,
            "currency": currency,
            "o": order_id,
            "s": sign,
        }
        if email:
            params["em"] = email
        url = FREEKASSA_PAY_URL + "?" + urlencode(params)
        logger.info("FreeKassa SCI URL сформирован для заказа %s, сумма %s %s", order_id, amount_str, currency)
        return url

    def verify_notification(self, payload: dict) -> bool:
        """
        Проверяет подпись уведомления от FreeKassa.
        Формула по документации: MD5(MERCHANT_ID:AMOUNT:SECRET_WORD_2:MERCHANT_ORDER_ID).
        """
        merchant_id = str(payload.get("MERCHANT_ID", ""))
        amount = str(payload.get("AMOUNT", ""))
        order_id = str(payload.get("MERCHANT_ORDER_ID", ""))
        sign = str(payload.get("SIGN", "")).strip()
        if not sign or not self.config.secret_word_2:
            return False
        expected = self._sign_notification(
            merchant_id, amount, self.config.secret_word_2, order_id
        )
        return sign.lower() == expected.lower()
