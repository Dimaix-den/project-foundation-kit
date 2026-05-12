"""
Telegram-обработчики. Простой пайплайн:
  любое сообщение → ContentAgent → Google Sheets
  "публикуй пост №N" → читаем Sheets → публикуем → обновляем статус
"""
import re
import logging
import asyncio
from telegram import Update
from telegram.ext import ContextTypes
from telegram.constants import ParseMode

import config
from agents.content import ContentAgent
from storage.sheets import (
    add_posts, get_post_by_number, mark_published,
    sheet_url, is_enabled, STATUS_READY,
)

logger = logging.getLogger(__name__)
agent = ContentAgent()


def is_allowed(user_id: int) -> bool:
    if not config.ALLOWED_USER_IDS:
        return True
    return user_id in config.ALLOWED_USER_IDS


async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "*Sanda Marketing Bot* 👋\n\n"
        "Просто напиши задачу — я всё сделаю:\n\n"
        "• _Создай контент-план на неделю_ → пишу план с текстами в таблицу\n"
        "• _Публикуй пост №5_ → публикую в канал\n"
        "• _Создай 3 поста про финансовые привычки_ → генерирую и записываю\n\n"
        f"Таблица: {sheet_url() or 'не настроена'}\n"
        f"Канал: {config.PUBLISH_CHANNEL or 'не настроен'}",
        parse_mode=ParseMode.MARKDOWN,
        disable_web_page_preview=True,
    )


async def _publish_post(update_or_query, ctx, post: dict):
    """Публикует пост в канал и обновляет статус."""
    if not config.PUBLISH_CHANNEL:
        text = "⚠️ PUBLISH\\_CHANNEL не настроен в переменных окружения."
        if hasattr(update_or_query, 'message'):
            await update_or_query.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)
        else:
            await update_or_query.edit_message_text(text, parse_mode=ParseMode.MARKDOWN)
        return

    channel = config.PUBLISH_CHANNEL
    try:
        channel = int(channel)
    except (ValueError, TypeError):
        pass

    post_text = post.get("text", "").strip()
    if not post_text:
        msg = f"⚠️ Пост #{post['id']} пустой — нечего публиковать."
        if hasattr(update_or_query, 'message'):
            await update_or_query.message.reply_text(msg)
        return

    try:
        await ctx.bot.send_message(
            chat_id=channel,
            text=post_text,
            parse_mode=ParseMode.MARKDOWN,
        )
        mark_published(post["_row"])
        reply = f"✅ Пост #{post['id']} опубликован в {config.PUBLISH_CHANNEL}"
        if hasattr(update_or_query, 'message'):
            await update_or_query.message.reply_text(reply)
    except Exception as e:
        err = str(e)
        hint = ""
        if "Chat not found" in err:
            hint = f"\n\nПроверь:\n• Правильный ID канала: `{config.PUBLISH_CHANNEL}`\n• Бот добавлен как администратор канала"
        msg = f"❌ Ошибка публикации: {e}{hint}"
        if hasattr(update_or_query, 'message'):
            await update_or_query.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)


async def handle_message(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Главный обработчик всех сообщений."""
    if not update.message or not update.message.text:
        return

    user_id = update.effective_user.id
    if not is_allowed(user_id):
        return

    text = update.message.text.strip()
    chat_id = update.effective_chat.id
    thread_id = getattr(update.message, "message_thread_id", None)

    logger.info(f"[Handler] '{text[:80]}' от user={user_id}")

    # ── Команда: публикуй пост №N ────────────────────────────────
    match = re.search(r'публикуй\s+пост\s*[№#]?\s*(\d+)', text, re.IGNORECASE)
    if match:
        n = int(match.group(1))
        await ctx.bot.send_chat_action(chat_id=chat_id, action="typing")
        post = get_post_by_number(n)
        if not post:
            await update.message.reply_text(f"⚠️ Пост №{n} не найден в таблице.")
            return
        await _publish_post(update, ctx, post)
        return

    # ── Всё остальное: создаём контент ───────────────────────────
    if not is_enabled():
        await update.message.reply_text(
            "⚠️ Google Sheets не подключён.\n"
            "Добавь `GOOGLE_SERVICE_ACCOUNT_JSON` и `GOOGLE_SHEETS_ID` в переменные окружения.",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    # Прогресс
    await ctx.bot.send_message(
        chat_id=chat_id,
        text="✍️ Генерирую контент...",
        message_thread_id=thread_id,
    )
    await ctx.bot.send_chat_action(chat_id=chat_id, action="typing")

    loop = asyncio.get_event_loop()
    try:
        posts = await loop.run_in_executor(None, lambda: agent.generate(text))
    except Exception as e:
        logger.error(f"[Handler] Ошибка генерации: {e}", exc_info=True)
        await update.message.reply_text(f"❌ Ошибка генерации контента: {e}")
        return

    # Пишем в Sheets
    result = await loop.run_in_executor(None, lambda: add_posts(posts))

    if result.startswith("http"):
        url = result
        await ctx.bot.send_message(
            chat_id=chat_id,
            text=(
                f"✅ Готово! Добавлено *{len(posts)} постов* в таблицу.\n\n"
                f"[Открыть таблицу]({url})\n\n"
                "Проставь статус *«На публикацию»* в колонке Статус — "
                "бот опубликует автоматически в нужное время."
            ),
            parse_mode=ParseMode.MARKDOWN,
            disable_web_page_preview=True,
            message_thread_id=thread_id,
        )
    else:
        await update.message.reply_text(f"⚠️ Контент сгенерирован, но таблица не обновлена: {result}")
