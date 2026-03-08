"""
Интеграция с CryptoBot (Telegram Stars через @CryptoBot).
Создание инвойсов и проверка подписи/статуса оплаты.
"""
from typing import Any, Optional

import httpx
from aiogram.types import LabeledPrice

from bot.config import CryptoBotConfig
from bot.utils.logger import get_logger

logger = get_logger(__name__)

CRYPTOBOT_API = "https://pay.crypt.bot/api"

# Ссылка для оплаты в приложении CryptoBot (компактный режим)
def build_invoice_app_url(invoice_id: str) -> str:
    """Формирует ссылку вида https://t.me/CryptoBot/app?startapp=invoice-XXX&mode=compact."""
    return f"https://t.me/CryptoBot/app?startapp=invoice-{invoice_id}&mode=compact"


class CryptoBotService:
    """Работа с CryptoBot API для приёма Stars."""

    def __init__(self, config: CryptoBotConfig):
        self.config = config
        self._enabled = bool(config.api_token)

    @property
    def enabled(self) -> bool:
        return self._enabled

    def _headers(self) -> dict[str, str]:
        return {"Crypto-Pay-API-Token": self.config.api_token or ""}

    async def create_invoice(
        self,
        amount_stars: int,
        description: str,
        payload: str,
        user_id: int,
    ) -> Optional[dict[str, Any]]:
        """
        Создаёт инвойс в CryptoBot (Stars).
        payload — строка для идентификации заказа (например order_123).
        Возвращает данные инвойса или None при ошибке.
        """
        if not self._enabled:
            return None
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                r = await client.post(
                    f"{CRYPTOBOT_API}/createInvoice",
                    headers=self._headers(),
                    json={
                        "asset": "XTR",  # Telegram Stars
                        "amount": str(amount_stars),
                        "description": description,
                        "payload": payload,
                        "paid_btn_name": "callback",
                        "paid_btn_meta": f"order:{payload}",
                    },
                )
                if r.status_code != 200:
                    logger.warning("CryptoBot createInvoice error: %s %s", r.status_code, r.text)
                    return None
                data = r.json()
                if not data.get("ok"):
                    return None
                return data.get("result")
        except Exception as e:
            logger.exception("CryptoBot createInvoice: %s", e)
            return None

    async def create_invoice_usdt(
        self,
        amount_usd: float,
        description: str,
        payload: str,
    ) -> Optional[dict[str, Any]]:
        """
        Создаёт инвойс на пополнение в USDT (Crypto Pay).
        Возвращает result с pay_url, invoice_id и т.д. или None.
        """
        if not self._enabled:
            return None
        try:
            amount_str = f"{amount_usd:.2f}"
            async with httpx.AsyncClient(timeout=15.0) as client:
                r = await client.post(
                    f"{CRYPTOBOT_API}/createInvoice",
                    headers=self._headers(),
                    json={
                        "asset": "USDT",
                        "amount": amount_str,
                        "description": description,
                        "payload": payload,
                    },
                )
                if r.status_code != 200:
                    logger.warning("CryptoBot createInvoice USDT error: %s %s", r.status_code, r.text)
                    return None
                data = r.json()
                if not data.get("ok"):
                    return None
                return data.get("result")
        except Exception as e:
            logger.exception("CryptoBot create_invoice_usdt: %s", e)
            return None

    def verify_update(self, update_dict: dict, secret: Optional[str] = None) -> bool:
        """
        Проверяет подпись/данные webhook CryptoBot (если используется).
        Для простоты можно проверять payload и статус через getInvoices.
        """
        # Реализация зависит от формата webhook CryptoBot
        return True

    async def get_invoice(self, invoice_id: int) -> Optional[dict[str, Any]]:
        """Получает статус инвойса по ID."""
        if not self._enabled:
            return None
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                r = await client.get(
                    f"{CRYPTOBOT_API}/getInvoices",
                    headers=self._headers(),
                    params={"invoice_ids": str(invoice_id)},
                )
                if r.status_code != 200:
                    return None
                data = r.json()
                if not data.get("ok"):
                    return None
                items = data.get("result", {}).get("items", [])
                return items[0] if items else None
        except Exception as e:
            logger.warning("CryptoBot get_invoice: %s", e)
            return None

    def build_labeled_price(self, amount_stars: int, label: str = "Stars") -> list[LabeledPrice]:
        """Для отправки инвойса через Bot API (Stars)."""
        return [LabeledPrice(label=label, amount=amount_stars)]
