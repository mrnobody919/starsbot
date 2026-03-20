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
        [InlineKeyboardButton(text="💎 Цена Stars (100 ⭐) + Маржа", callback_data="admin:price")],
        [InlineKeyboardButton(text="👑 Premium цены (USD)", callback_data="admin:premium:price")],
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


def admin_order_actions_kb(order_id: int, order_type: str = "stars") -> InlineKeyboardMarkup:
    """Действия по заказу: завершить (Stars/Premium) и отменить."""
    order_type_norm = (order_type or "stars").lower()
    complete_text = "✅ Активировал Premium" if order_type_norm == "premium" else "✅ Отправил Stars"
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=complete_text, callback_data=f"admin:order:complete:{order_id}")],
        [InlineKeyboardButton(text="❌ Отменить заказ", callback_data=f"admin:order:cancel:{order_id}")],
        [InlineKeyboardButton(text="◀️ К заказам", callback_data="admin:orders")]
    ])


def order_stars_sent_kb(order_id: int) -> InlineKeyboardMarkup:
    """Одна кнопка под сообщением о новом заказе: «Stars отправлены» — помечает заказ выполненным и уведомляет покупателя."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⭐ Stars отправлены", callback_data=f"admin:order:complete:{order_id}")]
    ])


def order_premium_sent_kb(order_id: int) -> InlineKeyboardMarkup:
    """Одна кнопка под сообщением о новом заказе Premium: помечает заказ выполненным."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👑 Premium активирован", callback_data=f"admin:order:complete:{order_id}")]
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
