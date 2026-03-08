"""
Конфигурация бота. Все настройки загружаются из переменных окружения.
Готово для деплоя на Railway/VPS.
"""
import os
from dataclasses import dataclass
from typing import Optional


@dataclass
class DatabaseConfig:
    """Настройки подключения к PostgreSQL."""
    url: str

    @classmethod
    def from_env(cls) -> "DatabaseConfig":
        return cls(
            url=os.getenv("DATABASE_URL", "postgresql://user:pass@localhost:5432/stars_bot")
        )


@dataclass
class BotConfig:
    """Настройки Telegram-бота."""
    token: str
    bot_username: Optional[str] = None  # для реферальных ссылок

    @classmethod
    def from_env(cls) -> "BotConfig":
        token = os.getenv("BOT_TOKEN")
        if not token:
            raise ValueError("BOT_TOKEN не задан в переменных окружения")
        return cls(
            token=token,
            bot_username=os.getenv("BOT_USERNAME")
        )


@dataclass
class CryptoBotConfig:
    """Настройки CryptoBot (Telegram Stars через @CryptoBot)."""
    api_token: Optional[str] = None
    merchant_id: Optional[str] = None

    @classmethod
    def from_env(cls) -> "CryptoBotConfig":
        return cls(
            api_token=os.getenv("CRYPTOBOT_API_TOKEN"),
            merchant_id=os.getenv("CRYPTOBOT_MERCHANT_ID")
        )


@dataclass
class TonConfig:
    """Настройки TON кошелька для приёма Toncoin."""
    wallet_address: Optional[str] = None
    api_key: Optional[str] = None  # для TON API (toncenter и т.д.)

    @classmethod
    def from_env(cls) -> "TonConfig":
        return cls(
            wallet_address=os.getenv("TON_WALLET_ADDRESS"),
            api_key=os.getenv("TON_API_KEY")
        )


@dataclass
class FreeKassaConfig:
    """Настройки FreeKassa. Если переменные не заданы — оплата через FreeKassa отключена."""
    merchant_id: str
    secret_word_1: str
    secret_word_2: str
    secret_word_3: Optional[str] = None
    webhook_secret: Optional[str] = None

    @property
    def enabled(self) -> bool:
        """True, если все обязательные поля заданы и FreeKassa доступна."""
        return bool(self.merchant_id and self.secret_word_1 and self.secret_word_2)

    @classmethod
    def from_env(cls) -> "FreeKassaConfig":
        mid = os.getenv("FREEKASSA_MERCHANT_ID") or ""
        s1 = os.getenv("FREEKASSA_SECRET_WORD_1") or ""
        s2 = os.getenv("FREEKASSA_SECRET_WORD_2") or ""
        return cls(
            merchant_id=mid,
            secret_word_1=s1,
            secret_word_2=s2,
            secret_word_3=os.getenv("FREEKASSA_SECRET_WORD_3"),
            webhook_secret=os.getenv("FREEKASSA_WEBHOOK_SECRET")
        )


@dataclass
class PriceConfig:
    """Настройки ценового движка."""
    stars_per_usd: float = 100.0  # сколько Stars за 1 USD
    ton_usd_url: str = "https://api.coingecko.com/api/v3/simple/price?ids=the-open-network&vs_currencies=usd"
    update_interval_seconds: int = 300  # 5 минут
    # Скидки: (мин. сумма заказа в Stars, множитель цены 0.0-1.0)
    discount_tiers: tuple = ((1000, 0.98), (5000, 0.95), (10000, 0.92))

    @classmethod
    def from_env(cls) -> "PriceConfig":
        return cls(
            stars_per_usd=float(os.getenv("STARS_PER_USD", "100")),
            update_interval_seconds=int(os.getenv("PRICE_UPDATE_INTERVAL", "300"))
        )


@dataclass
class AntifraudConfig:
    """Настройки антифрода."""
    max_orders_per_minute: int = 3
    min_stars_per_order: int = 50
    max_stars_per_order: int = 50000

    @classmethod
    def from_env(cls) -> "AntifraudConfig":
        return cls(
            max_orders_per_minute=int(os.getenv("ANTIFRAUD_MAX_ORDERS_PER_MINUTE", "3")),
            min_stars_per_order=int(os.getenv("MIN_STARS_PER_ORDER", "50")),
            max_stars_per_order=int(os.getenv("MAX_STARS_PER_ORDER", "50000"))
        )


@dataclass
class AppConfig:
    """Агрегированная конфигурация приложения."""
    bot: BotConfig
    database: DatabaseConfig
    cryptobot: CryptoBotConfig
    ton: TonConfig
    freekassa: FreeKassaConfig
    price: PriceConfig
    antifraud: AntifraudConfig
    admin_ids: list[int]
    referral_percent: float = 10.0
    support_link: Optional[str] = None
    webhook_base_url: Optional[str] = None  # для FreeKassa webhook на Railway
    rub_per_usd: float = 100.0  # курс ₽/USD для пополнения баланса из FreeKassa

    @classmethod
    def from_env(cls) -> "AppConfig":
        admin_str = os.getenv("ADMIN_IDS", "")
        admin_ids = [int(x.strip()) for x in admin_str.split(",") if x.strip()]
        return cls(
            bot=BotConfig.from_env(),
            database=DatabaseConfig.from_env(),
            cryptobot=CryptoBotConfig.from_env(),
            ton=TonConfig.from_env(),
            freekassa=FreeKassaConfig.from_env(),
            price=PriceConfig.from_env(),
            antifraud=AntifraudConfig.from_env(),
            admin_ids=admin_ids,
            referral_percent=float(os.getenv("REFERRAL_PERCENT", "10")),
            support_link=os.getenv("SUPPORT_LINK"),
            webhook_base_url=os.getenv("WEBHOOK_BASE_URL"),
            rub_per_usd=float(os.getenv("RUB_PER_USD", "100")),
        )


def load_config() -> AppConfig:
    """Загружает конфигурацию из окружения. Вызывать при старте бота."""
    return AppConfig.from_env()
