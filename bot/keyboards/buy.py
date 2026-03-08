"""
Клавиатуры для сценария покупки Stars: выбор способа оплаты, подтверждение.
"""
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton


def payment_method_kb() -> InlineKeyboardMarkup:
    """Выбор способа оплаты: CryptoBot, TON, FreeKassa."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⭐ CryptoBot (Stars)", callback_data="pay:cryptobot")],
        [InlineKeyboardButton(text="💎 Toncoin", callback_data="pay:ton")],
        [InlineKeyboardButton(text="💳 FreeKassa", callback_data="pay:freekassa")],
        [InlineKeyboardButton(text="◀️ В меню", callback_data="menu:main")],
    ])


def confirm_order_kb(order_id: int) -> InlineKeyboardMarkup:
    """Подтверждение заказа: кнопка «Оплатить»."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Подтвердить и оплатить", callback_data=f"confirm_order:{order_id}")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="menu:main")],
    ])
