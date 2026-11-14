"""Database connection and tables (SQLite file at backend/data/travel.db).

Switching to Postgres later only means changing DATABASE_URL.
"""
import os
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import (Boolean, DateTime, Float, ForeignKey, Integer, String,
                        create_engine)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
DATA_DIR.mkdir(exist_ok=True)
DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{DATA_DIR / 'travel.db'}")

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False}
                       if DATABASE_URL.startswith("sqlite") else {})
SessionLocal = sessionmaker(bind=engine, autoflush=False)


def now() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class Agency(Base):
    __tablename__ = "agencies"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(4), unique=True)   # "A" / "B"
    name: Mapped[str] = mapped_column(String(100))
    city: Mapped[str] = mapped_column(String(50))


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(50), unique=True)
    password_hash: Mapped[str] = mapped_column(String(200))
    full_name: Mapped[str] = mapped_column(String(100))
    email: Mapped[str] = mapped_column(String(100))
    role: Mapped[str] = mapped_column(String(20))               # "admin" / "subagent"
    agency_id: Mapped[int] = mapped_column(ForeignKey("agencies.id"))


class Session(Base):
    """A login token. Random, opaque, stored server-side."""
    __tablename__ = "sessions"
    token: Mapped[str] = mapped_column(String(100), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class Booking(Base):
    __tablename__ = "bookings"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    agency_id: Mapped[int] = mapped_column(ForeignKey("agencies.id"))
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))   # who booked it
    customer_name: Mapped[str] = mapped_column(String(100))
    customer_email: Mapped[str] = mapped_column(String(100))
    customer_phone: Mapped[str] = mapped_column(String(30))
    item: Mapped[str] = mapped_column(String(200))                 # flight / hotel
    travel_date: Mapped[str] = mapped_column(String(10))
    amount: Mapped[float] = mapped_column(Float)                   # price in INR
    payment_status: Mapped[str] = mapped_column(String(20))        # unpaid / paid
    refund_eligible: Mapped[bool] = mapped_column(Boolean)
    refund_status: Mapped[str] = mapped_column(String(20))         # none / refunded
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class Payment(Base):
    __tablename__ = "payments"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    booking_id: Mapped[int] = mapped_column(ForeignKey("bookings.id"))
    amount: Mapped[float] = mapped_column(Float)
    paid_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class Refund(Base):
    __tablename__ = "refunds"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    booking_id: Mapped[int] = mapped_column(ForeignKey("bookings.id"))
    amount: Mapped[float] = mapped_column(Float)
    refunded_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
