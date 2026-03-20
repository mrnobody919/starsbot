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
        """
        Загружает курс TON/USD с настроенного URL.
        По умолчанию Binance (TONUSDT): {"symbol":"TONUSDT","price":"5.12"} → 5.12 USD за 1 TON.
        Поддерживается и CoinGecko: {"the-open-network":{"usd":1.33}} — задайте TON_USD_URL в .env.
        """
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                r = await client.get(self.config.ton_usd_url)
                if r.status_code == 429:
                    logger.warning("Rate limit (429). Используется кэш курса.")
                    return None
                r.raise_for_status()
                data = r.json()
                # Binance: {"symbol":"TONUSDT","price":"5.12"}
                price = data.get("price")
                if price is not None:
                    return float(price)
                # CoinGecko: {"the-open-network":{"usd":1.33}}
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
        """
        Возвращает курс: сколько USD стоит 1 TON. Сумма в TON = сумма_usd / get_ton_usd().
        Приоритет: 1) TON_USD_RATE, 2) TON_PER_STAR, 3) API (по умолчанию Binance TONUSDT).
        TON_USD_RATE можно задать в двух форматах:
        - больше 1: 1 TON = N USD (например 1.33);
        - от 0 до 1: 1 USD = N TON (например 0.751 → считаем 1 TON = 1/0.751 USD).
        """
        ton_usd_rate = getattr(self.config, "ton_usd_rate", None)
        if ton_usd_rate and ton_usd_rate > 0:
            # 0 < rate <= 1 обычно значит "TON за 1 USD" (0.751 TON/$)
            if ton_usd_rate <= 1.0:
                return 1.0 / ton_usd_rate  # 1 TON = 1/0.751 ≈ 1.33 USD
            return ton_usd_rate  # > 1: 1 TON = rate USD
        async with self._lock:
            if self._ton_usd is not None:
                return self._ton_usd
        await self.update_ton_rate()
        async with self._lock:
            if self._ton_usd and self._ton_usd > 0:
                return self._ton_usd

        # Если курс недоступен (например, провайдер блокирует запросы),
        # возвращаем консервативный фиксированный fallback, чтобы бот не зависал.
        fallback = 1.33  # USD за 1 TON (примерно соответствует ~0.751 TON за 1$)
        logger.warning("TON/USD недоступен — используется fallback=%s", fallback)
        return fallback

    def stars_to_usd_with_rate(self, stars: int, usd_per_star: float) -> float:
        """Считает USD за stars по заданному курсу (с учётом скидок)."""
        mult = self._discount_multiplier(stars)
        return round(stars * usd_per_star * mult, 2)

    async def quote(self, stars: int, usd_per_star_override: Optional[float] = None) -> PriceQuote:
        """
        Возвращает цену за указанное количество Stars в USD и TON.
        usd_per_star_override: курс из админки (1 Star = X USD); если None — из конфига.
        """
        if usd_per_star_override is None or usd_per_star_override <= 0:
            raise ValueError("usd_per_star_override обязателен (и должен быть > 0) для расчёта цены.")
        amount_usd = self.stars_to_usd_with_rate(stars, usd_per_star_override)
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
