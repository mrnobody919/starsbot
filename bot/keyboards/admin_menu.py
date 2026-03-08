"""
Клавиатуры админ-панели: заказы, статистика, пользователи, рассылка.
"""
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton


def admin_main_kb() -> InlineKeyboardMarkup:
    """Главное меню админки."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📋 Оплаченные заказы", callback_data="admin:orders")],
        [InlineKeyboardButton(text="📊 Статистика", callback_data="admin:stats")],
        [InlineKeyboardButton(text="👥 Пользователи", callback_data="admin:users")],
        [InlineKeyboardButton(text="💵 Курс Stars ($)", callback_data="admin:price")],
        [InlineKeyboardButton(text="📤 Рассылка", callback_data="admin:broadcast")],
        [InlineKeyboardButton(text="◀️ Закрыть", callback_data="admin:close")]
    ])


def admin_price_back_kb() -> InlineKeyboardMarkup:
    """Назад из экрана курса Stars."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ Назад", callback_data="admin:main")]
    ])


def admin_orders_filter_kb() -> InlineKeyboardMarkup:
    """Фильтры заказов: все, ожидают отправки, по дате."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="⏳ Ожидают", callback_data="admin:orders:filter:waiting"),
            InlineKeyboardButton(text="✅ Все", callback_data="admin:orders:filter:all"),
        ],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="admin:main")]
    ])


def admin_order_actions_kb(order_id: int) -> InlineKeyboardMarkup:
    """Действия по заказу: Отправил Stars, Отменить."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Отправил Stars", callback_data=f"admin:order:complete:{order_id}")],
        [InlineKeyboardButton(text="❌ Отменить заказ", callback_data=f"admin:order:cancel:{order_id}")],
        [InlineKeyboardButton(text="◀️ К заказам", callback_data="admin:orders")]
    ])


def admin_user_actions_kb(user_id: int, is_blocked: bool) -> InlineKeyboardMarkup:
    """Действия по пользователю: заблокировать/разблокировать."""
    if is_blocked:
        btn = InlineKeyboardButton(text="🔓 Разблокировать", callback_data=f"admin:user:unblock:{user_id}")
    else:
        btn = InlineKeyboardButton(text="🚫 Заблокировать", callback_data=f"admin:user:block:{user_id}")
    return InlineKeyboardMarkup(inline_keyboard=[
        [btn],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="admin:users")]
    ])


def admin_confirm_broadcast_kb() -> InlineKeyboardMarkup:
    """Подтверждение рассылки."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Отправить", callback_data="admin:broadcast:confirm"),
            InlineKeyboardButton(text="❌ Отмена", callback_data="admin:main"),
        ]
    ])
