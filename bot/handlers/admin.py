"""Manager side: replying to clients, closing requests, the knowledge base and stats.

Real managers are ADMIN_IDS. In DEMO_MODE anyone can open /admin read-only:
they see the knowledge base and their own numbers, but can't edit anything.
"""
import io
from datetime import timedelta
from html import escape
from pathlib import PurePath

from aiogram import Bot, F, Router
from aiogram.dispatcher.event.bases import SkipHandler
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message
from pypdf import PdfReader

from .. import keyboards as kb
from .. import texts
from ..ai import estimate_cost
from ..config import Config
from ..repo import Repo
from .common import send, show

router = Router(name="admin")
MAX_FILE = 5 * 1024 * 1024
BIG_KB_CHARS = 400_000  # ≈100k tokens — still works, but every question costs more


class AdminSt(StatesGroup):
    add_doc = State()


def can_view(user_id: int, cfg: Config) -> bool:
    return cfg.demo_mode or cfg.is_admin(user_id)


def scope(user_id: int, cfg: Config) -> int | None:
    """None = manager sees everything; a user id = demo visitor sees only their own data."""
    return None if cfg.is_admin(user_id) else user_id


# ---------- manager replies to a client (Telegram "Reply" on a relayed message) ----------
@router.message(F.reply_to_message)
async def manager_reply(message: Message, repo: Repo, cfg: Config, bot: Bot) -> None:
    if not message.from_user or not cfg.is_admin(message.from_user.id) or not message.reply_to_message:
        raise SkipHandler()
    user_id = await repo.relay_target(message.chat.id, message.reply_to_message.message_id)
    if user_id is None:
        raise SkipHandler()
    if message.text:
        delivered = await send(bot, user_id, f"🧑‍💼 <b>Manager:</b> {escape(message.text)}")
        await repo.add_message(user_id, "manager", message.text)
    else:
        try:
            await bot.copy_message(user_id, message.chat.id, message.message_id)
            delivered = True
        except Exception:
            delivered = None
    await message.reply("✓ Delivered" if delivered else "⚠️ Not delivered — the client may have blocked the bot.")


@router.callback_query(kb.TicketCb.filter())
async def close_ticket(cb: CallbackQuery, callback_data: kb.TicketCb, repo: Repo, cfg: Config, bot: Bot) -> None:
    if not cfg.is_admin(cb.from_user.id):
        await cb.answer("Only managers can close requests.", show_alert=True)
        return
    ticket = await repo.close_ticket(callback_data.id)
    if ticket is None:
        await cb.answer("Already closed.", show_alert=True)
        return
    await cb.answer(f"Request #{ticket.id} closed")
    await send(bot, ticket.user_id, texts.TICKET_CLOSED_CLIENT, reply_markup=kb.main_menu())
    if isinstance(cb.message, Message):
        await cb.message.edit_reply_markup(reply_markup=None)
        await cb.message.reply(f"✅ Closed by {escape(cb.from_user.full_name)}")


# ---------- owner panel ----------
async def panel_text(user_id: int, repo: Repo, cfg: Config) -> str:
    who = scope(user_id, cfg)
    docs = await repo.docs()
    chars = sum(len(d.content) for d in docs)
    today = await repo.stats(repo.day_start(), who)
    week = await repo.stats(repo.day_start() - timedelta(days=6), who)
    tickets = await repo.open_tickets(who)

    def money(st: dict) -> str:
        t = st["tokens"]
        cost = estimate_cost(cfg, t)
        if cost is not None:
            return f" · ≤${cost:.2f} AI cost"
        return f" · {(t['input_tokens'] + t['output_tokens']) // 1000:,}k tokens"

    text = (f"🛠 <b>Support panel · {escape(cfg.business_name)}</b>\n\n"
            f"📚 Knowledge base: {len(docs)} document(s), ~{chars // 4:,} tokens\n"
            f"🎫 Open requests: {len(tickets)}\n\n"
            f"<b>Today:</b> {today['answers']} AI answers · {today['users']} people · "
            f"{today['tickets']} hand-offs{money(today)}\n"
            f"<b>7 days:</b> {week['answers']} AI answers · {week['users']} people · "
            f"{week['tickets']} hand-offs{money(week)}\n\n"
            f"<i>Model: {escape(cfg.model)}</i>")
    if who is not None:
        text += "\n\n🧪 <i>Demo mode: read-only, numbers show only your own chats.</i>"
    return text


@router.message(Command("admin"))
async def admin(message: Message, state: FSMContext, repo: Repo, cfg: Config) -> None:
    if not message.from_user or not can_view(message.from_user.id, cfg):
        return
    await state.clear()
    await message.answer(await panel_text(message.from_user.id, repo, cfg),
                         reply_markup=kb.admin_menu(cfg.is_admin(message.from_user.id)))


@router.callback_query(kb.AdmCb.filter(F.action == "menu"))
async def admin_cb(cb: CallbackQuery, state: FSMContext, repo: Repo, cfg: Config) -> None:
    if not can_view(cb.from_user.id, cfg):
        return
    await state.clear()
    await show(cb, await panel_text(cb.from_user.id, repo, cfg), kb.admin_menu(cfg.is_admin(cb.from_user.id)))


