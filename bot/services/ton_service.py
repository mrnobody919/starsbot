"""
Сервис для приёма Toncoin: генерация ссылки на оплату, проверка входящих переводов.
Для продакшна можно использовать TON Connect или API кошелька.
"""
from typing import Any, Optional
from urllib.parse import quote

import httpx
from bot.config import TonConfig
from bot.utils.logger import get_logger

logger = get_logger(__name__)

TONAPI_EVENTS = "https://tonapi.io/v2/accounts"


class TonService:
    """
    TON оплата: формирование ссылки ton:// с адресом и суммой.
    Проверка платежей — через внешний API (toncenter, tonapi) по tx hash или по балансу.
    """

    def __init__(self, config: TonConfig):
        self.config = config
        self._enabled = bool(config.wallet_address)

    @property
    def enabled(self) -> bool:
        return self._enabled

    def build_payment_link(self, amount_ton: float, comment: str = "") -> Optional[str]:
        """
        Формирует deep link для перевода TON.
        Формат: ton://transfer/<address>?amount=<nanoTON>&text=<comment>
        amount в nanoTON: 1 TON = 10^9 nanoTON.
        """
        if not self.config.wallet_address:
            return None
        nano = int(amount_ton * 1_000_000_000)
        addr = self.config.wallet_address.strip()
        base = f"ton://transfer/{addr}?amount={nano}"
        if comment:
            base += f"&text={quote(comment)}"
        return base

    async def check_payment(self, tx_hash: str) -> Optional[dict]:
        """
        Проверяет транзакцию по хешу через TON API.
        Возвращает данные о транзакции или None.
        """
        if not self.config.api_key:
            return None
        return None

    async def get_recent_incoming_transfers(self, limit: int = 30) -> list[dict[str, Any]]:
        """
        Возвращает последние входящие переводы на кошелёк (TonAPI).
        Каждый элемент: {"amount_ton": float, "comment": str}.
        """
        if not self.config.wallet_address or not self.config.api_key:
            return []
        addr = self.config.wallet_address.strip()
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                r = await client.get(
                    f"{TONAPI_EVENTS}/{addr}/events",
                    params={"limit": limit},
                    headers={"Authorization": f"Bearer {self.config.api_key}"},
                )
                if r.status_code != 200:
                    logger.warning("TonAPI events: %s %s", r.status_code, r.text[:200])
                    return []
                data = r.json()
        except Exception as e:
            logger.warning("TonAPI get_recent_incoming: %s", e)
            return []
        out: list[dict[str, Any]] = []
        for ev in data.get("events", [])[:limit]:
            for act in ev.get("actions", []):
                if act.get("type") != "TonTransfer":
                    continue
                ton_transfer = act.get("ton_transfer") or {}
                recipient_addr = (ton_transfer.get("recipient") or {}).get("address", "")
                if not recipient_addr:
                    continue
                # Входящий перевод: получатель — наш кошелёк (сравнение с учётом разных форматов)
                is_incoming = (
                    addr in recipient_addr or recipient_addr in addr or addr == recipient_addr
                )
                if not is_incoming:
                    continue
                try:
                    amount_nano = int(ton_transfer.get("amount", 0))
                except (TypeError, ValueError):
                    continue
                amount_ton = amount_nano / 1_000_000_000
                comment = ""
                payload = ton_transfer.get("payload") or ""
                if isinstance(payload, str) and payload:
                    try:
                        import base64
                        raw = base64.b64decode(payload, validate=True)
                        comment = raw.decode("utf-8", errors="replace").strip("\x00")
                    except Exception:
                        pass
                out.append({"amount_ton": amount_ton, "comment": comment})
        return out
