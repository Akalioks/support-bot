"""Settings are read from the .env file (see .env.example)."""
import os
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from dotenv import load_dotenv


def _ids(raw: str) -> frozenset[int]:
    return frozenset(int(x) for x in raw.replace(" ", "").split(",") if x)


def _price(raw: str) -> float | None:
    return float(raw) if raw.strip() else None


def _bool(raw: str) -> bool:
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Config:
    bot_token: str
    admin_ids: frozenset[int]   # managers: receive hand-offs, edit the knowledge base
    demo_mode: bool
    tz: ZoneInfo
    database_url: str
    business_name: str
    support_hours: str
    model: str
    fallback_models: tuple[str, ...]  # tried in order when the main model is overloaded
    thinking: str | None              # minimal | low | medium | high; None = the model's default
    price_input: float | None   # $ per 1M tokens, only for the cost estimate in /admin
    price_output: float | None
    history_messages: int       # how many recent messages the AI sees
    user_hourly_limit: int      # AI answers per user per hour
    daily_ai_limit: int         # AI answers for the whole bot per day (protects your API bill)

    def now(self) -> datetime:
        return datetime.now(self.tz).replace(tzinfo=None)

    def is_admin(self, user_id: int) -> bool:
        return user_id in self.admin_ids


def load_config(**overrides) -> Config:
    load_dotenv()
    env = os.getenv
    values: dict[str, Any] = dict(
        bot_token=env("BOT_TOKEN", ""),
        admin_ids=_ids(env("ADMIN_IDS", "")),
        demo_mode=_bool(env("DEMO_MODE", "true")),
        tz=ZoneInfo(env("TIMEZONE", "Europe/Tallinn")),
        database_url=env("DATABASE_URL", "sqlite+aiosqlite:///support.db"),
        business_name=env("BUSINESS_NAME", "Nordic Home"),
        support_hours=env("SUPPORT_HOURS", "Mon–Fri 9:00–18:00"),
        model=env("AI_MODEL", "gemini-3.5-flash"),
        fallback_models=tuple(m.strip() for m in env("AI_FALLBACK_MODELS", "gemini-3.5-flash-lite").split(",")
                              if m.strip()),
        thinking=env("AI_THINKING", "minimal").strip().lower() or None,
        price_input=_price(env("AI_PRICE_INPUT", "")),
        price_output=_price(env("AI_PRICE_OUTPUT", "")),
        history_messages=int(env("HISTORY_MESSAGES", "12")),
        user_hourly_limit=int(env("USER_HOURLY_LIMIT", "30")),
        daily_ai_limit=int(env("DAILY_AI_LIMIT", "500")),
    )
    values.update(overrides)
    return Config(**values)
