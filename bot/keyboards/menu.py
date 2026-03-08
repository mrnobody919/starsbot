"""
Инлайн-кнопки главного меню бота.
"""
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton


def main_menu_kb() -> InlineKeyboardMarkup:
    """Главное меню: Купить Stars, Мои заказы, Профиль, Рефералы, Поддержка."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🛒 Купить Stars", callback_data="menu:buy")],
        [InlineKeyboardButton(text="📋 Мои заказы", callback_data="menu:orders")],
        [InlineKeyboardButton(text="👤 Мой профиль", callback_data="menu:profile")],
        [InlineKeyboardButton(text="👥 Реферальная программа", callback_data="menu:referrals")],
        [InlineKeyboardButton(text="💬 Поддержка", callback_data="menu:support")],
    ])


def back_to_menu_kb() -> InlineKeyboardMarkup:
    """Кнопка «Назад в меню»."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ В меню", callback_data="menu:main")]
    ])
