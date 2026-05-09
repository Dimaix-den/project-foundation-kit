"""
Точка входа — запускает Telegram-бота.
"""
import logging
import traceback
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
    ContextTypes,
)

import config
from storage.db import init_db
from bot.handlers import (
    cmd_start, cmd_status, cmd_drafts, cmd_brand, cmd_brand_init, cmd_topic_id,
    cmd_pipeline, cmd_sheets_setup, cmd_sheets_test, handle_message, handle_document, handle_callback,
)

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    """Логирует все необработанные ошибки."""
    logger.error("❌ Необработанное исключение:", exc_info=context.error)
    tb = "".join(traceback.format_exception(type(context.error), context.error, context.error.__traceback__))
    logger.error(tb)
    # Если есть апдейт с сообщением — уведомляем пользователя
    if isinstance(update, Update) and update.effective_message:
        try:
            await update.effective_message.reply_text(
                f"⚠️ Произошла ошибка: {type(context.error).__name__}: {context.error}"
            )
        except Exception:
            pass


def main():
    # Проверяем ключи
    if not config.ANTHROPIC_API_KEY:
        raise ValueError("❌ ANTHROPIC_API_KEY не задан в .env")
    if not config.TELEGRAM_BOT_TOKEN:
        raise ValueError("❌ TELEGRAM_BOT_TOKEN не задан в .env")

    logger.info(f"✅ ANTHROPIC_API_KEY: ...{config.ANTHROPIC_API_KEY[-6:]}")
    logger.info(f"✅ TELEGRAM_BOT_TOKEN: {config.TELEGRAM_BOT_TOKEN[:10]}...")
    logger.info(f"✅ MODEL: {config.MODEL}")

    # Инициализируем БД
    init_db()

    # Строим приложение
    app = (
        ApplicationBuilder()
        .token(config.TELEGRAM_BOT_TOKEN)
        .build()
    )

    # Глобальный обработчик ошибок
    app.add_error_handler(error_handler)

    # Команды
    app.add_handler(CommandHandler("start",    cmd_start))
    app.add_handler(CommandHandler("help",     cmd_start))
    app.add_handler(CommandHandler("status",   cmd_status))
    app.add_handler(CommandHandler("drafts",   cmd_drafts))
    app.add_handler(CommandHandler("brand",      cmd_brand))
    app.add_handler(CommandHandler("brand_init", cmd_brand_init))
    app.add_handler(CommandHandler("topic_id", cmd_topic_id))
    app.add_handler(CommandHandler("create",       cmd_pipeline))
    app.add_handler(CommandHandler("sheets_setup", cmd_sheets_setup))
    app.add_handler(CommandHandler("sheets_test",  cmd_sheets_test))

    # Inline кнопки (одобрение / публикация)
    app.add_handler(CallbackQueryHandler(handle_callback))

    # Документы (PDF, DOCX, TXT) — аналитик читает и анализирует
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))

    # Все текстовые сообщения
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    logger.info("🚀 Бот запущен. Ожидаю сообщения...")
    app.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)


if __name__ == "__main__":
    main()
