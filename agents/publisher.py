"""
Агент-менеджер публикаций.
- Управляет статусами черновиков
- Записывает контент-планы и тексты постов в Google Sheets
- Публикует одобренный контент
"""
import re
import json
from agents.base import BaseAgent
from storage.db import get_drafts, get_draft, get_plan, update_draft_status
from storage.sheets import write_content_plan, write_texts_to_plan, is_sheets_enabled


class PublisherAgent(BaseAgent):
    name = "publisher"
    emoji = "📅"

    def _system_prompt(self) -> str:
        brand = self._brand_context()
        return f"""Ты — менеджер публикаций и редакционный координатор Sanda.

БРЕНД-КОНТЕКСТ:
{brand}

ТВОИ ЗАДАЧИ:
- Управлять статусами контента (черновик → на согласовании → опубликован)
- Записывать контент-планы и тексты постов в Google Sheets
- Показывать текущие черновики и план
- Расставлять приоритеты и планировать расписание

ЛУЧШЕЕ ВРЕМЯ ДЛЯ ПУБЛИКАЦИИ (Казахстан, финтех):
- Telegram: вт-чт, 9:00-10:00 или 18:00-20:00
- Понедельник: мотивационный контент
- Пятница: лёгкий итоговый контент"""

    def _save_plan_to_sheets(self, content: str) -> str:
        """Парсит JSON из текста и записывает план в Google Sheets."""
        try:
            json_block = content.split("```json")[1].split("```")[0].strip()
            items = json.loads(json_block)
            if not isinstance(items, list) or not items:
                return "⚠️ JSON пустой или неверного формата."
            if is_sheets_enabled():
                return write_content_plan(items)
            return "⚠️ Google Sheets не подключён. Напиши /sheets_setup."
        except json.JSONDecodeError as e:
            return f"⚠️ Ошибка парсинга JSON: {e}"
        except Exception as e:
            return f"⚠️ Ошибка записи в таблицу: {e}"

    def _save_db_plan_to_sheets(self) -> str:
        """Читает план из БД и записывает в Google Sheets."""
        items = get_plan("planned")
        if not items:
            return "⚠️ В базе нет сохранённого контент-плана. Попроси стратега создать его."
        if not is_sheets_enabled():
            return "⚠️ Google Sheets не подключён. Напиши /sheets_setup."
        try:
            return write_content_plan(items)
        except Exception as e:
            return f"⚠️ Ошибка записи в таблицу: {e}"

    def _parse_post_texts(self, content: str) -> list[str]:
        """
        Парсит тексты отдельных постов из ответа копирайтера.
        Ожидает разделители: --- ПОСТ N --- или === ПОСТ N ===
        """
        # Пробуем разделители вида "--- ПОСТ 1 ---" или "=== ПОСТ 1 ==="
        parts = re.split(r'(?:---|\===)\s*ПОСТ\s*\d+[^-=]*(?:---|\===)', content, flags=re.IGNORECASE)
        texts = [p.strip() for p in parts if p.strip() and len(p.strip()) > 50]
        if len(texts) > 1:
            return texts

        # Fallback: разделяем по двойной пустой строке если постов несколько
        parts = re.split(r'\n{3,}', content)
        texts = [p.strip() for p in parts if p.strip() and len(p.strip()) > 100]
        if len(texts) > 1:
            return texts

        # Один большой текст — возвращаем как есть
        return [content.strip()]

    def _save_texts_to_sheets(self, content: str) -> str:
        """Парсит тексты постов из контента и записывает в колонку 'Текст к посту'."""
        if not is_sheets_enabled():
            return "⚠️ Google Sheets не подключён. Напиши /sheets_setup."

        texts = self._parse_post_texts(content)
        if not texts:
            return "⚠️ Не удалось распарсить тексты постов."

        result = write_texts_to_plan(texts)

        if "|" in result and result.startswith("http"):
            url, count = result.split("|", 1)
            return f"https://...|{count}"  # передаём дальше для форматирования
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
                sched = p.get("scheduled") or "без даты"
                lines.append(f"  • [{p['id']}] {p['topic']} — {sched}")
            if len(plan) > 5:
                lines.append(f"  _...и ещё {len(plan)-5}_")
        lines.append("")
        if drafts:
            lines.append(f"✏️ *Черновики:* {len(drafts)}")
            for d in drafts[:3]:
                lines.append(f"  • [#{d['id']}] {d['title'][:50] or 'без названия'}")
        if review:
            lines.append(f"👀 *На согласовании:* {len(review)}")
            for d in review:
                lines.append(f"  • [#{d['id']}] {d['title'][:50] or 'без названия'}")
        if approved:
            lines.append(f"✅ *Одобрено, ждёт публикации:* {len(approved)}")
            for d in approved:
                lines.append(f"  • [#{d['id']}] {d['title'][:50] or 'без названия'}")
        if not any([plan, drafts, review, approved]):
            lines.append("Пока пусто. Попроси стратега создать контент-план.")
        return "\n".join(lines)

    def run(self, user_message: str, history: list[dict] = None) -> str:
        msg_lower = user_message.lower()

        # Статус
        if any(t in msg_lower for t in ["статус", "что в работе", "покажи план", "что готово", "дашборд"]):
            return self.get_status_report()

        # Запись текстов постов в колонку (куратор передаёт тексты от копирайтера)
        texts_triggers = ["запиши тексты", "сохрани тексты", "текст к посту", "обнови тексты", "тексты в таблиц"]
        if any(t in msg_lower for t in texts_triggers):
            # Ищем блок КОНТЕКСТ от предыдущих шагов
            context_match = None
            if "КОНТЕКСТ:" in user_message:
                context_match = user_message.split("КОНТЕКСТ:", 1)[1].strip()
            content_to_parse = context_match or user_message
            result = write_texts_to_plan(self._parse_post_texts(content_to_parse))
            if isinstance(result, str) and "|" in result and result.startswith("http"):
                url, count = result.split("|", 1)
                return f"Тексты записаны в таблицу 📊 [{count} постов]({url})"
            if isinstance(result, str) and result.startswith("http"):
                return f"Тексты записаны в таблицу 📊 [Открыть]({result})"
            return result

        # Запись плана в Google Sheets (с JSON)
        if "```json" in user_message:
            result = self._save_plan_to_sheets(user_message)
        elif any(t in msg_lower for t in ["google sheets", "таблиц", "запиши", "зафиксируй", "в таблицу", "сохрани в"]):
            result = self._save_db_plan_to_sheets()
        else:
            return super().run(user_message, history)

        if isinstance(result, str) and result.startswith("http"):
            return f"Контент-план записан в таблицу 📊 [Открыть]({result})"
        return result
