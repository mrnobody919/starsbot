"""
Клавиатуры для сценария покупки Stars: выбор способа оплаты, подтверждение.
"""
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton


def payment_method_kb(freekassa_enabled: bool = True) -> InlineKeyboardMarkup:
    """Выбор способа оплаты: CryptoBot, TON, опционально FreeKassa."""
    buttons = [
        [InlineKeyboardButton(text="⭐ CryptoBot (Stars)", callback_data="pay:cryptobot")],
        [InlineKeyboardButton(text="💎 Toncoin", callback_data="pay:ton")],
    ]
    if freekassa_enabled:
        buttons.append([InlineKeyboardButton(text="💳 FreeKassa", callback_data="pay:freekassa")])
    buttons.append([InlineKeyboardButton(text="◀️ В меню", callback_data="menu:main")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def confirm_order_kb(order_id: int) -> InlineKeyboardMarkup:
    """Подтверждение заказа: кнопка «Оплатить»."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Подтвердить и оплатить", callback_data=f"confirm_order:{order_id}")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="menu:main")],
    ])


def topup_methods_kb() -> InlineKeyboardMarkup:
    """Кнопки выбора способа пополнения баланса."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💳 СБП — оплата рублями через QR-код", callback_data="topup:sbp")],
        [InlineKeyboardButton(text="🔹 TON — оплата через нативный токен сети TON", callback_data="topup:ton")],
        [InlineKeyboardButton(text="💸 USDT TON — оплата через USDT в сети TON", callback_data="topup:usdt_ton")],
        [InlineKeyboardButton(text="💎 Cryptobot — оплата через Cryptobot", callback_data="topup:cryptobot")],
        [InlineKeyboardButton(text="◀️ В меню", callback_data="menu:main")],
    ])


def cryptobot_pay_button_kb(pay_url: str) -> InlineKeyboardMarkup:
    """Кнопка «Перейти к оплате» со ссылкой на инвойс CryptoBot."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💳 Перейти к оплате", url=pay_url)],
        [InlineKeyboardButton(text="◀️ В меню", callback_data="menu:main")],
    ])
