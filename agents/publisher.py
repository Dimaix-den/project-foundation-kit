"""
Агент-менеджер публикаций: управляет расписанием, статусами черновиков,
публикует одобренный контент в Telegram-канал.
"""
from agents.base import BaseAgent
from storage.db import get_drafts, get_draft, get_plan, update_draft_status


class PublisherAgent(BaseAgent):
    name = "publisher"
    emoji = "📅"

    def _system_prompt(self) -> str:
        brand = self._brand_context()
        return f"""Ты — менеджер публикаций и редакционный координатор.

БРЕНД-КОНТЕКСТ:
{brand}

ТВОИ ЗАДАЧИ:
- Управлять статусами контента (черновик → на согласовании → опубликован)
- Показывать контент-план и текущие черновики
- Помогать расставлять приоритеты и планировать расписание
- Давать статус по всем материалам в работе
- Советовать лучшее время для публикации

ЛУЧШЕЕ ВРЕМЯ ДЛЯ B2B КОНТЕНТА:
- Telegram: вт-чт, 9:00-10:00 или 17:00-19:00
- Понедельник: мотивационный/итоговый контент
- Пятница: лёгкий, итоговый контент
- Выходные: минимальная активность

Отвечай на том же языке, на котором к тебе обращаются."""

    def get_status_report(self) -> str:
        """Генерирует сводку по всем материалам."""
        drafts = get_drafts("draft")
        review = get_drafts("review")
        approved = get_drafts("approved")
        plan = get_plan("planned")

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
            lines.append("Пока пусто. Начни с команды `/plan` чтобы создать контент-план!")

        return "\n".join(lines)

    def run(self, user_message: str, history: list[dict] = None) -> str:
        status_triggers = ["статус", "что в работе", "покажи план", "что готово", "дашборд"]
        if any(t in user_message.lower() for t in status_triggers):
            return self.get_status_report()
        return super().run(user_message, history)
