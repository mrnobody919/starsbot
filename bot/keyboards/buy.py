"""
Клавиатуры для сценария покупки Stars: выбор получателя, способа оплаты, пополнение.
"""
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton


def recipient_choice_kb() -> InlineKeyboardMarkup:
    """Выбор: купить себе / подарить другу / назад."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🫵 Купить себе", callback_data="buy:recipient_self"),
            InlineKeyboardButton(text="👥Подарить другу", callback_data="buy:recipient_gift"),
        ],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="menu:main")],
    ])


def premium_recipient_choice_kb() -> InlineKeyboardMarkup:
    """Выбор: купить Premium себе / подарить другу / назад."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🫵 Купить себе", callback_data="premium:recipient_self"),
            InlineKeyboardButton(text="👥Подарить другу", callback_data="premium:recipient_gift"),
        ],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="menu:main")],
    ])


def premium_back_to_recipient_kb() -> InlineKeyboardMarkup:
    """Назад к выбору получателя Premium."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ Назад", callback_data="premium:back_recipient")],
    ])


def back_to_recipient_kb() -> InlineKeyboardMarkup:
    """Назад к выбору получателя (из ввода количества)."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ Назад", callback_data="buy:back_recipient")],
    ])


def premium_duration_kb(prices: dict[int, float]) -> InlineKeyboardMarkup:
    """Кнопки выбора срока Premium."""
    def _btn(months: int) -> InlineKeyboardButton:
        price = prices.get(months)
        price_txt = f"${price:.2f}" if price is not None else "—"
        return InlineKeyboardButton(text=f"{months} месяцев ({price_txt})", callback_data=f"premium:duration:{months}")

    return InlineKeyboardMarkup(inline_keyboard=[
        [_btn(3)],
        [_btn(6)],
        [_btn(12)],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="premium:back_recipient")],
    ])


def payment_method_kb(show_balance: bool = False) -> InlineKeyboardMarkup:
    """Выбор способа оплаты. Если show_balance — добавляется кнопка «Оплатить с баланса»."""
    rows = []
    if show_balance:
        rows.append([InlineKeyboardButton(text="💰 Оплатить с баланса", callback_data="pay:balance")])
    rows += [
        [InlineKeyboardButton(text="⭐ CryptoBot (Stars)", callback_data="pay:cryptobot")],
        [InlineKeyboardButton(text="💎 Toncoin", callback_data="pay:ton")],
        [InlineKeyboardButton(text="💳 СБП (рубли)", callback_data="pay:freekassa")],
        [InlineKeyboardButton(text="◀️ В меню", callback_data="menu:main")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def confirm_order_kb(order_id: int) -> InlineKeyboardMarkup:
    """Подтверждение заказа: кнопка «Оплатить»."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Подтвердить и оплатить", callback_data=f"confirm_order:{order_id}")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="menu:main")],
    ])


def topup_methods_kb() -> InlineKeyboardMarkup:
    """Кнопки выбора способа пополнения: СБП 4%, TON без комиссии, Cryptobot 3%."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💳 СБП Рубли | 4%", callback_data="topup:sbp")],
        [InlineKeyboardButton(text="🔹 TON | Без комиссии", callback_data="topup:ton")],
        [InlineKeyboardButton(text="💎 Cryptobot | 3%", callback_data="topup:cryptobot")],
        [InlineKeyboardButton(text="◀️ В меню", callback_data="menu:main")],
    ])


def cryptobot_pay_button_kb(pay_url: str) -> InlineKeyboardMarkup:
    """Кнопка «Перейти к оплате» со ссылкой на инвойс CryptoBot."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💳 Перейти к оплате", url=pay_url)],
        [InlineKeyboardButton(text="◀️ В меню", callback_data="menu:main")],
    ])


def sbp_pay_button_kb(pay_url: str) -> InlineKeyboardMarkup:
    """Кнопка «Оплатить счёт» для СБП."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💷 Оплатить счёт", url=pay_url)],
        [InlineKeyboardButton(text="◀️ В меню", callback_data="menu:main")],
    ])


def ton_pay_button_kb(pay_url: str) -> InlineKeyboardMarkup:
    """Кнопка «Оплатить счёт» для TON."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💷 Оплатить счёт", url=pay_url)],
        [InlineKeyboardButton(text="◀️ В меню", callback_data="menu:main")],
    ])
