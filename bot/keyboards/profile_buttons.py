"""
Кнопки для раздела профиля и заказов.
"""
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton


def profile_kb() -> InlineKeyboardMarkup:
    """Профиль: кнопка назад в меню."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ В меню", callback_data="menu:main")]
    ])


def orders_list_kb(orders: list, page: int = 0, per_page: int = 5) -> InlineKeyboardMarkup:
    """
    Список заказов пользователя с пагинацией.
    orders: список Order с id, stars_amount, delivery_status, created_at.
    """
    start = page * per_page
    chunk = orders[start : start + per_page]
    buttons = []
    for o in chunk:
        status_emoji = "✅" if o.delivery_status == "completed" else "⏳"
        order_type = (getattr(o, "order_type", None) or "stars").lower()
        buttons.append([
            InlineKeyboardButton(
                text=(
                    f"{status_emoji} #{o.id} — Premium {getattr(o, 'premium_months', 0) or 0}м"
                    if order_type == "premium"
                    else f"{status_emoji} #{o.id} — {o.stars_amount} ⭐"
                ),
                callback_data=f"order:view:{o.id}"
            )
        ])
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="⬅️ Назад", callback_data=f"orders:page:{page - 1}"))
    if start + len(chunk) < len(orders):
        nav.append(InlineKeyboardButton(text="Вперёд ➡️", callback_data=f"orders:page:{page + 1}"))
    if nav:
        buttons.append(nav)
    buttons.append([InlineKeyboardButton(text="◀️ В меню", callback_data="menu:main")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def order_detail_kb(order_id: int) -> InlineKeyboardMarkup:
    """Детали одного заказа — назад к списку заказов."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📋 К списку заказов", callback_data="menu:orders")],
        [InlineKeyboardButton(text="◀️ В меню", callback_data="menu:main")]
    ])
