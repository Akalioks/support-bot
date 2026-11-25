"""All database queries live here."""
from datetime import datetime, time
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

from .config import Config
from .db import Base, ChatMessage, Doc, Relay, Ticket, User

KNOWLEDGE_DIR = Path(__file__).resolve().parent.parent / "knowledge"


class Repo:
    def __init__(self, engine: AsyncEngine, cfg: Config):
        self.engine = engine
        self.cfg = cfg
        self.session = async_sessionmaker(engine, expire_on_commit=False)

    @classmethod
    async def create(cls, cfg: Config) -> "Repo":
        engine = create_async_engine(cfg.database_url)
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        return cls(engine, cfg)

    async def close(self) -> None:
        await self.engine.dispose()

    # ---------- users ----------
    async def ensure_user(self, user_id: int, full_name: str, username: str | None) -> None:
        async with self.session() as s:
            user = await s.get(User, user_id)
            if user is None:
                s.add(User(id=user_id, full_name=full_name, username=username, created_at=self.cfg.now()))
            else:
                user.full_name, user.username = full_name, username
            await s.commit()

    async def get_user(self, user_id: int) -> User | None:
        async with self.session() as s:
            return await s.get(User, user_id)

    async def reset_history(self, user_id: int) -> None:
        async with self.session() as s:
            user = await s.get(User, user_id)
            if user:
                user.history_from = self.cfg.now()
                await s.commit()

    # ---------- messages ----------
    async def add_message(self, user_id: int, role: str, text: str, usage: dict | None = None) -> None:
        async with self.session() as s:
            s.add(ChatMessage(user_id=user_id, role=role, text=text, created_at=self.cfg.now(), **(usage or {})))
            await s.commit()

    async def history(self, user_id: int) -> list[dict]:
        """Recent conversation in chat format: starts with a user turn, ends with a user turn."""
        async with self.session() as s:
            user = await s.get(User, user_id)
            q = select(ChatMessage).where(ChatMessage.user_id == user_id)
            if user and user.history_from:
                q = q.where(ChatMessage.created_at >= user.history_from)
            q = q.order_by(ChatMessage.id.desc()).limit(self.cfg.history_messages)
            rows = list(reversed((await s.scalars(q)).all()))
        msgs = []
        for m in rows:
            if m.role == "user":
                msgs.append({"role": "user", "content": m.text})
            else:
                text = f"[Manager] {m.text}" if m.role == "manager" else m.text
                msgs.append({"role": "assistant", "content": text})
        while msgs and msgs[0]["role"] != "user":
            msgs.pop(0)
        return msgs

    async def ai_answers_since(self, since: datetime, user_id: int | None = None) -> int:
        q = select(func.count(ChatMessage.id)).where(ChatMessage.role == "assistant", ChatMessage.created_at >= since)
        if user_id:
            q = q.where(ChatMessage.user_id == user_id)
        async with self.session() as s:
            return (await s.scalar(q)) or 0

    async def recent_messages(self, user_id: int, limit: int = 6) -> list[ChatMessage]:
        async with self.session() as s:
            q = (select(ChatMessage).where(ChatMessage.user_id == user_id)
                 .order_by(ChatMessage.id.desc()).limit(limit))
            return list(reversed((await s.scalars(q)).all()))

    async def stats(self, since: datetime, user_id: int | None = None) -> dict:
        cols = [func.count(ChatMessage.id), func.sum(ChatMessage.input_tokens), func.sum(ChatMessage.output_tokens),
                func.sum(ChatMessage.cache_read_tokens), func.sum(ChatMessage.cache_write_tokens)]
        q = select(*cols).where(ChatMessage.role == "assistant", ChatMessage.created_at >= since)
        tq = select(func.count(Ticket.id)).where(Ticket.created_at >= since)
        uq = select(func.count(func.distinct(ChatMessage.user_id))).where(ChatMessage.created_at >= since)
        if user_id:  # demo visitor: only their own numbers
            q = q.where(ChatMessage.user_id == user_id)
            uq = uq.where(ChatMessage.user_id == user_id)
            tq = tq.where(Ticket.user_id == user_id)
        async with self.session() as s:
            row = (await s.execute(q)).one()
            tickets = await s.scalar(tq)
            users = await s.scalar(uq)
        return {
            "answers": row[0] or 0, "tickets": tickets or 0, "users": users or 0,
            "tokens": {"input_tokens": row[1] or 0, "output_tokens": row[2] or 0,
                       "cache_read_tokens": row[3] or 0, "cache_write_tokens": row[4] or 0},
        }

    def day_start(self) -> datetime:
        return datetime.combine(self.cfg.now().date(), time.min)

    # ---------- knowledge base ----------
    async def docs(self) -> list[Doc]:
        async with self.session() as s:
            return list((await s.scalars(select(Doc).order_by(Doc.id))).all())

    async def doc(self, doc_id: int) -> Doc | None:
        async with self.session() as s:
            return await s.get(Doc, doc_id)

    async def add_doc(self, title: str, content: str) -> Doc:
        async with self.session() as s:
            d = Doc(title=title[:128], content=content, created_at=self.cfg.now())
            s.add(d)
            await s.commit()
            return d

    async def delete_doc(self, doc_id: int) -> Doc | None:
        async with self.session() as s:
            d = await s.get(Doc, doc_id)
            if d:
                await s.delete(d)
                await s.commit()
            return d

    # ---------- tickets ----------
    async def open_ticket(self, user_id: int) -> Ticket | None:
        async with self.session() as s:
            q = select(Ticket).where(Ticket.user_id == user_id, Ticket.status == "open")
            return (await s.scalars(q)).first()

    async def create_ticket(self, user_id: int) -> tuple[Ticket, bool]:
        """Returns (ticket, created). Doesn't open a second ticket if one is already open."""
        existing = await self.open_ticket(user_id)
        if existing:
            return existing, False
        async with self.session() as s:
            t = Ticket(user_id=user_id, created_at=self.cfg.now())
            s.add(t)
            await s.commit()
            return await s.get(Ticket, t.id, populate_existing=True), True  # type: ignore[return-value]

    async def close_ticket(self, ticket_id: int, only_user_id: int | None = None) -> Ticket | None:
        async with self.session() as s:
            t = await s.get(Ticket, ticket_id)
            if t is None or t.status != "open" or (only_user_id and t.user_id != only_user_id):
                return None
            t.status, t.closed_at = "closed", self.cfg.now()
            await s.commit()
            return t

    async def open_tickets(self, user_id: int | None = None) -> list[Ticket]:
        q = select(Ticket).where(Ticket.status == "open").order_by(Ticket.id)
        if user_id:
            q = q.where(Ticket.user_id == user_id)
        async with self.session() as s:
            return list((await s.scalars(q)).unique().all())

    # ---------- relays ----------
    async def add_relay(self, manager_chat_id: int, manager_message_id: int, user_id: int) -> None:
        async with self.session() as s:
            s.add(Relay(manager_chat_id=manager_chat_id, manager_message_id=manager_message_id, user_id=user_id))
            await s.commit()

    async def relay_target(self, manager_chat_id: int, manager_message_id: int) -> int | None:
        async with self.session() as s:
            q = select(Relay.user_id).where(Relay.manager_chat_id == manager_chat_id,
                                            Relay.manager_message_id == manager_message_id)
            return await s.scalar(q)


async def seed_knowledge(repo: Repo) -> None:
    """On first run, loads every .md / .txt file from the knowledge/ folder."""
    if await repo.docs():
        return
    for path in sorted(KNOWLEDGE_DIR.glob("*")):
        if path.suffix.lower() in {".md", ".txt"}:
            text = path.read_text(encoding="utf-8")
            first = text.strip().splitlines()[0].lstrip("# ").strip() if text.strip() else path.stem
            await repo.add_doc(first or path.stem, text)
