"""
Инлайн-кнопки главного меню бота.
"""
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton


def main_menu_kb(is_admin: bool = False) -> InlineKeyboardMarkup:
    """Главное меню: Купить Stars, Мои заказы, Профиль, Рефералы, Поддержка. Для админов — кнопка «Админ панель»."""
    rows = [
        [InlineKeyboardButton(text="🛒 Купить Stars", callback_data="menu:buy")],
        [InlineKeyboardButton(text="📋 Мои заказы", callback_data="menu:orders")],
        [InlineKeyboardButton(text="👤 Мой профиль", callback_data="menu:profile")],
        [InlineKeyboardButton(text="👥 Реферальная программа", callback_data="menu:referrals")],
        [InlineKeyboardButton(text="💬 Поддержка", callback_data="menu:support")],
    ]
    if is_admin:
        rows.append([InlineKeyboardButton(text="🔐 Админ панель", callback_data="admin:main")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def back_to_menu_kb() -> InlineKeyboardMarkup:
    """Кнопка «Назад в меню»."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ В меню", callback_data="menu:main")]
    ])
