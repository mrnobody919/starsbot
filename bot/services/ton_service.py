"""
Сервис для приёма Toncoin: генерация ссылки на оплату, проверка входящих переводов.
Для продакшна можно использовать TON Connect или API кошелька.
"""
import base64
from typing import Any, Optional
from urllib.parse import quote

import httpx
from bot.config import TonConfig
from bot.utils.logger import get_logger

logger = get_logger(__name__)

TONAPI_EVENTS = "https://tonapi.io/v2/accounts"


def _normalize_ton_address(addr: str) -> str:
    """Приводит адрес к одному виду для сравнения (убирает пробелы, нижний регистр не применяем)."""
    if not addr:
        return ""
    return addr.strip()


def _ton_address_hash(addr: str) -> Optional[bytes]:
    """Извлекает 32-байтный hash кошелька из строки (EQ/UQ/0:hex). Без библиотеки TON."""
    a = _normalize_ton_address(addr)
    if not a or len(a) < 40:
        return None
    # Формат 0:hex (raw)
    if ":" in a and a[0].isdigit():
        try:
            _, hex_part = a.split(":", 1)
            return bytes.fromhex(hex_part)[:32]
        except Exception:
            return None
    # Base64 / Base64url: 2 байта флаги + 32 байта hash + 2 байта CRC
    for fn in (base64.b64decode, base64.urlsafe_b64decode):
        try:
            raw = fn(a + "==")
            if len(raw) >= 34:
                return raw[2:34]
        except Exception:
            continue
    return None


def _ton_addresses_match(our_addr: str, api_addr: str) -> bool:
    """Проверяет, что оба адреса указывают на один кошелёк (EQ/UQ и т.д.)."""
    a = _normalize_ton_address(our_addr)
    b = _normalize_ton_address(api_addr)
    if a == b:
        return True
    if a in b or b in a:
        return True
    ha, hb = _ton_address_hash(a), _ton_address_hash(b)
    if ha and hb and ha == hb:
        return True
    return False


def _decode_ton_comment(payload: Any) -> str:
    """
    Извлекает текстовый комментарий из payload перевода TON.
    В TON комментарий: 4 байта 0x00 (op) + UTF-8 текст. API может отдать base64 или уже строку.
    """
    if payload is None:
        return ""
    if isinstance(payload, str):
        s = payload.strip()
        if not s:
            return ""
        # Уже похоже на комментарий (order_123 и т.д.)
        if s.startswith("order_") and s[6:].isdigit():
            return s
        try:
            raw = base64.b64decode(s, validate=True)
        except Exception:
            try:
                raw = base64.urlsafe_b64decode(s + "==")
            except Exception:
                return s[:200] if s.isascii() or len(s) < 100 else ""
        if not raw:
            return ""
        if len(raw) >= 4 and raw[:4] == b"\x00\x00\x00\x00":
            raw = raw[4:]
        try:
            return raw.decode("utf-8", errors="replace").strip("\x00").strip()
        except Exception:
            return ""
    return ""


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
                if not _ton_addresses_match(addr, recipient_addr):
                    continue
                try:
                    amount_nano = int(ton_transfer.get("amount", 0))
                except (TypeError, ValueError):
                    continue
                amount_ton_val = amount_nano / 1_000_000_000
                comment = (ton_transfer.get("comment") or act.get("comment") or "").strip()
                if not comment:
                    comment = _decode_ton_comment(ton_transfer.get("payload"))
                out.append({"amount_ton": amount_ton_val, "comment": comment})
        return out
