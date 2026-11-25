"""Small helpers shared by handlers."""
import logging

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message

log = logging.getLogger(__name__)
TG_LIMIT = 4000  # Telegram allows 4096 characters per message


async def show(target: Message | CallbackQuery, text: str, markup: InlineKeyboardMarkup | None = None) -> None:
    """Answers a message, or edits the message whose button was pressed."""
    if isinstance(target, CallbackQuery):
        await target.answer()
        if isinstance(target.message, Message):
            try:
                await target.message.edit_text(text, reply_markup=markup)
                return
            except TelegramBadRequest:
                pass
        await target.bot.send_message(target.from_user.id, text, reply_markup=markup)  # type: ignore[union-attr]
        return
    await target.answer(text, reply_markup=markup)


async def send(bot: Bot, chat_id: int, text: str, **kwargs) -> Message | None:
    """Sends a message, ignoring users who blocked the bot. Long texts are split."""
    try:
        sent = None
        for i in range(0, max(len(text), 1), TG_LIMIT):
            last = i + TG_LIMIT >= len(text)
            sent = await bot.send_message(chat_id, text[i:i + TG_LIMIT], **(kwargs if last else
                                          {k: v for k, v in kwargs.items() if k != "reply_markup"}))
        return sent
    except TelegramAPIError as e:
        log.warning("Could not message %s: %s", chat_id, e)
        return None
