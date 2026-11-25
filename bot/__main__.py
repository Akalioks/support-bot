"""Run with:  python -m bot"""
import asyncio
import logging
import os
import sys

from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import BotCommand

from .ai import SupportAI
from .app import build_dispatcher
from .config import load_config
from .repo import Repo, seed_knowledge


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    cfg = load_config()
    if not cfg.bot_token:
        sys.exit("BOT_TOKEN is empty. Copy .env.example to .env and paste the token from @BotFather.")
    if not os.getenv("GEMINI_API_KEY"):
        sys.exit("GEMINI_API_KEY is empty. Create a key at aistudio.google.com and paste it into .env.")

    repo = await Repo.create(cfg)
    await seed_knowledge(repo)

    bot = Bot(cfg.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    await bot.set_my_commands([
        BotCommand(command="start", description="Start"),
        BotCommand(command="human", description="Talk to a human"),
        BotCommand(command="bot", description="Back to the assistant"),
        BotCommand(command="reset", description="Forget our conversation"),
    ])
    dp = build_dispatcher(cfg, repo, SupportAI(cfg))
    try:
        await dp.start_polling(bot)
    finally:
        await repo.close()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
