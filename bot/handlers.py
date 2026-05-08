"""
Обработчики Telegram-сообщений.
"""
import re
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from telegram.constants import ParseMode

import config
from agents.orchestrator import Orchestrator
from storage.db import (
    add_to_history, get_history,
    get_draft, update_draft_status,
    save_published, get_drafts,
    set_brand, get_all_brand,
)

orchestrator = Orchestrator()

# Привязка топиков к агентам (заполняется из config)
def setup_topic_routing():
    topic_map = {}
    if config.TOPIC_ANALYTICS: topic_map[config.TOPIC_ANALYTICS] = "analyst"
    if config.TOPIC_DRAFTS:    topic_map[config.TOPIC_DRAFTS]    = "copywriter"
    if config.TOPIC_VISUALS:   topic_map[config.TOPIC_VISUALS]   = "designer"
    if config.TOPIC_REVIEW:    topic_map[config.TOPIC_REVIEW]    = "publisher"
    orchestrator.set_topic_defaults(topic_map)

setup_topic_routing()


def is_allowed(user_id: int) -> bool:
    if not config.ALLOWED_USER_IDS:
        return True
    return user_id in config.ALLOWED_USER_IDS


async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Приветствие и инструкция."""
    text = (
        "👋 *Привет! Я — твоя ИИ контент-команда.*\n\n"
        "Просто пиши мне что нужно сделать, я сам разберусь кому передать задачу:\n\n"
        "🔍 *Аналитик* — тренды, конкуренты, рынок\n"
        "📋 *Стратег* — контент-план, рубрики, идеи\n"
        "✍️ *Копирайтер* — посты, статьи, тексты\n"
        "🎨 *Дизайнер* — промпты для визуалов\n"
        "📅 *Менеджер* — статус, расписание, публикация\n\n"
        "Или вызывай агента напрямую:\n"
        "`@аналитик`, `@стратег`, `@копирайтер`, `@дизайнер`, `@менеджер`\n\n"
        "Команды:\n"
        "/status — статус всех материалов\n"
        "/drafts — список черновиков\n"
        "/brand — настройки бренда\n"
        "/help — эта справка"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)


async def cmd_status(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    publisher = orchestrator.get_agent("publisher")
    report = publisher.get_status_report()
    await update.message.reply_text(report, parse_mode=ParseMode.MARKDOWN)


async def cmd_drafts(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    drafts = get_drafts("draft") + get_drafts("review") + get_drafts("approved")
    if not drafts:
        await update.message.reply_text("Черновиков пока нет.")
        return

    lines = ["📝 *Черновики:*\n"]
    for d in drafts:
        status_emoji = {"draft": "✏️", "review": "👀", "approved": "✅"}.get(d["status"], "•")
        lines.append(f"{status_emoji} [#{d['id']}] {d['title'][:60] or 'без названия'}")

    lines.append("\nДля просмотра: `показать #ID`")
    lines.append("Для одобрения: `одобрить #ID`")
    lines.append("Для публикации: `опубликовать #ID`")
    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN)


async def cmd_brand(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    brand = get_all_brand()
    if not brand:
        text = (
            "⚙️ *Настройки бренда пока не заданы.*\n\n"
            "Используются значения по умолчанию из config.\n\n"
            "Чтобы настроить, напиши:\n"
            "`бренд ниша: SaaS для HR-команд`\n"
            "`бренд тон: дружелюбный эксперт`\n"
            "`бренд аудитория: HR-директора и рекрутеры`"
        )
    else:
        lines = ["⚙️ *Настройки бренда:*\n"]
        for k, v in brand.items():
            lines.append(f"*{k}:* {v}")
        text = "\n".join(lines)
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)


async def cmd_topic_id(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Показывает ID текущего топика — нужно для настройки config."""
    thread_id = getattr(update.message, "message_thread_id", None)
    chat_id = update.effective_chat.id
    await update.message.reply_text(
        f"💬 Chat ID: `{chat_id}`\n📌 Topic ID: `{thread_id or 'нет (общий чат)'}`",
        parse_mode=ParseMode.MARKDOWN,
    )


