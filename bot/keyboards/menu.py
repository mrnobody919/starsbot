"""
Инлайн-кнопки главного меню бота.
"""
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton


def main_menu_kb(is_admin: bool = False) -> InlineKeyboardMarkup:
    """Главное меню: Купить/Продать звёзды, Premium, Профиль, Рефералка, Поддержка, Мои заказы. Для админов — Админ панель."""
    rows = [
        [
            InlineKeyboardButton(text="⭐️ Купить звёзды", callback_data="menu:buy"),
            InlineKeyboardButton(text="💸 Продать звёзды", callback_data="menu:sell"),
        ],
        [InlineKeyboardButton(text="👑 Premium", callback_data="menu:premium")],
        [
            InlineKeyboardButton(text="👤 Профиль", callback_data="menu:profile"),
            InlineKeyboardButton(text="🫂 Рефералка", callback_data="menu:referrals"),
        ],
        [
            InlineKeyboardButton(text="💬 Поддержка", callback_data="menu:support"),
            InlineKeyboardButton(text="📋 Мои заказы", callback_data="menu:orders"),
        ],
    ]
    if is_admin:
        rows.append([InlineKeyboardButton(text="🔐 Админ панель", callback_data="admin:main")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def back_to_menu_kb() -> InlineKeyboardMarkup:
    """Кнопка «Назад в меню»."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ В меню", callback_data="menu:main")]
    ])
