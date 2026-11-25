"""A fake Telegram and a fake AI: feeds updates to the dispatcher and records what the bot sends."""
import itertools
from datetime import datetime

import pytest
from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.base import BaseSession
from aiogram.enums import ParseMode
from aiogram.methods import CopyMessage, EditMessageText, GetFile, SendMessage
from aiogram.types import (CallbackQuery, Chat, Document, File, InlineKeyboardMarkup, Message, MessageId,
                           Update, User as TgUser)

from bot.ai import AIResult
from bot.app import build_dispatcher
from bot.config import load_config
from bot.handlers import admin, client
from bot.repo import Repo, seed_knowledge


class FakeSession(BaseSession):
    def __init__(self):
        super().__init__()
        self.log = []  # (method, result)
        self.ids = itertools.count(1000)
        self.files: dict[str, bytes] = {}

    async def make_request(self, bot, method, timeout=None):
        result = True
        if isinstance(method, SendMessage):
            result = Message(message_id=next(self.ids), date=datetime.now(),
                             chat=Chat(id=method.chat_id, type="private"), text=method.text)
        elif isinstance(method, EditMessageText):
            result = Message(message_id=method.message_id or 0, date=datetime.now(),
                             chat=Chat(id=method.chat_id or 0, type="private"), text=method.text)
        elif isinstance(method, CopyMessage):
            result = MessageId(message_id=next(self.ids))
        elif isinstance(method, GetFile):
            result = File(file_id=method.file_id, file_unique_id=method.file_id, file_path=method.file_id)
        self.log.append((method, result))
        return result

    async def stream_content(self, url, *args, **kwargs):
        name = url.rsplit("/", 1)[-1]
        yield self.files[name]

    async def close(self):
        pass


class FakeAI:
    def __init__(self):
        self.calls = []
        self.next = AIResult("Delivery to Tartu takes 1–2 days.", False)

    async def reply(self, docs, history):
        self.calls.append((docs, history))
        return self.next


class Person:
    """One simulated Telegram user."""

    def __init__(self, env, user_id, name):
        self.env, self.id = env, user_id
        self.user = TgUser(id=user_id, is_bot=False, first_name=name, username=name.lower())

    def _mine(self):
        return [(m, r) for m, r in self.env.session.log
                if getattr(m, "chat_id", None) == self.id and isinstance(m, (SendMessage, EditMessageText))]

    @property
    def last(self):
        return self._mine()[-1][0]

    @property
    def last_text(self) -> str:
        return self.last.text

    def texts(self) -> list[str]:
        return [m.text for m, _ in self._mine()]

    def find(self, part: str):
        """The last message containing `part`, and the id it got in the chat."""
        for m, r in reversed(self._mine()):
            if part in m.text:
                return m, (r.message_id if isinstance(r, Message) else None)
        raise AssertionError(f"No message containing {part!r}")

    def buttons(self) -> list[str]:
        for m, _ in reversed(self._mine()):
            if isinstance(m.reply_markup, InlineKeyboardMarkup):
                return [b.text for row in m.reply_markup.inline_keyboard for b in row]
        return []

    async def say(self, text=None, reply_to: int | None = None, document: tuple[str, bytes] | None = None):
        env = self.env
        doc = None
        if document:
            name, data = document
            env.session.files[name] = data
            doc = Document(file_id=name, file_unique_id=name, file_name=name, file_size=len(data))
        reply = Message(message_id=reply_to, date=datetime.now(), chat=Chat(id=self.id, type="private")) if reply_to else None
        msg = Message(message_id=next(env.ids), date=datetime.now(), chat=Chat(id=self.id, type="private"),
                      from_user=self.user, text=text, reply_to_message=reply, document=doc)
        await env.dp.feed_update(env.bot, Update(update_id=next(env.ids), message=msg))

    async def press(self, label_part: str):
        for m, r in reversed(self._mine()):
            if isinstance(m.reply_markup, InlineKeyboardMarkup):
                for row in m.reply_markup.inline_keyboard:
                    for b in row:
                        if label_part in b.text:
                            mid = r.message_id if isinstance(r, Message) else 1
                            msg = Message(message_id=mid, date=datetime.now(), chat=Chat(id=self.id, type="private"), text=m.text)
                            cq = CallbackQuery(id=str(next(self.env.ids)), from_user=self.user, chat_instance="ci",
                                               data=b.callback_data, message=msg)
                            await self.env.dp.feed_update(self.env.bot, Update(update_id=next(self.env.ids), callback_query=cq))
                            return
        raise AssertionError(f"No button containing {label_part!r}; have: {self.buttons()}")


class Env:
    def __init__(self, cfg, repo):
        self.cfg, self.repo = cfg, repo
        self.session, self.ai = FakeSession(), FakeAI()
        self.ids = itertools.count(1)
        self.bot = Bot("42:TEST", session=self.session, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
        for r in (admin.router, client.router):
            r._parent_router = None  # module-level routers attach once; each test builds a fresh dispatcher
        self.dp = build_dispatcher(cfg, repo, self.ai)  # type: ignore[arg-type]

    def person(self, user_id, name):
        return Person(self, user_id, name)


@pytest.fixture
async def make_env(tmp_path):
    repos = []

    async def factory(**overrides):
        settings = {"database_url": f"sqlite+aiosqlite:///{tmp_path}/t{len(repos)}.db",
                    "admin_ids": frozenset({99}), "demo_mode": True, **overrides}
        cfg = load_config(**settings)
        repo = await Repo.create(cfg)
        await seed_knowledge(repo)
        repos.append(repo)
        return Env(cfg, repo)

    yield factory
    for r in repos:
        await r.close()
