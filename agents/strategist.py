"""
Агент-стратег: создаёт и корректирует контент-планы.
JSON используется внутренне — пользователю не показывается.
При любом изменении плана — тихо обновляет Google Sheets.
"""
import json
import re
from agents.base import BaseAgent
from storage.db import add_plan_items
from storage.sheets import write_content_plan, rewrite_content_plan, is_sheets_enabled


# Ключевые слова, означающие корректировку существующего плана
_EDIT_KEYWORDS = [
    "скоррект", "измен", "обнов", "перепиш", "замен",
    "перенес", "убер", "удал", "добав", "вместо",
    "поправ", "подправ", "переделай", "сдвин",
]


class StrategistAgent(BaseAgent):
    name = "strategist"
    emoji = "📋"

    def _system_prompt(self) -> str:
        from datetime import date
        today = date.today().isoformat()
        brand = self._brand_context()
        return f"""Ты — контент-стратег финтех-стартапа Sanda. Сегодня {today}.

БРЕНД-КОНТЕКСТ:
{brand}

Создавай контент-план сразу, без уточняющих вопросов. Если что-то не указано — придумай сам.

ФОРМАТЫ ПОСТОВ (чередуй):
- Финансовые лайфхаки для казахстанцев (Kaspi, рассрочки, накопления)
- Психология денег
- Фичи Sanda
- Вовлекающие вопросы
- Мотивация и привычки
- Новости продукта

СТРУКТУРА ОТВЕТА (строго):

1. Краткий список постов (без таблиц, просто текстом):
   Дата | Платформа | Тема | Цель

2. В самом конце — JSON-блок (обязательно):

```json
[{{"topic": "Тема", "description": "Суть поста, 60-80 символов", "platform": "telegram", "scheduled": "{today}"}}]
```

JSON должен содержать ВСЕ посты. scheduled — реальная дата YYYY-MM-DD."""

    def run(self, user_message: str, history: list = None) -> str:
        response = super().run(user_message, history)

        if "```json" not in response:
            return response

        # Извлекаем JSON
        try:
            json_block = response.split("```json")[1].split("```")[0].strip()
            items = json.loads(json_block)
            if not isinstance(items, list) or not items:
                return re.sub(r"```json.*?```", "", response, flags=re.DOTALL).strip()
        except Exception:
            return re.sub(r"```json.*?```", "", response, flags=re.DOTALL).strip()

        # Сохраняем в БД
        add_plan_items(items)

        # Определяем: это корректировка или новый план?
        msg_lower = user_message.lower()
        is_edit = any(kw in msg_lower for kw in _EDIT_KEYWORDS)

        # Тихо обновляем Google Sheets (без сообщений пользователю)
        if is_sheets_enabled():
            if is_edit:
                rewrite_content_plan(items)   # перезаписываем при корректировке
            else:
                write_content_plan(items)     # добавляем при новом плане

        # Убираем JSON из ответа пользователю
        clean = re.sub(r"```json.*?```", "", response, flags=re.DOTALL).strip()

        # Добавляем тихую пометку про Sheets (без полного текста плана)
        if is_sheets_enabled():
            action = "обновлён" if is_edit else "записан"
            clean += f"\n\n📊 _Таблица {action}_"

        return clean
