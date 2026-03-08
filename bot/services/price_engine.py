"""
Динамический ценовой движок: курс TON/USD, пересчёт цены Stars каждые N минут.
Поддержка скидок для крупных заказов.
"""
import asyncio
from dataclasses import dataclass
from typing import Optional

import httpx

from bot.config import PriceConfig
from bot.utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class PriceQuote:
    """Цена за N Stars в выбранной валюте."""
    stars: int
    amount_usd: float
    amount_ton: Optional[float] = None
    currency: str = "USD"


class PriceEngine:
    """
    Движок цен: получает курс TON/USD, считает цену Stars с учётом скидок.
    """

    def __init__(self, config: PriceConfig):
        self.config = config
        self._ton_usd: Optional[float] = None
        self._lock = asyncio.Lock()
        self._task: Optional[asyncio.Task] = None

    def _discount_multiplier(self, stars: int) -> float:
        """Возвращает множитель цены (1.0 = без скидки, 0.95 = 5% скидка)."""
        mult = 1.0
        for threshold, tier_mult in self.config.discount_tiers:
            if stars >= threshold:
                mult = tier_mult
        return mult

    async def fetch_ton_usd(self) -> Optional[float]:
        """Загружает курс TON/USD с CoinGecko. При 429 (rate limit) возвращает None."""
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                r = await client.get(self.config.ton_usd_url)
                if r.status_code == 429:
                    logger.warning("CoinGecko rate limit (429). Используется кэш или следующий запрос позже.")
                    return None
                r.raise_for_status()
                data = r.json()
                # CoinGecko: ids=the-open-network
                price = data.get("the-open-network", {}).get("usd")
                if price is not None:
                    return float(price)
        except Exception as e:
            logger.warning("Не удалось получить курс TON/USD: %s", e)
        return None

    async def update_ton_rate(self) -> None:
        """Обновляет курс TON (вызывается периодически). При 429 курс не меняется (остаётся кэш)."""
        rate = await self.fetch_ton_usd()
        if rate is not None:
            async with self._lock:
                self._ton_usd = rate
            logger.info("Курс TON/USD обновлён: %s", rate)

    async def get_ton_usd(self) -> Optional[float]:
        """Возвращает текущий курс TON/USD (из кэша или один раз запросить)."""
        async with self._lock:
            if self._ton_usd is not None:
                return self._ton_usd
        await self.update_ton_rate()
        async with self._lock:
            return self._ton_usd

    def stars_to_usd(self, stars: int) -> float:
        """
        Переводит количество Stars в USD: 1 Star = usd_per_star USD, с учётом скидок.
        Курс задаётся в конфиге (USD_PER_STAR, по умолчанию 0.015).
        """
        mult = self._discount_multiplier(stars)
        base_usd = stars * self.config.usd_per_star
        return round(base_usd * mult, 2)

    async def quote(self, stars: int) -> PriceQuote:
        """
        Возвращает цену за указанное количество Stars в USD и TON (если доступен курс).
        """
        amount_usd = self.stars_to_usd(stars)
        amount_ton: Optional[float] = None
        ton_usd = await self.get_ton_usd()
        if ton_usd and ton_usd > 0:
            amount_ton = round(amount_usd / ton_usd, 6)
        return PriceQuote(stars=stars, amount_usd=amount_usd, amount_ton=amount_ton)

    def start_background_updater(self) -> None:
        """Запускает фоновое обновление курса каждые N секунд."""
        async def _loop():
            while True:
                await self.update_ton_rate()
                await asyncio.sleep(self.config.update_interval_seconds)

        self._task = asyncio.create_task(_loop())
        logger.info("PriceEngine: фоновое обновление курса запущено (интервал %s с)", self.config.update_interval_seconds)

    def stop_background_updater(self) -> None:
        """Останавливает фоновое обновление."""
        if self._task and not self._task.done():
            self._task.cancel()
