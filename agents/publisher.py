"""
Агент-менеджер публикаций.
- Записывает контент-планы и тексты постов в Google Sheets
- Управляет статусами черновиков
"""
import re
import json
from agents.base import BaseAgent
from storage.db import get_drafts, get_draft, get_plan, update_draft_status
from storage.sheets import write_content_plan, write_texts_to_plan, is_sheets_enabled


def _parse_post_texts(content: str) -> list:
    """
    Парсит тексты постов из ответа копирайтера.
    Поддерживает форматы:
      ===ПОСТ 1===  (основной, задаётся куратором)
      --- ПОСТ 1 ---
      **ПОСТ 1:**
    Если разделителей нет — пробует split по 3+ пустым строкам.
    """
    # Основной формат: ===ПОСТ N===
    parts = re.split(r'={2,}\s*ПОСТ\s*\d+[^=]*={2,}', content, flags=re.IGNORECASE)
    texts = [p.strip() for p in parts if p.strip() and len(p.strip()) > 80]
    if len(texts) > 1:
        logger_msg = f"Распознано {len(texts)} постов по ===ПОСТ N==="
        return texts

    # Fallback: --- ПОСТ N ---
    parts = re.split(r'-{2,}\s*ПОСТ\s*\d+[^-]*-{2,}', content, flags=re.IGNORECASE)
    texts = [p.strip() for p in parts if p.strip() and len(p.strip()) > 80]
    if len(texts) > 1:
        return texts

    # Fallback: **ПОСТ N:**
    parts = re.split(r'\*{1,2}\s*ПОСТ\s*\d+[^*]*\*{1,2}:?', content, flags=re.IGNORECASE)
    texts = [p.strip() for p in parts if p.strip() and len(p.strip()) > 80]
    if len(texts) > 1:
        return texts

    # Последний fallback: разбиваем по 3+ пустым строкам
    parts = re.split(r'\n{3,}', content)
    texts = [p.strip() for p in parts if p.strip() and len(p.strip()) > 100]
    if len(texts) > 1:
        return texts

    # Один большой блок — возвращаем как есть
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
- Управлять статусами черновиков (черновик → одобрен → опубликован)
- Показывать план и статус материалов
- Советовать время публикации

ЛУЧШЕЕ ВРЕМЯ (Казахстан, финтех):
- Telegram: вт-чт, 9:00-10:00 или 18:00-20:00
- Пн: мотивация, Пт: лёгкий контент"""

    def _save_plan_from_json(self, content: str) -> str:
        try:
            json_block = content.split("```json")[1].split("```")[0].strip()
            items = json.loads(json_block)
            if not isinstance(items, list) or not items:
                return "⚠️ JSON пустой."
            if is_sheets_enabled():
                url = write_content_plan(items)
                if url.startswith("http"):
                    return f"Контент-план записан 📊 [Открыть таблицу]({url})"
                return url
            return "⚠️ Google Sheets не подключён — напиши /sheets_setup"
        except Exception as e:
            return f"⚠️ Ошибка: {e}"

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

    def _do_write_texts(self, raw_content: str) -> str:
        """Парсит тексты постов и записывает каждый в отдельную строку."""
        if not is_sheets_enabled():
            return "⚠️ Google Sheets не подключён — напиши /sheets_setup"

        texts = _parse_post_texts(raw_content)
        if not texts:
            return "⚠️ Не удалось распознать тексты постов в переданном контенте."

        result = write_texts_to_plan(texts)

        if isinstance(result, str) and "|" in result and result.startswith("http"):
            url, count = result.split("|", 1)
            return f"Готово 📊 Записано *{count} текстов* в колонку «Текст к посту» — [Открыть таблицу]({url})"
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

        # Запись текстов в колонку — куратор передаёт тексты от копирайтера
        if any(t in msg_lower for t in ["запиши тексты", "сохрани тексты", "текст к посту", "обнови тексты", "тексты в таблиц"]):
            # Извлекаем контент от копирайтера из контекста куратора
            if "КОНТЕКСТ:" in user_message:
                raw = user_message.split("КОНТЕКСТ:", 1)[1].strip()
            else:
                raw = user_message
            return self._do_write_texts(raw)

        # Запись плана с JSON (куратор или стратег передали JSON)
        if "```json" in user_message:
            return self._save_plan_from_json(user_message)

        # Запись плана из БД по ключевым словам
        if any(t in msg_lower for t in ["google sheets", "таблиц", "запиши план", "зафиксируй", "в таблицу", "сохрани план"]):
            return self._save_db_plan_to_sheets()

        # Всё остальное — ответ LLM
        return super().run(user_message, history)
