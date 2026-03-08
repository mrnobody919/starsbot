"""
HTTP-сервер для приёма webhook от FreeKassa.
Запускается в том же процессе, что и бот (порт из WEBHOOK_PORT или 8080).
"""
import os
from aiohttp import web

from bot.services.freekassa_service import FreeKassaService
from bot.handlers.payments import handle_freekassa_paid, handle_freekassa_topup
from bot.utils.logger import get_logger

logger = get_logger(__name__)


def create_webhook_app(bot, session_factory, config):
    """Создаёт aiohttp Application с маршрутом POST /webhook/freekassa."""

    async def freekassa_webhook(request: web.Request) -> web.Response:
        """Принимает GET или POST от FreeKassa, проверяет подпись, помечает заказ оплаченным."""
        if not config.freekassa.enabled:
            return web.Response(status=503, text="FreeKassa not configured")
        try:
            if request.method == "GET":
                payload = dict(request.query)
            else:
                data = await request.post()
                payload = dict(data)
        except Exception as e:
            logger.warning("FreeKassa webhook parse error: %s", e)
            return web.Response(status=400, text="Bad request")

        fk = FreeKassaService(config.freekassa)
        if not fk.verify_notification(payload):
            logger.warning("FreeKassa webhook invalid signature")
            return web.Response(status=400, text="Invalid signature")

        order_id_str = (payload.get("MERCHANT_ORDER_ID") or "").strip()
        if not order_id_str:
            return web.Response(status=400, text="No order id")

        async with session_factory() as session:
            try:
                if order_id_str.startswith("topup_"):
                    # Пополнение баланса: зачисляем на balance_usd
                    amount_rub = float(payload.get("AMOUNT") or 0)
                    if amount_rub <= 0:
                        return web.Response(status=400, text="Bad amount")
                    ok = await handle_freekassa_topup(
                        session, bot, config, order_id_str, amount_rub
                    )
                else:
                    try:
                        order_id = int(order_id_str)
                    except ValueError:
                        return web.Response(status=400, text="Bad order id")
                    ok = await handle_freekassa_paid(session, bot, config, order_id)
                await session.commit()
            except Exception as e:
                await session.rollback()
                logger.exception("FreeKassa webhook handle error: %s", e)
                return web.Response(status=500, text="Error")
        return web.Response(text="OK")

    app = web.Application()
    app.router.add_route("GET", "/webhook/freekassa", freekassa_webhook)
    app.router.add_route("POST", "/webhook/freekassa", freekassa_webhook)
    # Health check для Railway
    app.router.add_get("/health", lambda r: web.Response(text="ok"))
    return app
