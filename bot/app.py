"""Wires routers, middleware and shared objects into a Dispatcher."""
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import TelegramObject

from .ai import SupportAI
from .config import Config
from .handlers import admin, client
from .repo import Repo


class RegisterUser(BaseMiddleware):
    """Makes sure every person who talks to the bot has a row in the users table."""

    def __init__(self) -> None:
        self.known: set[int] = set()

    async def __call__(self, handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
                       event: TelegramObject, data: dict[str, Any]) -> Any:
        u = data.get("event_from_user")
        if u and u.id not in self.known:
            await data["repo"].ensure_user(u.id, u.full_name, u.username)
            self.known.add(u.id)
        return await handler(event, data)


def build_dispatcher(cfg: Config, repo: Repo, ai: SupportAI) -> Dispatcher:
    dp = Dispatcher(storage=MemoryStorage())
    dp["cfg"], dp["repo"], dp["ai"] = cfg, repo, ai
    mw = RegisterUser()
    dp.message.outer_middleware(mw)
    dp.callback_query.outer_middleware(mw)
    # order matters: manager replies and the panel first, then the catch-all client chat
    dp.include_routers(admin.router, client.router)
    return dp
