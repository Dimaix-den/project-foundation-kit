"""
Агент-менеджер публикаций.
Умеет читать Google Sheets и вносить любые правки:
обновлять ячейки, добавлять строки/столбцы, удалять записи.
"""
import re
import json
import logging
import time
import anthropic
from agents.base import BaseAgent
from storage.db import get_drafts, get_draft, get_plan, update_draft_status
from storage.sheets import (
    write_content_plan, rewrite_content_plan, write_texts_to_plan,
    apply_changes, read_sheet_as_text, is_sheets_enabled,
)
from config import ANTHROPIC_API_KEY, MODEL

logger = logging.getLogger(__name__)

# Системный промпт для Claude-редактора таблицы
SHEET_EDITOR_SYSTEM = """Ты — редактор Google Sheets для контент-команды Sanda.

Тебе дадут:
1. Текущее содержимое таблицы (построчно)
2. Запрос пользователя на изменение

Ответь ТОЛЬКО валидным JSON-массивом изменений (без markdown, без пояснений):

[
  {"action": "update_by_topic", "topic": "Тема поста", "field": "Описание", "value": "новое значение"},
  {"action": "update_by_topic", "topic": "Тема поста", "field": "Дата", "value": "2026-05-15"},
  {"action": "update_by_topic", "topic": "Тема поста", "field": "Статус", "value": "✅ Готово"},
  {"action": "update_by_topic", "topic": "Тема поста", "field": "Текст к посту", "value": "полный текст"},
  {"action": "update", "row": 3, "field": "Платформа", "value": "instagram"},
  {"action": "add", "topic": "Новая тема", "description": "Описание", "platform": "telegram", "scheduled": "2026-05-20"},
  {"action": "delete_by_topic", "topic": "Тема для удаления"},
  {"action": "add_column", "name": "Название новой колонки"}
]

Доступные поля для update: "Тема", "Описание", "Платформа", "Дата", "Статус", "Текст к посту"
Доступные статусы: "📝 Черновик", "👀 На согласовании", "✅ Готово", "🚀 Опубликовано"

Правила:
- Возвращай ТОЛЬКО JSON-массив, без пояснений
- Если ничего менять не нужно — верни []
- update_by_topic ищет строку по частичному совпадению темы
- scheduled формат: YYYY-MM-DD"""


def _parse_post_texts(content: str) -> list:
    """Парсит тексты постов по разделителям ===ПОСТ N===."""
    parts = re.split(r'={2,}\s*ПОСТ\s*\d+[^=]*={2,}', content, flags=re.IGNORECASE)
    texts = [p.strip() for p in parts if p.strip() and len(p.strip()) > 80]
    if len(texts) > 1:
        return texts
    parts = re.split(r'-{2,}\s*ПОСТ\s*\d+[^-]*-{2,}', content, flags=re.IGNORECASE)
    texts = [p.strip() for p in parts if p.strip() and len(p.strip()) > 80]
    if len(texts) > 1:
        return texts
    parts = re.split(r'\n{3,}', content)
    texts = [p.strip() for p in parts if p.strip() and len(p.strip()) > 100]
    if len(texts) > 1:
        return texts
    return [content.strip()] if content.strip() else []


