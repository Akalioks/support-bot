"""Database tables. SQLite by default, PostgreSQL works by changing DATABASE_URL."""
from datetime import datetime

from sqlalchemy import BigInteger, ForeignKey, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)  # Telegram user id
    full_name: Mapped[str] = mapped_column(String(128))
    username: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime]
    history_from: Mapped[datetime | None]  # /reset: the AI ignores messages before this moment


class ChatMessage(Base):
    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    role: Mapped[str] = mapped_column(String(16))  # user | assistant | manager
    text: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(index=True)
    # token usage of the AI answer (assistant rows only)
    input_tokens: Mapped[int] = mapped_column(default=0)
    output_tokens: Mapped[int] = mapped_column(default=0)
    cache_read_tokens: Mapped[int] = mapped_column(default=0)
    cache_write_tokens: Mapped[int] = mapped_column(default=0)


class Doc(Base):
    """A knowledge-base document: price list, FAQ, delivery rules…"""
    __tablename__ = "docs"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(128))
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime]


class Ticket(Base):
    """A conversation handed over to a human manager."""
    __tablename__ = "tickets"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    status: Mapped[str] = mapped_column(String(16), default="open")  # open | closed
    created_at: Mapped[datetime]
    closed_at: Mapped[datetime | None]

    user: Mapped[User] = relationship(lazy="joined")


class Relay(Base):
    """Which client a message in a manager's chat belongs to — so a Telegram 'Reply' reaches the right person."""
    __tablename__ = "relays"

    id: Mapped[int] = mapped_column(primary_key=True)
    manager_chat_id: Mapped[int] = mapped_column(BigInteger, index=True)
    manager_message_id: Mapped[int] = mapped_column(BigInteger, index=True)
    user_id: Mapped[int] = mapped_column(BigInteger)
