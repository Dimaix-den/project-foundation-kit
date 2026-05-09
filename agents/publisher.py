"""
Агент-менеджер публикаций.
- Управляет статусами черновиков
- Записывает контент-планы в Google Sheets
- Публикует одобренный контент
"""
import json
from agents.base import BaseAgent
from storage.db import get_drafts, get_draft, get_plan, update_draft_status
from storage.sheets import write_content_plan, is_sheets_enabled


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
- Записывать контент-планы в Google Sheets
- Показывать текущие черновики и план
- Расставлять приоритеты и планировать расписание
- Давать статус по всем материалам в работе

ЛУЧШЕЕ ВРЕМЯ ДЛЯ ПУБЛИКАЦИИ (Казахстан, финтех):
- Telegram: вт-чт, 9:00-10:00 или 18:00-20:00
- Понедельник: мотивационный контент
- Пятница: лёгкий итоговый контент

Отвечай на том же языке, на котором к тебе обращаются."""

    def _save_plan_to_sheets(self, content: str) -> str:
        """Парсит JSON из текста и записывает в Google Sheets."""
        if "```json" not in content:
            return "⚠️ В переданном плане нет JSON-блока — нечего записывать в таблицу."

        try:
            json_block = content.split("```json")[1].split("```")[0].strip()
            items = json.loads(json_block)
            if not isinstance(items, list) or not items:
                return "⚠️ JSON пустой или неверного формата."

            if is_sheets_enabled():
                return write_content_plan(items)
            else:
                return "⚠️ Google Sheets не подключён. Напиши /sheets_setup."

        except json.JSONDecodeError as e:
            return f"⚠️ Ошибка парсинга JSON: {e}"
        except Exception as e:
            return f"⚠️ Ошибка записи в таблицу: {e}"

    def get_status_report(self) -> str:
        """Сводка по всем материалам."""
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
        # Статус
        status_triggers = ["статус", "что в работе", "покажи план", "что готово", "дашборд"]
        if any(t in user_message.lower() for t in status_triggers):
            return self.get_status_report()

        # Запись в Google Sheets (когда куратор передаёт JSON-план)
        if "```json" in user_message:
            result = self._save_plan_to_sheets(user_message)
            if result.startswith("http"):
                return f"Контент-план записан в таблицу 📊 {result}"
            return result

        # Всё остальное — обычный ответ агента
        return super().run(user_message, history)
