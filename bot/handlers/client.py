"""Customer side: questions to the AI, hand-off to a human manager."""
import asyncio
from collections import defaultdict
from datetime import timedelta
from html import escape

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message, User as TgUser
from aiogram.utils.chat_action import ChatActionSender

from .. import keyboards as kb
from .. import texts
from ..ai import SupportAI
from ..config import Config
from ..repo import Repo
from .common import send

router = Router(name="client")
_locks: dict[int, asyncio.Lock] = defaultdict(asyncio.Lock)  # one AI answer at a time per user
MAX_QUESTION = 4000


@router.message(CommandStart())
@router.message(Command("help"))
async def start(message: Message, state: FSMContext, cfg: Config) -> None:
    await state.clear()
    u = message.from_user
    await message.answer(texts.welcome(u.first_name if u else "there", cfg.business_name, cfg.demo_mode),
                         reply_markup=kb.main_menu())


@router.message(Command("reset"))
async def reset(message: Message, repo: Repo) -> None:
    if message.from_user:
        await repo.reset_history(message.from_user.id)
        await message.answer(texts.RESET_DONE)


@router.message(Command("bot"))
async def back_to_bot(message: Message, repo: Repo, bot: Bot, cfg: Config) -> None:
    """Client ends the conversation with a manager themselves."""
    if not message.from_user:
        return
    ticket = await repo.open_ticket(message.from_user.id)
    if ticket and await repo.close_ticket(ticket.id):
        for admin_id in cfg.admin_ids:
            await send(bot, admin_id, f"ℹ️ Request #{ticket.id} was closed by the client.")
    await message.answer(texts.TICKET_CLOSED_CLIENT, reply_markup=kb.main_menu())


# ---------- hand-off to a human ----------
async def handoff(user: TgUser, answer, repo: Repo, cfg: Config, bot: Bot) -> None:
    if not cfg.admin_ids:
        await answer(texts.NO_MANAGERS)
        return
    ticket, created = await repo.create_ticket(user.id)
    if not created:
        await answer(texts.HANDOFF_ALREADY)
        return
    icons = {"user": "👤", "assistant": "🤖", "manager": "🧑‍💼"}
    lines = [f"{icons.get(m.role, '•')} {escape(m.text[:300])}" for m in await repo.recent_messages(user.id)]
    note = texts.manager_new_ticket(ticket.id, user.full_name, user.username, "\n".join(lines) or "—")
    for admin_id in cfg.admin_ids:
        sent = await send(bot, admin_id, note, reply_markup=kb.close_ticket(ticket.id))
        if sent:
            await repo.add_relay(admin_id, sent.message_id, user.id)
    await answer(texts.handoff_client(cfg.support_hours))


@router.message(F.text == texts.BTN_HUMAN)
@router.message(Command("human"))
async def human_button(message: Message, repo: Repo, cfg: Config, bot: Bot) -> None:
    if message.from_user:
        await handoff(message.from_user, message.answer, repo, cfg, bot)


@router.callback_query(kb.HandoffCb.filter())
async def human_inline(cb: CallbackQuery, repo: Repo, cfg: Config, bot: Bot) -> None:
    await cb.answer()
    await handoff(cb.from_user, lambda text: bot.send_message(cb.from_user.id, text), repo, cfg, bot)


async def relay_to_managers(message: Message, repo: Repo, cfg: Config, bot: Bot) -> None:
    """While a request is open, everything the client writes goes to the managers."""
    user = message.from_user
    assert user is not None
    if message.text:
        await repo.add_message(user.id, "user", message.text)
        for admin_id in cfg.admin_ids:
            sent = await send(bot, admin_id, texts.manager_client_message(user.full_name, message.text))
            if sent:
                await repo.add_relay(admin_id, sent.message_id, user.id)
        return
    for admin_id in cfg.admin_ids:  # photo, voice, file…
        header = await send(bot, admin_id, f"💬 <b>{escape(user.full_name)}</b> sent:")
        ids = [header.message_id] if header else []
        try:
            ids.append((await bot.copy_message(admin_id, message.chat.id, message.message_id)).message_id)
        except TelegramAPIError:
            pass
        for msg_id in ids:
            await repo.add_relay(admin_id, msg_id, user.id)


# ---------- questions to the AI ----------
@router.message(F.text & ~F.text.startswith("/"))
async def question(message: Message, repo: Repo, cfg: Config, bot: Bot, ai: SupportAI) -> None:
    user = message.from_user
    if not user or not message.text:
        return
    if await repo.open_ticket(user.id):
        await relay_to_managers(message, repo, cfg, bot)
        return

    now = cfg.now()
    if await repo.ai_answers_since(repo.day_start()) >= cfg.daily_ai_limit:
        await message.answer(texts.DAILY_LIMIT, reply_markup=kb.handoff_offer())
        return
    if await repo.ai_answers_since(now - timedelta(hours=1), user.id) >= cfg.user_hourly_limit:
        await message.answer(texts.USER_LIMIT, reply_markup=kb.handoff_offer())
        return

    async with _locks[user.id]:
        await repo.add_message(user.id, "user", message.text[:MAX_QUESTION])
        history = await repo.history(user.id)
        async with ChatActionSender.typing(bot=bot, chat_id=message.chat.id):
            result = await ai.reply(await repo.docs(), history)
        if result.ok:
            await repo.add_message(user.id, "assistant", result.answer, result.usage)
    markup = kb.handoff_offer() if result.needs_human and cfg.admin_ids else None
    await send(bot, message.chat.id, result.answer, parse_mode=None, reply_markup=markup)


@router.message()
async def other(message: Message, repo: Repo, cfg: Config, bot: Bot) -> None:
    """Photos, voice messages, stickers…"""
    if message.from_user and await repo.open_ticket(message.from_user.id):
        await relay_to_managers(message, repo, cfg, bot)
    elif not (message.text or "").startswith("/"):
        await message.answer(texts.NON_TEXT)
