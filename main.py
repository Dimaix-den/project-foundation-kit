"""
Точка входа. Telegram-бот + APScheduler для автопубликации.
"""
import logging
import asyncio
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler, filters,
)
from apscheduler.schedulers.asyncio import AsyncIOScheduler

import config
from bot.handlers import cmd_start, handle_message
from scheduler import check_and_publish

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


def main():
    if not config.TELEGRAM_BOT_TOKEN:
        raise RuntimeError("TELEGRAM_BOT_TOKEN не задан")
    if not config.ANTHROPIC_API_KEY:
        raise RuntimeError("ANTHROPIC_API_KEY не задан")

    app = ApplicationBuilder().token(config.TELEGRAM_BOT_TOKEN).build()

    # Команды
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help",  cmd_start))

    # Все текстовые сообщения → handle_message
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    # Планировщик автопубликации (каждые 5 минут)
    scheduler = AsyncIOScheduler()

    async def publish_job():
        await check_and_publish(app.bot)

    scheduler.add_job(publish_job, "interval", minutes=5, id="auto_publish")
    scheduler.start()
    logger.info("⏰ Планировщик запущен (каждые 5 минут)")

    logger.info("🤖 Бот запускается...")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
