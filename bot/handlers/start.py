"""
Обработчик /start и главного меню (инлайн-кнопки).
"""
from pathlib import Path

from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, FSInputFile
from aiogram.filters import CommandStart, Command
from sqlalchemy.ext.asyncio import AsyncSession

from bot.database import get_or_create_user
from bot.keyboards import main_menu_kb, back_to_menu_kb
from bot.config import AppConfig
from bot.utils.logger import get_logger

logger = get_logger(__name__)

router = Router(name="start")


def _get_menu_banner_path() -> Path | None:
    """Путь к баннеру над меню (bot/static/menu_banner.png). Если файла нет — None."""
    base = Path(__file__).resolve().parent.parent
    path = base / "static" / "menu_banner.png"
    return path if path.is_file() else None


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
    Если ссылка вида /start ref_CODE — сохраняем реферера. Админам показывается кнопка «Админ панель».
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

    is_admin = user.id in config.admin_ids
    welcome = (
        "🌟 Здравствуйте!\n\n"
        "С помощью нашего сервиса вы сможете мгновенно купить или продать Telegram Stars, "
        "а также оформить Telegram Premium за рубли или криптовалюту."
    )
    banner_path = _get_menu_banner_path()
    if banner_path:
        await message.answer_photo(
            photo=FSInputFile(banner_path),
            caption=welcome,
            reply_markup=main_menu_kb(is_admin=is_admin),
        )
    else:
        await message.answer(welcome, reply_markup=main_menu_kb(is_admin=is_admin))


@router.callback_query(F.data == "menu:main")
async def menu_main(callback: CallbackQuery, session: AsyncSession, config: AppConfig):
    """Возврат в главное меню по кнопке «В меню». Если есть баннер — показываем его над меню."""
    is_admin = callback.from_user.id in config.admin_ids
    caption = "Выберите действие:"
    banner_path = _get_menu_banner_path()
    try:
        if banner_path:
            await callback.message.delete()
            await callback.message.answer_photo(
                photo=FSInputFile(banner_path),
                caption=caption,
                reply_markup=main_menu_kb(is_admin=is_admin),
            )
        else:
            await callback.message.edit_text(
                caption,
                reply_markup=main_menu_kb(is_admin=is_admin),
            )
    except Exception as e:
        logger.warning("menu_main: %s", e)
        await callback.message.edit_text(
            caption,
            reply_markup=main_menu_kb(is_admin=is_admin),
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