@router.callback_query(kb.AdmCb.filter(F.action == "tickets"))
async def tickets(cb: CallbackQuery, repo: Repo, cfg: Config) -> None:
    if not can_view(cb.from_user.id, cfg):
        return
    items = await repo.open_tickets(scope(cb.from_user.id, cfg))
    lines = [f"#{t.id} · {escape(t.user.full_name)} · since {t.created_at:%d.%m %H:%M}" for t in items]
    text = "🎫 <b>Open requests</b>\n\n" + ("\n".join(lines) if lines else "None — the AI handles everything 🙂")
    await show(cb, text, kb.tickets_list(items, cfg.is_admin(cb.from_user.id)))


# ---------- knowledge base ----------
@router.callback_query(kb.AdmCb.filter(F.action == "kb"))
async def kb_list(cb: CallbackQuery, repo: Repo, cfg: Config) -> None:
    if not can_view(cb.from_user.id, cfg):
        return
    docs = await repo.docs()
    text = ("📚 <b>Knowledge base</b>\n\nThe assistant answers only from these documents. "
            "Tap one to view it." if docs else "📚 The knowledge base is empty — the assistant can't answer anything yet.")
    await show(cb, text, kb.docs_list(docs))


@router.callback_query(kb.DocCb.filter())
async def doc_action(cb: CallbackQuery, callback_data: kb.DocCb, repo: Repo, cfg: Config) -> None:
    uid = cb.from_user.id
    if not can_view(uid, cfg):
        return
    doc = await repo.doc(callback_data.id)
    if doc is None:
        await cb.answer("Document not found.", show_alert=True)
        return
    if callback_data.action == "view":
        body = doc.content if len(doc.content) <= 3500 else doc.content[:3500] + "\n…"
        await show(cb, f"📄 <b>{escape(doc.title)}</b> · {len(doc.content):,} characters\n\n{escape(body)}",
                   kb.doc_view(doc.id, cfg.is_admin(uid)))
    elif not cfg.is_admin(uid):
        await cb.answer("Demo mode: editing is disabled.", show_alert=True)
    elif callback_data.action == "del":
        await show(cb, f"Delete <b>{escape(doc.title)}</b>? The assistant will stop using it.",
                   kb.doc_delete_confirm(doc.id))
    else:
        await repo.delete_doc(doc.id)
        await show(cb, f"🗑 Deleted <b>{escape(doc.title)}</b>.", kb.docs_list(await repo.docs()))


@router.callback_query(kb.AdmCb.filter(F.action == "add"))
async def add_doc_start(cb: CallbackQuery, state: FSMContext, cfg: Config) -> None:
    if not cfg.is_admin(cb.from_user.id):
        await cb.answer("Demo mode: editing is disabled.", show_alert=True)
        return
    await state.set_state(AdminSt.add_doc)
    await show(cb, "➕ Send a <b>.txt</b>, <b>.md</b> or <b>.pdf</b> file — or paste the text "
                   "(the first line becomes the title).\n\n/admin — cancel")


def extract_text(name: str, data: bytes) -> str:
    if PurePath(name).suffix.lower() == ".pdf":
        reader = PdfReader(io.BytesIO(data))
        return "\n\n".join((page.extract_text() or "") for page in reader.pages).strip()
    return data.decode("utf-8", errors="replace").strip()


async def _saved(message: Message, repo: Repo, title: str, content: str) -> None:
    if not content:
        await message.answer("⚠️ No text found in it. (Scanned PDFs without a text layer aren't supported.)")
        return
    await repo.add_doc(title, content)
    total = sum(len(d.content) for d in await repo.docs())
    note = ("\n\n⚠️ The knowledge base is getting large — answers will cost more. "
            "Consider removing outdated documents." if total > BIG_KB_CHARS else "")
    await message.answer(f"✅ Added <b>{escape(title)}</b> ({len(content):,} characters). "
                         f"The assistant uses it from the next question.{note}",
                         reply_markup=kb.back())


@router.message(AdminSt.add_doc, F.document)
async def add_doc_file(message: Message, state: FSMContext, repo: Repo, bot: Bot) -> None:
    doc = message.document
    assert doc is not None
    name = doc.file_name or "document.txt"
    if PurePath(name).suffix.lower() not in {".txt", ".md", ".pdf"}:
        await message.answer("Please send a .txt, .md or .pdf file.")
        return
    if (doc.file_size or 0) > MAX_FILE:
        await message.answer("The file is too large (max 5 MB).")
        return
    buf = await bot.download(doc)
    try:
        content = extract_text(name, buf.read() if buf else b"")
    except Exception:
        await message.answer("⚠️ Couldn't read this file. Try saving it as .txt or a text-based PDF.")
        return
    await state.clear()
    await _saved(message, repo, PurePath(name).stem, content)


@router.message(AdminSt.add_doc, F.text & ~F.text.startswith("/"))
async def add_doc_text(message: Message, state: FSMContext, repo: Repo) -> None:
    text = (message.text or "").strip()
    title = text.splitlines()[0].lstrip("# ").strip()[:128] if text else "Note"
    await state.clear()
    await _saved(message, repo, title, text)
