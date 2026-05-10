"""
Агент-менеджер публикаций.
Умеет читать Google Sheets и вносить любые правки через LLM.
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

SHEET_EDITOR_SYSTEM = """Ты — редактор Google Sheets для контент-команды Sanda.

Тебе дадут: (1) текущее содержимое таблицы, (2) запрос пользователя.

Ответь ТОЛЬКО валидным JSON-массивом изменений (без markdown):

[
  {"action": "update_by_topic", "topic": "Тема поста", "field": "Описание", "value": "новый текст"},
  {"action": "update_by_topic", "topic": "Тема поста", "field": "Дата", "value": "2026-05-15"},
  {"action": "update_by_topic", "topic": "Тема", "field": "Статус", "value": "✅ Готово"},
  {"action": "update_by_topic", "topic": "Тема", "field": "Текст к посту", "value": "полный текст"},
  {"action": "update", "row": 3, "field": "Платформа", "value": "instagram"},
  {"action": "add", "topic": "Новая тема", "description": "Описание", "platform": "telegram", "scheduled": "2026-05-20"},
  {"action": "delete_by_topic", "topic": "Тема для удаления"},
  {"action": "add_column", "name": "Название новой колонки"}
]

Поля: "Тема", "Описание", "Платформа", "Дата", "Статус", "Текст к посту"
Статусы: "📝 Черновик", "👀 На согласовании", "✅ Готово", "🚀 Опубликовано"
Если ничего менять не нужно — верни [].
scheduled формат: YYYY-MM-DD"""

# Маркеры, по которым определяем что контент — инструкция, а не реальные тексты постов
_INSTRUCTION_MARKERS = [
    "запиши тексты", "каждый пост", "отдельн строк", "используй данные",
    "google sheets", "колонку", "контент-план", "каждая строка",
]


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


def _looks_like_instruction(text: str) -> bool:
    """Проверяет, похоже ли содержимое на инструкцию, а не на реальный текст поста."""
    low = text.lower()
    return any(m in low for m in _INSTRUCTION_MARKERS)


def _extract_post_context(user_message: str) -> str:
    """Извлекает тексты постов из сообщения куратора."""
    # Ищем блок [Тексты постов]: в контексте
    if "[Тексты постов]:" in user_message:
        raw = user_message.split("[Тексты постов]:", 1)[1].strip()
        # Обрезаем если дальше идёт следующий блок [...]
        if "\n\n[" in raw:
            raw = raw.split("\n\n[", 1)[0].strip()
        return raw
    # Fallback: всё после КОНТЕКСТ:
    if "КОНТЕКСТ:" in user_message:
        return user_message.split("КОНТЕКСТ:", 1)[1].strip()
    return user_message


class PublisherAgent(BaseAgent):
    name = "publisher"
    emoji = "📅"

    def _system_prompt(self) -> str:
        brand = self._brand_context()
        return f"""Ты — менеджер публикаций Sanda.

БРЕНД-КОНТЕКСТ:
{brand}

ТВОИ ЗАДАЧИ:
- Управлять Google Sheets (читать, редактировать, дополнять)
- Управлять статусами черновиков
- Показывать план и статус материалов
- Советовать время публикации

ЛУЧШЕЕ ВРЕМЯ (Казахстан, финтех):
- Telegram: вт-чт, 9:00-10:00 или 18:00-20:00
- Пн: мотивация, Пт: лёгкий контент"""

    def _edit_sheet_with_llm(self, user_request: str, extra_context: str = "") -> str:
        """Читает таблицу → Claude составляет изменения → применяет."""
        if not is_sheets_enabled():
            return "⚠️ Google Sheets не подключён — напиши /sheets_setup"
        sheet_content = read_sheet_as_text()
        if not sheet_content or sheet_content == "Таблица пуста или недоступна.":
            return "⚠️ Таблица пуста. Сначала создай контент-план."

        user_msg = f"Таблица:\n{sheet_content}\n\nЗапрос: {user_request}"
        if extra_context:
            user_msg += f"\n\nДополнительный контекст:\n{extra_context[:2000]}"

        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        for attempt in range(3):
            try:
                resp = client.messages.create(
                    model=MODEL,
                    max_tokens=2048,
                    system=SHEET_EDITOR_SYSTEM,
                    messages=[{"role": "user", "content": user_msg}],
                )
                break
            except anthropic.APIStatusError as e:
                if e.status_code == 529 and attempt < 2:
                    time.sleep([10, 30, 60][attempt])
                    continue
                raise

        raw = resp.content[0].text.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
            raw = raw.split("```")[0]

        try:
            changes = json.loads(raw.strip())
        except json.JSONDecodeError as e:
            logger.error(f"[Publisher] JSON parse error: {e} | raw: {raw[:300]}")
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
            return "⚠️ Google Sheets не подключён"
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
        """Парсит тексты постов и записывает каждый в отдельную строку."""
        if not is_sheets_enabled():
            return "⚠️ Google Sheets не подключён"

        texts = _parse_post_texts(raw_content)

        # Если вместо текстов постов пришла инструкция — сообщаем об ошибке
        if len(texts) == 1 and _looks_like_instruction(texts[0]):
            return (
                "⚠️ Нет текстов для записи — в контексте только инструкция, не контент.\n\n"
                "Используй:\n`/create напишите тексты для всех постов и запишите в таблицу`\n\n"
                "Копирайтер напишет тексты, затем я запишу их по строкам."
            )

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

        # Запись текстов в колонку (куратор передаёт результат копирайтера)
        text_write_triggers = [
            "запиши тексты", "сохрани тексты", "текст к посту",
            "обнови тексты", "тексты в таблиц", "записаны по строкам",
        ]
        if any(t in msg_lower for t in text_write_triggers):
            raw = _extract_post_context(user_message)
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
            "перенес", "замен", "дату", "описани",
            "google sheets", "sheets",
        ]
        if any(t in msg_lower for t in sheet_edit_triggers) and is_sheets_enabled():
            extra_ctx = ""
            instruction = user_message
            if "КОНТЕКСТ:" in user_message:
                parts = user_message.split("КОНТЕКСТ:", 1)
                instruction = parts[0].strip()
                extra_ctx = parts[1].strip()
            return self._edit_sheet_with_llm(instruction, extra_ctx)

        return super().run(user_message, history)
