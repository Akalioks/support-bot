"""Buttons and the data they carry."""
from aiogram.filters.callback_data import CallbackData
from aiogram.types import InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from .db import Doc, Ticket
from .texts import BTN_HUMAN, HANDOFF_OFFER


class HandoffCb(CallbackData, prefix="ho"):
    pass


class AdmCb(CallbackData, prefix="adm"):
    action: str  # menu | kb | tickets | add


class DocCb(CallbackData, prefix="doc"):
    id: int
    action: str  # view | del | delok


class TicketCb(CallbackData, prefix="tk"):
    id: int


def main_menu() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text=BTN_HUMAN)]], resize_keyboard=True)


def handoff_offer() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text=HANDOFF_OFFER, callback_data=HandoffCb())
    return kb.as_markup()


def close_ticket(ticket_id: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text=f"✅ Close #{ticket_id}", callback_data=TicketCb(id=ticket_id))
    return kb.as_markup()


def admin_menu(can_edit: bool) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="📚 Knowledge base", callback_data=AdmCb(action="kb"))
    kb.button(text="🎫 Open requests", callback_data=AdmCb(action="tickets"))
    if can_edit:
        kb.button(text="➕ Add document", callback_data=AdmCb(action="add"))
    kb.adjust(2, 1)
    return kb.as_markup()


def back() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="⬅️ Back", callback_data=AdmCb(action="menu"))
    return kb.as_markup()


def docs_list(docs: list[Doc]) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for d in docs:
        kb.button(text=f"📄 {d.title[:40]}", callback_data=DocCb(id=d.id, action="view"))
    kb.button(text="⬅️ Back", callback_data=AdmCb(action="menu"))
    kb.adjust(1)
    return kb.as_markup()


def doc_view(doc_id: int, can_edit: bool) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    if can_edit:
        kb.button(text="🗑 Delete", callback_data=DocCb(id=doc_id, action="del"))
    kb.button(text="⬅️ Back", callback_data=AdmCb(action="kb"))
    kb.adjust(1)
    return kb.as_markup()


def doc_delete_confirm(doc_id: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="Yes, delete", callback_data=DocCb(id=doc_id, action="delok"))
    kb.button(text="Cancel", callback_data=DocCb(id=doc_id, action="view"))
    kb.adjust(2)
    return kb.as_markup()


def tickets_list(tickets: list[Ticket], can_close: bool) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    if can_close:
        for t in tickets:
            kb.button(text=f"✅ Close #{t.id} · {t.user.full_name[:20]}", callback_data=TicketCb(id=t.id))
    kb.button(text="⬅️ Back", callback_data=AdmCb(action="menu"))
    kb.adjust(1)
    return kb.as_markup()