async def handle_message(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Главный обработчик всех входящих сообщений."""
    if not update.message or not update.message.text:
        return

    user_id  = update.effective_user.id
    message  = update.message.text.strip()
    topic_id = getattr(update.message, "message_thread_id", 0) or 0

    if not is_allowed(user_id):
        return

    # ─── Команда: показать черновик ──────────────────────────────
    if re.match(r"^(показать|посмотреть)\s*#?(\d+)", message, re.IGNORECASE):
        m = re.search(r"(\d+)", message)
        if m:
            draft = get_draft(int(m.group(1)))
            if draft:
                await update.message.reply_text(
                    f"*Черновик #{draft['id']}*\n\n{draft['body']}",
                    parse_mode=ParseMode.MARKDOWN,
                )
            else:
                await update.message.reply_text("Черновик не найден.")
        return

    # ─── Команда: одобрить черновик ──────────────────────────────
    if re.match(r"^одобрить\s*#?(\d+)", message, re.IGNORECASE):
        m = re.search(r"(\d+)", message)
        if m:
            draft_id = int(m.group(1))
            update_draft_status(draft_id, "approved")
            draft = get_draft(draft_id)

            keyboard = InlineKeyboardMarkup([[
                InlineKeyboardButton("📢 Опубликовать сейчас", callback_data=f"publish:{draft_id}"),
                InlineKeyboardButton("❌ Отмена", callback_data=f"cancel:{draft_id}"),
            ]])
            await update.message.reply_text(
                f"✅ Черновик #{draft_id} одобрен!\n\nОпубликовать в канал?",
                reply_markup=keyboard,
            )
        return

    # ─── Команда: опубликовать черновик ──────────────────────────
    if re.match(r"^опубликовать\s*#?(\d+)", message, re.IGNORECASE):
        m = re.search(r"(\d+)", message)
        if m:
            await _publish_draft(update, ctx, int(m.group(1)))
        return

    # ─── Команда: настройка бренда ───────────────────────────────
    brand_match = re.match(r"^бренд\s+(\w+):\s*(.+)", message, re.IGNORECASE)
    if brand_match:
        key, value = brand_match.group(1).lower(), brand_match.group(2).strip()
        set_brand(key, value)
        await update.message.reply_text(f"✅ Бренд обновлён: *{key}* = {value}", parse_mode=ParseMode.MARKDOWN)
        return

    # ─── Явный вызов агента через @имя ───────────────────────────
    force_agent = None
    agent_aliases = {
        "@аналитик": "analyst", "@analyst": "analyst",
        "@стратег": "strategist", "@strategist": "strategist",
        "@копирайтер": "copywriter", "@copywriter": "copywriter",
        "@дизайнер": "designer", "@designer": "designer",
        "@менеджер": "publisher", "@publisher": "publisher",
    }
    for alias, agent_name in agent_aliases.items():
        if message.lower().startswith(alias):
            force_agent = agent_name
            message = message[len(alias):].strip()
            break

    if not message:
        await update.message.reply_text("Напиши задачу после имени агента.")
        return

    # ─── Индикатор набора ─────────────────────────────────────────
    await ctx.bot.send_chat_action(
        chat_id=update.effective_chat.id,
        action="typing",
        message_thread_id=topic_id or None,
    )

    # ─── История контекста ────────────────────────────────────────
    history = get_history(user_id, limit=8)

    # ─── Роутинг к агенту ────────────────────────────────────────
    agent_name, response = orchestrator.route(
        message=message,
        history=history,
        topic_id=topic_id,
        force_agent=force_agent,
    )

    # ─── Сохраняем в историю ─────────────────────────────────────
    add_to_history(user_id, "user", message, agent_name)
    add_to_history(user_id, "assistant", response[:1000], agent_name)

    # ─── Отправляем ответ ─────────────────────────────────────────
    agent_emojis = {
        "analyst": "🔍", "strategist": "📋",
        "copywriter": "✍️", "designer": "🎨", "publisher": "📅",
    }
    emoji = agent_emojis.get(agent_name, "🤖")

    # Разбиваем длинные ответы на части (лимит Telegram — 4096 символов)
    max_len = 4000
    chunks = [response[i:i+max_len] for i in range(0, len(response), max_len)]

    for i, chunk in enumerate(chunks):
        prefix = f"{emoji} *{agent_name.capitalize()}:*\n\n" if i == 0 else ""
        try:
            await update.message.reply_text(
                prefix + chunk,
                parse_mode=ParseMode.MARKDOWN,
            )
        except Exception:
            # Если Markdown сломан — отправляем как plain text
            await update.message.reply_text(prefix + chunk)


async def handle_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Обработчик inline-кнопок (Опубликовать / Отмена)."""
    query = update.callback_query
    await query.answer()

    data = query.data
    if data.startswith("publish:"):
        draft_id = int(data.split(":")[1])
        await _publish_draft_callback(query, ctx, draft_id)

    elif data.startswith("cancel:"):
        draft_id = int(data.split(":")[1])
        update_draft_status(draft_id, "draft")
        await query.edit_message_text(f"❌ Публикация черновика #{draft_id} отменена.")


async def _publish_draft(update: Update, ctx: ContextTypes.DEFAULT_TYPE, draft_id: int):
    """Публикует черновик в канал."""
    draft = get_draft(draft_id)
    if not draft:
        await update.message.reply_text(f"Черновик #{draft_id} не найден.")
        return

    if not config.PUBLISH_CHANNEL:
        await update.message.reply_text(
            "⚠️ Канал для публикации не настроен.\n"
            "Добавь `PUBLISH_CHANNEL=@your_channel` в .env файл."
        )
        return

    try:
        sent = await ctx.bot.send_message(
            chat_id=config.PUBLISH_CHANNEL,
            text=draft["body"],
            parse_mode=ParseMode.MARKDOWN,
        )
        update_draft_status(draft_id, "published")
        save_published(draft_id, config.PUBLISH_CHANNEL, sent.message_id)
        await update.message.reply_text(
            f"✅ *Опубликовано!* Черновик #{draft_id} → {config.PUBLISH_CHANNEL}",
            parse_mode=ParseMode.MARKDOWN,
        )
    except Exception as e:
        await update.message.reply_text(f"❌ Ошибка публикации: {e}")


async def _publish_draft_callback(query, ctx: ContextTypes.DEFAULT_TYPE, draft_id: int):
    """Публикует через callback-кнопку."""
    draft = get_draft(draft_id)
    if not draft:
        await query.edit_message_text(f"Черновик #{draft_id} не найден.")
        return

    if not config.PUBLISH_CHANNEL:
        await query.edit_message_text(
            "⚠️ Канал для публикации не настроен. Добавь PUBLISH_CHANNEL в .env"
        )
        return

    try:
        sent = await ctx.bot.send_message(
            chat_id=config.PUBLISH_CHANNEL,
            text=draft["body"],
            parse_mode=ParseMode.MARKDOWN,
        )
        update_draft_status(draft_id, "published")
        save_published(draft_id, config.PUBLISH_CHANNEL, sent.message_id)
        await query.edit_message_text(
            f"✅ Опубликовано! Черновик #{draft_id} → {config.PUBLISH_CHANNEL}"
        )
    except Exception as e:
        await query.edit_message_text(f"❌ Ошибка: {e}")
