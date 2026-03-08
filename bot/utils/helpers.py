"""
Вспомогательные функции: генерация кодов, форматирование, валидация.
"""
import hashlib
import secrets
from datetime import datetime
from typing import Optional


def generate_referral_code(telegram_id: int) -> str:
    """Генерирует уникальный реферальный код на основе telegram_id и случайности."""
    raw = f"{telegram_id}_{secrets.token_hex(4)}"
    return hashlib.sha256(raw.encode()).hexdigest()[:12]


def format_stars(amount: int | float) -> str:
    """Форматирует количество Stars для отображения."""
    return f"{int(amount):,} ⭐".replace(",", " ")


def format_price(amount: float, currency: str = "USD") -> str:
    """Форматирует цену с валютой."""
    if currency.upper() == "USD":
        return f"${amount:.2f}"
    return f"{amount:.2f} {currency}"


def format_datetime(dt: datetime) -> str:
    """Форматирует дату/время для сообщений."""
    return dt.strftime("%d.%m.%Y %H:%M") if dt else "—"


def validate_stars_input(text: str, min_stars: int, max_stars: int) -> tuple[bool, Optional[int], str]:
    """
    Проверяет ввод пользователя на количество Stars.
    Возвращает (ok, value, error_message).
    """
    text = (text or "").strip()
    if not text:
        return False, None, "Введите число (например: 250)"
    try:
        value = int(text)
    except ValueError:
        return False, None, f"Введите целое число от {min_stars} до {max_stars}"
    if value < min_stars:
        return False, None, f"Минимум {min_stars} Stars"
    if value > max_stars:
        return False, None, f"Максимум {max_stars} Stars"
    return True, value, ""
