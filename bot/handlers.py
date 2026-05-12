"""
Обработчики Telegram-сообщений.
"""
import os
import re
import logging
import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from telegram.constants import ParseMode

import config
from agents.orchestrator import Orchestrator
from agents.curator import CuratorAgent
from agents.analyst import AnalystAgent
from storage.db import (
    add_to_history, get_history,
    get_draft, update_draft_status,
    save_published, get_drafts,
    set_brand, get_all_brand,
)
from storage.sheets import is_sheets_enabled

logger = logging.getLogger(__name__)
orchestrator = Orchestrator()
curator = CuratorAgent()
analyst = AnalystAgent()

DOWNLOADS_DIR = "/tmp/sanda_files"
os.makedirs(DOWNLOADS_DIR, exist_ok=True)

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


async def _run_curator(task: str, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Общий хелпер: запускает куратора и отправляет результаты в чат."""
    chat_id   = update.effective_chat.id
    thread_id = getattr(update.message, "message_thread_id", None)
    loop      = asyncio.get_event_loop()

    # Прогресс только в логах, не в чат
    def sync_progress(step, text):
        logger.info(f"[Curator progress] {step}: {text}")

    await ctx.bot.send_chat_action(chat_id=chat_id, action="typing")

    try:
        results = await loop.run_in_executor(
            None, lambda: curator.run(task, progress_cb=sync_progress)
        )
    except Exception as e:
        logger.error(f"Curator error: {e}", exc_info=True)
        await update.message.reply_text(f"Что-то пошло не так: {e}")
        return

    # Отправляем результаты шагов
    steps = results.get("steps_results", [])
    for step in steps:
        result = step.get("result", "").strip()
        agent  = step.get("agent", "")

        if not result:
            continue

        # Стратег: если план уже в Sheets — показываем только подтверждение, не дамп плана
        if agent == "strategist" and is_sheets_enabled():
            sheets_line = next(
                (line for line in result.splitlines() if "Таблица" in line or "таблица" in line),
                None,
            )
            if sheets_line:
                # Показываем первую строку (итог) + строку про таблицу
                first_line = result.splitlines()[0].strip()
                short = f"{first_line}\n{sheets_line}" if first_line != sheets_line else sheets_line
                try:
                    await ctx.bot.send_message(
                        chat_id=chat_id, text=short,
                        parse_mode=ParseMode.MARKDOWN,
                        message_thread_id=thread_id,
                    )
                except Exception:
                    await ctx.bot.send_message(chat_id=chat_id, text=short, message_thread_id=thread_id)
                continue

        # Дизайнер: проверяем маркер [IMAGE_FILE:path]
        img_match = re.search(r'\[IMAGE_FILE:(.+?)\]', result)
        if img_match:
            img_path = img_match.group(1).strip()
            caption = result.replace(img_match.group(0), "").strip()
            try:
                with open(img_path, "rb") as img_f:
                    await ctx.bot.send_photo(
                        chat_id=chat_id,
                        photo=img_f,
                        caption=caption[:1024] if caption else None,
                        parse_mode=ParseMode.MARKDOWN,
                        message_thread_id=thread_id,
                    )
            except Exception as e:
                logger.warning(f"Не удалось отправить фото: {e}")
                if caption:
                    await ctx.bot.send_message(chat_id=chat_id, text=caption, message_thread_id=thread_id)
            finally:
                try:
                    os.unlink(img_path)
                except Exception:
                    pass
            continue

        # Обычный текстовый результат
        chunks = [result[i:i+3800] for i in range(0, len(result), 3800)]
        for chunk in chunks:
            try:
                await ctx.bot.send_message(
                    chat_id=chat_id, text=chunk,
                    parse_mode=ParseMode.MARKDOWN,
                    message_thread_id=thread_id,
                )
            except Exception:
                await ctx.bot.send_message(
                    chat_id=chat_id, text=chunk,
                    message_thread_id=thread_id,
                )

    # Кнопки если есть черновик
    draft_id = results.get("draft_id")
    if draft_id:
        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton("✅ Опубликовать", callback_data=f"publish:{draft_id}"),
            InlineKeyboardButton("✏️ Доработать",  callback_data=f"revise:{draft_id}"),
        ]])
        await ctx.bot.send_message(
            chat_id=chat_id,
            text=f"💾 *Черновик #{draft_id} сохранён*\nЧто делаем?",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=keyboard,
            message_thread_id=thread_id,
        )


async def cmd_pipeline(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Команда /create — передаёт задачу куратору."""
    logger.info(f"📨 /create от user_id={update.effective_user.id}")
    task = " ".join(ctx.args) if ctx.args else ""
    if not task:
        await update.message.reply_text(
            "📝 Напиши задачу после команды, например:\n"
            "`/create пост в Threads про финансовые привычки`\n"
            "`/create контент-план на неделю`\n"
            "`/create визуал и пост про запуск приложения`",
            parse_mode=ParseMode.MARKDOWN,
        )
        return
    await _run_curator(task, update, ctx)


async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Приветствие и инструкция."""
    logger.info(f"📨 /start от user_id={update.effective_user.id} (@{update.effective_user.username})")
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
        "🧠 *Куратор принимает любые задачи:*\n"
        "`/create [задача]` — примеры:\n"
        "• `/create пост в Threads про финансы`\n"
        "• `/create контент-план на неделю`\n"
        "• `/create визуал и пост про запуск Sanda`\n"
        "• `/create анализ конкурентов`\n\n"
        "Или вызывай агента напрямую:\n"
        "`@аналитик`, `@стратег`, `@копирайтер`, `@дизайнер`, `@менеджер`\n\n"
        "Другие команды:\n"
        "/status — что в работе\n"
        "/drafts — черновики\n"
        "/brand_init — загрузить контекст Sanda\n"
        "/help — справка"
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


async def cmd_brand_init(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Инициализирует полный бренд-контекст Sanda в БД."""
    logger.info(f"📨 /brand_init от user_id={update.effective_user.id}")
    await update.message.reply_text("⏳ Записываю бренд-контекст Sanda в базу...")
    try:
        import subprocess, sys
        result = subprocess.run(
            [sys.executable, "brand_context.py"],
            capture_output=True, text=True, timeout=30
        )
        if result.returncode == 0:
            await update.message.reply_text(
                "✅ *Бренд-контекст Sanda загружен!*\n\n"
                "Все агенты теперь знают о продукте, аудитории, тоне и визуальном стиле.\n"
                "Попробуй: `/create контроль расходов для казахстанцев`",
                parse_mode=ParseMode.MARKDOWN,
            )
        else:
            await update.message.reply_text(f"❌ Ошибка: {result.stderr[:500]}")
    except Exception as e:
        await update.message.reply_text(f"❌ {e}")


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
    logger.info(f"📨 Входящее сообщение: update={update.update_id}, chat={update.effective_chat.id}, user={update.effective_user.id}")

    if not update.message or not update.message.text:
        logger.info("⚠️ Нет message или text — пропускаем")
        return

    user_id  = update.effective_user.id
    message  = update.message.text.strip()
    topic_id = getattr(update.message, "message_thread_id", 0) or 0

    logger.info(f"📝 Текст: '{message[:80]}' | user_id={user_id} | topic_id={topic_id}")

    if not is_allowed(user_id):
        logger.info(f"🚫 user_id={user_id} не в списке ALLOWED_USER_IDS")
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

    # ─── Явный вызов конкретного агента через @имя ───────────────
    if force_agent:
        history = get_history(user_id, limit=8)
        agent_name, response = orchestrator.route(
            message=message,
            history=history,
            topic_id=topic_id,
            force_agent=force_agent,
        )
        add_to_history(user_id, "user", message, agent_name)
        add_to_history(user_id, "assistant", response[:1000], agent_name)
        agent_emojis = {
            "analyst": "🔍", "strategist": "📋",
            "copywriter": "✍️", "designer": "🎨", "publisher": "📅",
        }
        emoji = agent_emojis.get(agent_name, "🤖")
        max_len = 4000
        chunks = [response[i:i+max_len] for i in range(0, len(response), max_len)]
        for i, chunk in enumerate(chunks):
            prefix = f"{emoji} *{agent_name.capitalize()}:*\n\n" if i == 0 else ""
            try:
                await update.message.reply_text(prefix + chunk, parse_mode=ParseMode.MARKDOWN)
            except Exception:
                await update.message.reply_text(prefix + chunk)
        return

    # ─── Всё остальное — куратор (мульти-агентный пайплайн) ──────
    await _run_curator(message, update, ctx)


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


async def handle_document(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Обработчик файлов: PDF, DOCX, TXT — передаёт аналитику для анализа."""
    user_id = update.effective_user.id
    if not is_allowed(user_id):
        return

    doc = update.message.document
    if not doc:
        return

    # Проверяем формат
    fname = doc.file_name or ""
    allowed_exts = (".pdf", ".docx", ".txt")
    if not any(fname.lower().endswith(ext) for ext in allowed_exts):
        await update.message.reply_text(
            "📎 Поддерживаю документы: PDF, DOCX, TXT\n"
            "Для других форматов — скопируй текст и пришли напрямую."
        )
        return

    await update.message.reply_text(f"📥 Получил файл *{fname}*, скачиваю и анализирую...", parse_mode=ParseMode.MARKDOWN)
    await ctx.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")

    # Скачиваем файл
    try:
        tg_file = await ctx.bot.get_file(doc.file_id)
        local_path = os.path.join(DOWNLOADS_DIR, fname)
        await tg_file.download_to_drive(local_path)
    except Exception as e:
        await update.message.reply_text(f"❌ Не удалось скачать файл: {e}")
        return

    # Текст задачи из подписи к файлу (caption) или дефолтный
    caption = (update.message.caption or "").strip()
    task = caption if caption else f"Проанализируй этот документ и выдели ключевые инсайты для контент-стратегии Sanda."

    # Запускаем аналитика с file_path
    loop = asyncio.get_event_loop()
    history = get_history(user_id, limit=4)
    try:
        response = await loop.run_in_executor(
            None, lambda: analyst.run(task, history=history, file_path=local_path)
        )
    except Exception as e:
        logger.error(f"Analyst doc error: {e}", exc_info=True)
        await update.message.reply_text(f"❌ Ошибка анализа: {e}")
        return

    add_to_history(user_id, "user", f"[файл: {fname}] {task}", "analyst")
    add_to_history(user_id, "assistant", response[:1000], "analyst")

    # Отправляем ответ
    max_len = 4000
    chunks = [response[i:i+max_len] for i in range(0, len(response), max_len)]
    for i, chunk in enumerate(chunks):
        prefix = "🔍 *Аналитик:*\n\n" if i == 0 else ""
        try:
            await update.message.reply_text(prefix + chunk, parse_mode=ParseMode.MARKDOWN)
        except Exception:
            await update.message.reply_text(prefix + chunk)


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
        # Telegram принимает ID канала как int или строку "-100XXXXXXXXX"
        channel = config.PUBLISH_CHANNEL
        try:
            channel = int(channel)
        except (ValueError, TypeError):
            pass  # оставляем как строку (@username)

        sent = await ctx.bot.send_message(
            chat_id=channel,
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
        err = str(e)
        hint = ""
        if "Chat not found" in err:
            hint = (
                "\n\n💡 *Возможные причины:*"
                "\n• Неверный ID канала — проверь через @userinfobot"
                "\n• Бот не добавлен в канал как администратор"
                "\n• Бот не имеет права публиковать сообщения"
                f"\n\nТекущий PUBLISH\_CHANNEL: `{config.PUBLISH_CHANNEL}`"
            )
        await update.message.reply_text(
            f"❌ Ошибка публикации: {e}{hint}",
            parse_mode=ParseMode.MARKDOWN,
        )


async def cmd_sheets_setup(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Инструкция по подключению Google Sheets."""
    logger.info(f"📨 /sheets_setup от user_id={update.effective_user.id}")

    if is_sheets_enabled():
        await update.message.reply_text(
            "✅ *Google Sheets уже подключён!*\n\n"
            "Стратег будет записывать контент-план в таблицу автоматически.\n"
            "Попробуй: `/create контент-план на неделю`",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    text = (
        "📊 *Как подключить Google Sheets (5 минут):*\n\n"
        "*Шаг 1.* Создай Service Account\n"
        "→ https://console.cloud.google.com\n"
        "→ Выбери проект (или создай новый)\n"
        "→ APIs & Services → Enable APIs → включи *Google Sheets API*\n"
        "→ IAM & Admin → Service Accounts → Create Service Account\n"
        "→ Назови его `sanda-content-bot`, нажми Create\n"
        "→ Keys → Add Key → JSON → скачай файл\n\n"
        "*Шаг 2.* Создай Google Таблицу\n"
        "→ Открой новую таблицу на sheets.google.com\n"
        "→ Скопируй ID из URL: `docs.google.com/spreadsheets/d/`*<<ID здесь>>*`/edit`\n"
        "→ Нажми «Настроить доступ» → добавь email из скачанного JSON (поле `client_email`) как *редактора*\n\n"
        "*Шаг 3.* Добавь в Railway Variables:\n"
        "`GOOGLE_SHEETS_ID` = ID таблицы из URL\n"
        "`GOOGLE_SERVICE_ACCOUNT_JSON` = *всё содержимое* скачанного JSON-файла\n\n"
        "После деплоя стратег будет автоматически заполнять таблицу 🎉"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN, disable_web_page_preview=True)


async def cmd_sheets_test(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Диагностика подключения к Google Sheets."""
    import os, json as _json
    lines = ["🔍 *Диагностика Google Sheets:*\n"]

    # 1. Проверяем переменные
    sheets_id = os.getenv("GOOGLE_SHEETS_ID", "")
    sa_json   = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "")

    lines.append(f"GOOGLE_SHEETS_ID: {'✅ ' + sheets_id[:20] + '...' if sheets_id else '❌ не задан'}")
    lines.append(f"GOOGLE_SERVICE_ACCOUNT_JSON: {'✅ задан (' + str(len(sa_json)) + ' символов)' if sa_json else '❌ не задан'}")

    if not sheets_id or not sa_json:
        await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN)
        return

    # 2. Парсим JSON
    try:
        sa_info = _json.loads(sa_json)
        lines.append(f"JSON парсинг: ✅ (client_email: {sa_info.get('client_email', '?')})")
    except Exception as e:
        lines.append(f"JSON парсинг: ❌ {e}")
        await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN)
        return

    # 3. Авторизация
    try:
        import gspread
        from google.oauth2.service_account import Credentials
        scopes = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
        creds = Credentials.from_service_account_info(sa_info, scopes=scopes)
        gc = gspread.authorize(creds)
        lines.append("Авторизация Google: ✅")
    except Exception as e:
        lines.append(f"Авторизация Google: ❌ {e}")
        await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN)
        return

    # 4. Открываем таблицу
    try:
        spreadsheet = gc.open_by_key(sheets_id)
        lines.append(f"Открытие таблицы: ✅ '{spreadsheet.title}'")
    except Exception as e:
        lines.append(f"Открытие таблицы: ❌ {e}")
        lines.append(f"\n💡 Убедись что добавил {sa_info.get('client_email')} как редактора в таблицу")
        await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN)
        return

    # 5. Тестовая запись
    try:
        from storage.sheets import write_content_plan
        result = write_content_plan([{
            "topic": "Тест подключения",
            "description": "Проверка работы Google Sheets интеграции",
            "platform": "telegram",
            "scheduled": "2026-05-10",
        }])
        lines.append(f"Тестовая запись: ✅")
        lines.append(f"\n{result}")
    except Exception as e:
        lines.append(f"Тестовая запись: ❌ {e}")

    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN, disable_web_page_preview=True)


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
        channel = config.PUBLISH_CHANNEL
        try:
            channel = int(channel)
        except (ValueError, TypeError):
            pass

        sent = await ctx.bot.send_message(
            chat_id=channel,
            text=draft["body"],
            parse_mode=ParseMode.MARKDOWN,
        )
        update_draft_status(draft_id, "published")
        save_published(draft_id, config.PUBLISH_CHANNEL, sent.message_id)
        await query.edit_message_text(
            f"✅ Опубликовано! Черновик #{draft_id} → {config.PUBLISH_CHANNEL}"
        )
    except Exception as e:
        err = str(e)
        hint = " (проверь ID канала и права бота)" if "Chat not found" in err else ""
        await query.edit_message_text(f"❌ Ошибка: {e}{hint}")


async def cmd_test_channel(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Диагностика подключения к каналу публикации."""
    lines = ["🔍 *Диагностика канала*\n"]

    channel = config.PUBLISH_CHANNEL
    if not channel:
        await update.message.reply_text("❌ PUBLISH\\_CHANNEL не задан в переменных окружения.")
        return

    lines.append(f"PUBLISH\\_CHANNEL: `{channel}`")

    # Приводим к int если числовой ID
    channel_id = channel
    try:
        channel_id = int(channel)
        lines.append(f"Тип: числовой ID ({channel_id})")
    except (ValueError, TypeError):
        lines.append(f"Тип: username/строка")

    # Пробуем получить инфо о чате
    try:
        chat = await ctx.bot.get_chat(chat_id=channel_id)
        lines.append(f"✅ Чат найден!")
        lines.append(f"Название: {chat.title}")
        lines.append(f"Тип: {chat.type}")
        lines.append(f"ID: `{chat.id}`")
    except Exception as e:
        lines.append(f"❌ get\\_chat: {e}")
        lines.append("\n*Возможные причины:*")
        lines.append("• Неверный ID — узнай точный через @userinfobot")
        lines.append("• Бот не добавлен в канал")
        lines.append("• Бот не является администратором канала")
        await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN)
        return

    # Пробуем отправить тестовое сообщение
    try:
        sent = await ctx.bot.send_message(
            chat_id=channel_id,
            text="🔧 Тест подключения Sanda Marketing Bot — всё работает!",
        )
        lines.append(f"✅ Тестовое сообщение отправлено (ID: {sent.message_id})")
        # Удаляем тестовое сообщение
        try:
            await ctx.bot.delete_message(chat_id=channel_id, message_id=sent.message_id)
            lines.append("_(тестовое сообщение удалено)_")
        except Exception:
            pass
    except Exception as e:
        lines.append(f"❌ Отправка сообщения: {e}")
        lines.append("\nПроверь что бот имеет право *публиковать сообщения* в канале.")

    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN)
