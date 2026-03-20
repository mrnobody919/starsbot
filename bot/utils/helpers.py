"""
Вспомогательные функции: генерация кодов, форматирование, валидация.
"""
import hashlib
import secrets
from datetime import datetime
from typing import Optional

from aiogram.exceptions import TelegramBadRequest


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


async def safe_callback_answer(callback, text: Optional[str] = None, show_alert: bool = False) -> None:
    """Вызывает callback.answer(), игнорируя ошибку «query is too old» (таймаут Telegram)."""
    try:
        await callback.answer(text=text or None, show_alert=show_alert)
    except TelegramBadRequest:
        pass  # query is too old / response timeout — ожидаемо при долгих операциях


async def edit_or_send_text(callback, text: str, reply_markup, parse_mode: Optional[str] = "HTML") -> None:
    """
    Редактирует сообщение или удаляет и отправляет новое, если текущее — с фото (баннер меню).
    У сообщений с фото в Telegram нет «текста», только caption — edit_text падает с «no text to edit».
    """
    kwargs = {"reply_markup": reply_markup}
    if parse_mode is not None:
        kwargs["parse_mode"] = parse_mode
    msg = getattr(callback, "message", None)
    if msg is None:
        # На всякий случай: если callback без message (редко), отправим в чат пользователя.
        await callback.bot.send_message(chat_id=callback.from_user.id, text=text, **kwargs)
        return

    # В некоторых случаях в aiogram для устаревших/удалённых сообщений callback.message может быть
    # объектом InaccessibleMessage, у которого нет поля photo/edit_text и т.п.
    try:
        has_photo = bool(getattr(msg, "photo", None))
        if has_photo:
            await msg.delete()
            await msg.answer(text, **kwargs)
        else:
            await msg.edit_text(text, **kwargs)
    except (TelegramBadRequest, AttributeError):
        # fallback: просто отправим новое сообщение пользователю вместо редактирования.
        await callback.bot.send_message(chat_id=callback.from_user.id, text=text, **kwargs)
