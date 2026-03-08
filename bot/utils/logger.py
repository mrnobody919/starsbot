"""
Централизованное логирование для бота.
Логируются операции, платежи, действия админов.
"""
import logging
import sys
from datetime import datetime
from pathlib import Path


def setup_logger(
    name: str = "stars_bot",
    level: int = logging.INFO,
    log_to_file: bool = True,
    log_dir: str = "logs",
) -> logging.Logger:
    """
    Настраивает и возвращает логгер.
    Пишет в stdout и опционально в файл с ротацией по дням.
    """
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger

    logger.setLevel(level)
    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Консоль
    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(formatter)
    logger.addHandler(console)

    if log_to_file:
        Path(log_dir).mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(
            Path(log_dir) / f"bot_{datetime.utcnow().strftime('%Y-%m-%d')}.log",
            encoding="utf-8",
        )
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

    return logger


def get_logger(name: str | None = None) -> logging.Logger:
    """Возвращает уже настроенный логгер или создаёт новый."""
    return logging.getLogger(name or "stars_bot")
