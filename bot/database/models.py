"""
Модели SQLAlchemy для базы данных.
User, Order, Transaction, Referral, AdminLog.
"""
from datetime import datetime
from typing import Optional

from sqlalchemy import (
    BigInteger,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    Boolean,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """Базовый класс для всех моделей."""
    pass


class User(Base):
    """Пользователь бота."""
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    username: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    balance_stars: Mapped[float] = mapped_column(Float, default=0.0)
    balance_usd: Mapped[float] = mapped_column(Float, default=0.0)  # баланс в USD для покупки Stars
    referral_code: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    referred_by: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    referral_reward_total: Mapped[float] = mapped_column(Float, default=0.0)
    referrals_count: Mapped[int] = mapped_column(Integer, default=0)
    is_blocked: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    # Связи
    orders: Mapped[list["Order"]] = relationship("Order", back_populates="user")
    referrals: Mapped[list["Referral"]] = relationship(
        "Referral",
        foreign_keys="Referral.referrer_id",
        back_populates="referrer"
    )


class Order(Base):
    """Заказ на покупку Stars."""
    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    username: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    stars_amount: Mapped[int] = mapped_column(Integer)
    price: Mapped[float] = mapped_column(Float)
    payment_method: Mapped[str] = mapped_column(String(32))  # cryptobot, ton, freekassa
    payment_status: Mapped[str] = mapped_column(String(32), default="pending")  # pending, paid
    delivery_status: Mapped[str] = mapped_column(String(32), default="waiting")  # waiting, completed, cancelled
    external_payment_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)  # ID платежа от платёжки
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    user: Mapped["User"] = relationship("User", back_populates="orders")
    transactions: Mapped[list["Transaction"]] = relationship("Transaction", back_populates="order")


class Transaction(Base):
    """Транзакция платежа (связь с платёжной системой)."""
    __tablename__ = "transactions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), index=True)
    tx_hash: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    amount: Mapped[float] = mapped_column(Float)
    currency: Mapped[str] = mapped_column(String(16))  # TON, USD, RUB, etc.
    status: Mapped[str] = mapped_column(String(32), default="pending")  # pending, confirmed, failed
    raw_data: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # JSON от webhook
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    order: Mapped["Order"] = relationship("Order", back_populates="transactions")


class Referral(Base):
    """Реферальная связь и начисленный бонус."""
    __tablename__ = "referrals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    referrer_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    referred_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    reward: Mapped[float] = mapped_column(Float, default=0.0)
    order_id: Mapped[Optional[int]] = mapped_column(ForeignKey("orders.id"), nullable=True)  # за какой заказ начислен бонус
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    referrer: Mapped["User"] = relationship("User", foreign_keys=[referrer_id], back_populates="referrals")


class AdminLog(Base):
    """Лог действий администратора."""
    __tablename__ = "admin_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    action: Mapped[str] = mapped_column(String(128))
    admin_id: Mapped[int] = mapped_column(BigInteger, index=True)
    details: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