class PublisherAgent(BaseAgent):
    name = "publisher"
    emoji = "📅"

    def _system_prompt(self) -> str:
        brand = self._brand_context()
        return f"""Ты — менеджер публикаций Sanda.

БРЕНД-КОНТЕКСТ:
{brand}

ТВОИ ЗАДАЧИ:
- Управлять Google Sheets с контент-планом (читать, редактировать, дополнять)
- Управлять статусами черновиков
- Показывать план и статус материалов
- Советовать время публикации

ЛУЧШЕЕ ВРЕМЯ (Казахстан, финтех):
- Telegram: вт-чт, 9:00-10:00 или 18:00-20:00
- Пн: мотивация, Пт: лёгкий контент"""

    def _edit_sheet_with_llm(self, user_request: str, extra_context: str = "") -> str:
        """
        Читает таблицу → передаёт Claude → получает список изменений → применяет.
        """
        if not is_sheets_enabled():
            return "⚠️ Google Sheets не подключён — напиши /sheets_setup"

        sheet_content = read_sheet_as_text()
        if not sheet_content or sheet_content == "Таблица пуста или недоступна.":
            return "⚠️ Таблица пуста или недоступна. Сначала создай контент-план."

        user_msg = f"Таблица:\n{sheet_content}\n\nЗапрос: {user_request}"
        if extra_context:
            user_msg += f"\n\nДополнительный контекст:\n{extra_context[:2000]}"

        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        max_retries = 3
        for attempt in range(max_retries):
            try:
                resp = client.messages.create(
                    model=MODEL,
                    max_tokens=2048,
                    system=SHEET_EDITOR_SYSTEM,
                    messages=[{"role": "user", "content": user_msg}],
                )
                break
            except anthropic.APIStatusError as e:
                if e.status_code == 529 and attempt < max_retries - 1:
                    time.sleep([10, 30, 60][attempt])
                    continue
                raise

        raw = resp.content[0].text.strip()
        # Убираем markdown если есть
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
            raw = raw.split("```")[0]

        try:
            changes = json.loads(raw.strip())
        except json.JSONDecodeError as e:
            logger.error(f"[Publisher] Не удалось распарсить JSON изменений: {e}\nRaw: {raw[:300]}")
            return f"⚠️ Не удалось составить список изменений: {e}"

        if not changes:
            return "Изменений не требуется — таблица уже актуальна."

        result = apply_changes(changes)
        n = len(changes)
        if result.startswith("http"):
            return f"Готово 📊 Внесено *{n} изменений* — [Открыть таблицу]({result})"
        return result

    def _save_db_plan_to_sheets(self) -> str:
        items = get_plan("planned")
        if not items:
            return "⚠️ В базе нет контент-плана. Попроси стратега создать его."
        if not is_sheets_enabled():
            return "⚠️ Google Sheets не подключён — напиши /sheets_setup"
        url = write_content_plan(items)
        if url.startswith("http"):
            return f"Контент-план записан 📊 [Открыть таблицу]({url})"
        return url

    def _save_plan_from_json(self, content: str) -> str:
        try:
            json_block = content.split("```json")[1].split("```")[0].strip()
            items = json.loads(json_block)
            if not isinstance(items, list) or not items:
                return "⚠️ JSON пустой."
            if not is_sheets_enabled():
                return "⚠️ Google Sheets не подключён"
            url = write_content_plan(items)
            if url.startswith("http"):
                return f"Контент-план записан 📊 [Открыть таблицу]({url})"
            return url
        except Exception as e:
            return f"⚠️ Ошибка: {e}"

    def _write_texts(self, raw_content: str) -> str:
        if not is_sheets_enabled():
            return "⚠️ Google Sheets не подключён"
        texts = _parse_post_texts(raw_content)
        if not texts:
            return "⚠️ Не удалось распознать тексты постов."
        result = write_texts_to_plan(texts)
        if isinstance(result, str) and "|" in result and result.startswith("http"):
            url, count = result.split("|", 1)
            return f"Готово 📊 Записано *{count} текстов* — [Открыть таблицу]({url})"
        if isinstance(result, str) and result.startswith("http"):
            return f"Готово 📊 [Открыть таблицу]({result})"
        return result

    def get_status_report(self) -> str:
        drafts   = get_drafts("draft")
        review   = get_drafts("review")
        approved = get_drafts("approved")
        plan     = get_plan("planned")
        lines = ["📊 *Статус контент-команды*\n"]
        if plan:
            lines.append(f"📋 *Контент-план:* {len(plan)} тем")
            for p in plan[:5]:
                lines.append(f"  • [{p['id']}] {p['topic']} — {p.get('scheduled','?')}")
            if len(plan) > 5:
                lines.append(f"  _...и ещё {len(plan)-5}_")
        lines.append("")
        for label, emoji, items in [
            ("Черновики", "✏️", drafts[:3]),
            ("На согласовании", "👀", review),
            ("Одобрено", "✅", approved),
        ]:
            if items:
                lines.append(f"{emoji} *{label}:* {len(items)}")
                for d in items:
                    lines.append(f"  • [#{d['id']}] {(d['title'] or 'без названия')[:50]}")
        if not any([plan, drafts, review, approved]):
            lines.append("Пока пусто. Попроси стратега создать контент-план.")
        return "\n".join(lines)

    def run(self, user_message: str, history: list = None) -> str:
        msg_lower = user_message.lower()

        # Статус
        if any(t in msg_lower for t in ["статус", "что в работе", "покажи план", "что готово", "дашборд"]):
            return self.get_status_report()

        # Запись текстов в колонку (от куратора/копирайтера)
        if any(t in msg_lower for t in ["запиши тексты", "сохрани тексты", "текст к посту", "обнови тексты", "тексты в таблиц"]):
            raw = user_message.split("КОНТЕКСТ:", 1)[1].strip() if "КОНТЕКСТ:" in user_message else user_message
            return self._write_texts(raw)

        # Запись нового плана с JSON
        if "```json" in user_message:
            return self._save_plan_from_json(user_message)

        # Запись плана из БД
        if any(t in msg_lower for t in ["запиши план", "зафиксируй план", "сохрани план"]):
            return self._save_db_plan_to_sheets()

        # Любые правки таблицы — через LLM-редактор
        sheet_edit_triggers = [
            "таблиц", "столбец", "строк", "ячейк",
            "измени", "обнови", "добавь", "удали", "скоррект",
            "перенес", "замен", "статус", "дату", "описани",
            "google sheets", "sheets",
        ]
        if any(t in msg_lower for t in sheet_edit_triggers) and is_sheets_enabled():
            extra_ctx = ""
            if "КОНТЕКСТ:" in user_message:
                extra_ctx = user_message.split("КОНТЕКСТ:", 1)[1].strip()
                user_message = user_message.split("КОНТЕКСТ:", 1)[0].strip()
            return self._edit_sheet_with_llm(user_message, extra_ctx)

        return super().run(user_message, history)
