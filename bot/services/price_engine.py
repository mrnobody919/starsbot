"""
Динамический ценовой движок: курс TON/USD, пересчёт цены Stars каждые N минут.
Поддержка скидок для крупных заказов.
"""
import asyncio
from dataclasses import dataclass
from typing import Optional

import httpx
import time

from bot.config import PriceConfig
from bot.utils.logger import get_logger

logger = get_logger(__name__)


# Общий кэш курса для всех экземпляров PriceEngine.
# В проекте PriceEngine часто создаётся заново в хендлерах, поэтому
# локальный кэш экземпляра сбрасывался и бот постоянно ловил 429.
_shared = {
    "lock": asyncio.Lock(),
    "ton_usd": None,  # type: Optional[float]
    "ton_rub": None,  # type: Optional[float]
    "next_fetch_at": 0.0,  # type: float
}


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
        self._task: Optional[asyncio.Task] = None

    def _discount_multiplier(self, stars: int) -> float:
        """Возвращает множитель цены (1.0 = без скидки, 0.95 = 5% скидка)."""
        mult = 1.0
        for threshold, tier_mult in self.config.discount_tiers:
            if stars >= threshold:
                mult = tier_mult
        return mult

    async def fetch_ton_prices(self) -> tuple[Optional[float], Optional[float]]:
        """
        Загружает курс TON к USD и RUB.

        Поддерживаются:
        - CoinGecko: { "the-open-network": { "usd": 1.33, "rub": 104.78 } }
        - Binance: { "price": "5.12" } (тогда RUB не возвращается)
        """
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                r = await client.get(self.config.ton_usd_url)
                if r.status_code == 429:
                    logger.warning("Rate limit (429). Используется кэш курса.")
                    # Кулдаун на повторные попытки загрузки курса
                    _shared["next_fetch_at"] = time.time() + int(getattr(self.config, "update_interval_seconds", 600))
                    return None, None
                r.raise_for_status()
                data = r.json()
                # Binance: {"symbol":"TONUSDT","price":"5.12"}
                price = data.get("price")
                if price is not None:
                    return float(price), None

                # CoinGecko: {"the-open-network":{"usd":1.33,"rub":104.78}}
                cg = data.get("the-open-network") or {}
                usd = cg.get("usd")
                rub = cg.get("rub")
                usd_val = float(usd) if usd is not None else None
                rub_val = float(rub) if rub is not None else None
                return usd_val, rub_val
        except Exception as e:
            logger.warning("Не удалось получить курс TON: %s", e)
            # Кулдаун, чтобы на временных сбоях не долбить API
            _shared["next_fetch_at"] = time.time() + 300
        return None, None

    async def update_ton_rate(self) -> None:
        """Обновляет курсы TON/USD и TON/RUB. При 429 курс не меняется (остаётся кэш)."""
        # Если недавно уже были ошибки загрузки — пропускаем попытку.
        now = time.time()
        if now < _shared["next_fetch_at"]:
            return
        usd, rub = await self.fetch_ton_prices()
        async with _shared["lock"]:
            if usd is not None and usd > 0:
                _shared["ton_usd"] = usd
            if rub is not None and rub > 0:
                _shared["ton_rub"] = rub
        if usd is not None and usd > 0:
            logger.info("Курс TON/USD обновлён: %s", usd)
        if rub is not None and rub > 0:
            logger.info("Курс TON/RUB обновлён: %s", rub)

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
        async with _shared["lock"]:
            if _shared["ton_usd"] is not None and _shared["ton_usd"] > 0:
                return _shared["ton_usd"]
        await self.update_ton_rate()
        async with _shared["lock"]:
            if _shared["ton_usd"] and _shared["ton_usd"] > 0:
                return _shared["ton_usd"]

        # Если курс недоступен (например, провайдер блокирует запросы),
        # возвращаем консервативный фиксированный fallback, чтобы бот не зависал.
        fallback = 1.33  # USD за 1 TON (примерно соответствует ~0.751 TON за 1$)
        logger.warning("TON/USD недоступен — используется fallback=%s", fallback)
        return fallback

    async def get_ton_rub(self) -> Optional[float]:
        """Возвращает курс: сколько RUB стоит 1 TON. Сначала пытается обновить кэш."""
        async with _shared["lock"]:
            if _shared["ton_rub"] is not None and _shared["ton_rub"] > 0:
                return _shared["ton_rub"]
        await self.update_ton_rate()
        async with _shared["lock"]:
            if _shared["ton_rub"] and _shared["ton_rub"] > 0:
                return _shared["ton_rub"]
        return None

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
