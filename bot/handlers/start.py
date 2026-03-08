"""
Обработчик /start и главного меню (инлайн-кнопки).
"""
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import CommandStart, Command
from sqlalchemy.ext.asyncio import AsyncSession

from bot.database import get_or_create_user
from bot.keyboards import main_menu_kb, back_to_menu_kb
from bot.config import AppConfig
from bot.utils.logger import get_logger

logger = get_logger(__name__)

router = Router(name="start")


def _parse_start_ref(text: str | None) -> str | None:
    """Из /start ref_XXXX извлекает реферальный код (без префикса ref_) для поиска в БД."""
    if not text or not text.startswith("/start "):
        return None
    payload = text.split(maxsplit=1)[1].strip()
    if payload.startswith("ref_"):
        return payload[4:]  # код без префикса для сравнения с User.referral_code
    return None


@router.message(CommandStart())
async def cmd_start(message: Message, session: AsyncSession, config: AppConfig):
    """
    Команда /start: регистрируем/обновляем пользователя, показываем меню.
    Если ссылка вида /start ref_CODE — сохраняем реферера.
    """
    user = message.from_user
    if not user:
        return
    ref_code = _parse_start_ref(message.text)
    db_user, created = await get_or_create_user(
        session,
        telegram_id=user.id,
        username=user.username,
        referral_code_from_start=ref_code,
    )
    await session.commit()
    if created:
        logger.info("New user: %s (%s)", user.id, user.username)

    bot_username = config.bot.bot_username or (message.bot.username or "your_bot")
    welcome = (
        "👋 Добро пожаловать!\n\n"
        "Здесь вы можете купить Telegram Stars.\n\n"
        "Выберите действие:"
    )
    await message.answer(welcome, reply_markup=main_menu_kb())


@router.callback_query(F.data == "menu:main")
async def menu_main(callback: CallbackQuery, session: AsyncSession):
    """Возврат в главное меню по кнопке «В меню»."""
    await callback.message.edit_text(
        "Выберите действие:",
        reply_markup=main_menu_kb()
    )
    await callback.answer()


@router.callback_query(F.data == "menu:support")
async def menu_support(callback: CallbackQuery, config: AppConfig):
    """Поддержка: ссылка или текст."""
    link = config.support_link or "https://t.me/"
    await callback.message.edit_text(
        f"💬 Поддержка: {link}",
        reply_markup=back_to_menu_kb()
    )
    await callback.answer()
