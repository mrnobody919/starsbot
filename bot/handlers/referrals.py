"""
Реферальная программа: описание и отображение реферальной ссылки.
"""
from aiogram import Router, F
from aiogram.types import CallbackQuery
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from bot.database.models import User
from bot.keyboards import back_to_menu_kb
from bot.config import AppConfig
from bot.utils.helpers import safe_callback_answer
from bot.utils.logger import get_logger

router = Router(name="referrals")
logger = get_logger(__name__)


@router.callback_query(F.data == "menu:referrals")
async def show_referrals(callback: CallbackQuery, session: AsyncSession, config: AppConfig):
    """Показывает описание реферальной программы и ссылку пользователя."""
    result = await session.execute(
        select(User).where(User.telegram_id == callback.from_user.id)
    )
    user = result.scalar_one_or_none()
    if not user:
        await safe_callback_answer(callback, "Ошибка.", show_alert=True)
        return

    bot_username = config.bot.bot_username or "your_bot"
    ref_link = f"https://t.me/{bot_username}?start=ref_{user.referral_code}"
    percent = int(config.referral_percent)

    text = (
        f"👥 <b>Реферальная программа</b>\n\n"
        f"Приглашайте друзей по ссылке — вы получаете <b>{percent}%</b> от суммы Stars, "
        f"которые они купят (начисляется бонусами на ваш счёт).\n\n"
        f"🔗 Ваша ссылка:\n<code>{ref_link}</code>\n\n"
        f"👥 Приглашено: {user.referrals_count}\n"
        f"💰 Получено бонусов: {user.referral_reward_total:.0f} ⭐"
    )
    await callback.message.edit_text(text, reply_markup=back_to_menu_kb(), parse_mode="HTML")
    await safe_callback_answer(callback)
