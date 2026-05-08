"""
Точка входа — запускает Telegram-бота.
"""
import logging
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
)

import config
from storage.db import init_db
from bot.handlers import (
    cmd_start, cmd_status, cmd_drafts, cmd_brand, cmd_topic_id,
    handle_message, handle_callback,
)

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


def main():
    # Проверяем ключи
    if not config.ANTHROPIC_API_KEY:
        raise ValueError("❌ ANTHROPIC_API_KEY не задан в .env")
    if not config.TELEGRAM_BOT_TOKEN:
        raise ValueError("❌ TELEGRAM_BOT_TOKEN не задан в .env")

    # Инициализируем БД
    init_db()

    # Строим приложение
    app = (
        ApplicationBuilder()
        .token(config.TELEGRAM_BOT_TOKEN)
        .build()
    )

    # Команды
    app.add_handler(CommandHandler("start",    cmd_start))
    app.add_handler(CommandHandler("help",     cmd_start))
    app.add_handler(CommandHandler("status",   cmd_status))
    app.add_handler(CommandHandler("drafts",   cmd_drafts))
    app.add_handler(CommandHandler("brand",    cmd_brand))
    app.add_handler(CommandHandler("topic_id", cmd_topic_id))

    # Inline кнопки (одобрение / публикация)
    app.add_handler(CallbackQueryHandler(handle_callback))

    # Все текстовые сообщения
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    logger.info("🚀 Бот запущен. Ожидаю сообщения...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
