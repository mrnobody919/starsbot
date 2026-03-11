"""
Точка входа: инициализация БД, бота, роутеров и запуск polling.
Готово для деплоя на Railway/VPS.
"""
import asyncio
import logging
import os

# Загрузка .env при локальном запуске
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from aiohttp import web
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from bot.config import load_config
from bot.database import init_db, ensure_balance_usd_column
from bot.middlewares import AntifloodMiddleware, DbSessionMiddleware
from bot.handlers import start, buy_stars, payments, profile, referrals, admin
from bot.services.price_engine import PriceEngine
from bot.services.payment_checker import PaymentChecker
from bot.services.cryptobot_service import CryptoBotService
from bot.services.ton_service import TonService
from bot.webhook_server import create_webhook_app
from bot.utils.logger import setup_logger

# Логирование
LOG_LEVEL = getattr(logging, os.getenv("LOG_LEVEL", "INFO").upper(), logging.INFO)
logger = setup_logger("stars_bot", level=LOG_LEVEL)


async def main():
    """Запуск бота."""
    config = load_config()
    session_factory = await init_db(config.database.url)
    # Гарантированно добавить колонку balance_usd при каждом старте (миграция для старых БД)
    await ensure_balance_usd_column(config.database.url)

    bot = Bot(
        token=config.bot.token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher()
    dp["config"] = config
    dp["session_factory"] = session_factory

    # Фоновое обновление курса TON/USD
    price_engine = PriceEngine(config.price)
    async def price_loop():
        while True:
            try:
                await price_engine.update_ton_rate()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.warning("Price loop error: %s", e)
            await asyncio.sleep(config.price.update_interval_seconds)
    price_task = asyncio.create_task(price_loop())

    # Опрос оплат CryptoBot и TON (подтверждение заказа после оплаты)
    payment_checker = PaymentChecker(
        cryptobot=CryptoBotService(config.cryptobot),
        ton=TonService(config.ton),
    )
    payment_checker.start_polling(
        session_factory,
        bot,
        config,
        price_engine=price_engine,
        interval_seconds=int(os.getenv("PAYMENT_CHECK_INTERVAL", "45")),
    )

    # Middlewares: сессия БД и антифлуд
    dp.message.middleware(DbSessionMiddleware(session_factory))
    dp.callback_query.middleware(DbSessionMiddleware(session_factory))
    dp.message.middleware(AntifloodMiddleware(rate_limit=5, period_sec=3.0))

    class ConfigMiddleware:
        async def __call__(self, handler, event, data):
            data["config"] = config
            return await handler(event, data)

    dp.message.middleware(ConfigMiddleware())
    dp.callback_query.middleware(ConfigMiddleware())
    dp.pre_checkout_query.middleware(DbSessionMiddleware(session_factory))
    dp.pre_checkout_query.middleware(ConfigMiddleware())

    # Роутеры
    dp.include_router(start.router)
    dp.include_router(buy_stars.router)
    dp.include_router(profile.router)
    dp.include_router(referrals.router)
    dp.include_router(payments.router)
    dp.include_router(admin.router)

    # Webhook-сервер для FreeKassa (на Railway используется PORT, иначе WEBHOOK_PORT или 8080)
    webhook_port = int(os.getenv("PORT") or os.getenv("WEBHOOK_PORT", "8080"))
    web_app = create_webhook_app(bot, session_factory, config)
    runner = web.AppRunner(web_app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", webhook_port)
    await site.start()
    logger.info("Webhook server listening on port %s", webhook_port)

    logger.info("Bot starting...")
    try:
        await dp.start_polling(bot)
    finally:
        await runner.cleanup()
        price_task.cancel()
        payment_checker.stop_polling()
        try:
            await price_task
        except asyncio.CancelledError:
            pass


if __name__ == "__main__":
    asyncio.run(main())
