"""
Сервис для приёма Toncoin: генерация ссылки на оплату, проверка входящих переводов.
Для продакшна можно использовать TON Connect или API кошелька.
"""
from typing import Optional
from urllib.parse import quote

from bot.config import TonConfig
from bot.utils.logger import get_logger

logger = get_logger(__name__)


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
        # Пример: TonAPI или TON Center — реализация зависит от выбранного провайдера
        # try:
        #     async with httpx.AsyncClient() as client:
        #         r = await client.get(f"https://toncenter.com/api/v2/getTransaction?hash={tx_hash}")
        #         ...
        return None
