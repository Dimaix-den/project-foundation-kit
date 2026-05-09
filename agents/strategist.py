"""
Агент-стратег: создаёт контент-планы.
JSON блок используется внутренне — пользователю не показывается.
"""
import json
import re
from agents.base import BaseAgent
from storage.db import add_plan_items


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

СТРУКТУРА ОТВЕТА:

Сначала — читаемый план для человека (даты, темы, форматы, цели). Просто текст без таблиц.

В самом конце — технический блок (его увидит только система, не пользователь):
```json
[{{"topic": "Тема", "description": "Суть поста до 80 символов", "platform": "telegram", "scheduled": "{today}"}}]
```

JSON должен содержать все посты. scheduled — реальная дата YYYY-MM-DD."""

    def run(self, user_message: str, history: list[dict] = None) -> str:
        response = super().run(user_message, history)

        # Извлекаем JSON и сохраняем в БД — но убираем из ответа пользователю
        if "```json" in response:
            try:
                json_block = response.split("```json")[1].split("```")[0].strip()
                items = json.loads(json_block)
                if isinstance(items, list) and items:
                    add_plan_items(items)
            except Exception:
                pass
            # Скрываем JSON блок от пользователя
            response = re.sub(r"```json.*?```", "", response, flags=re.DOTALL).strip()

        return response
