"""
Агент-стратег: создаёт контент-планы, рубрики, редакционный календарь.
При создании контент-плана — автоматически сохраняет в БД и Google Sheets.
"""
import json
from agents.base import BaseAgent
from storage.db import add_plan_items, get_plan
from storage.sheets import write_content_plan, is_sheets_enabled


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

ТВОЯ ЗАДАЧА — сразу создавать готовый контент-план. Никогда не задавай уточняющих вопросов.
Если чего-то не указано — придумай сам: выбери даты, платформы, количество постов.
Действуй как опытный стратег который просто делает работу.

ФОРМАТЫ ПОСТОВ (используй все):
- Финансовые лайфхаки для казахстанцев (Kaspi, рассрочки, накопления)
- Психология денег — почему деньги «уходят»
- Фичи Sanda — как работает приложение
- Вовлекающие вопросы и опросы аудитории
- Мотивация и финансовые привычки
- Новости продукта

СТРУКТУРА ОТВЕТА — строго в таком порядке:

1. Краткий список постов (без таблиц, просто текстом):
   Для каждого поста: дата, платформа, тема, формат, цель

2. Сразу после — JSON-блок (обязательно, всегда):

```json
[
  {{"topic": "Тема поста", "description": "Что именно написать, главная мысль", "platform": "telegram", "scheduled": "{today}"}},
  ...
]
```

JSON должен содержать ВСЕ посты из плана. Поле scheduled — реальная дата в формате YYYY-MM-DD."""

    def run(self, user_message: str, history: list[dict] = None) -> str:
        response = super().run(user_message, history)

        # Автоматически сохраняем контент-план если агент его создал
        if "```json" in response:
            try:
                json_block = response.split("```json")[1].split("```")[0].strip()
                items = json.loads(json_block)
                if isinstance(items, list) and items:
                    # 1. Сохраняем в SQLite
                    ids = add_plan_items(items)
                    response += f"\n\n✅ *Сохранено в БД:* {len(ids)} тем"

                    # 2. Экспортируем в Google Sheets (если настроен)
                    if is_sheets_enabled():
                        sheets_result = write_content_plan(items)
                        response += f"\n{sheets_result}"
                    else:
                        response += "\n💡 _Подключи Google Sheets — отправь боту /sheets_setup_"

            except Exception:
                pass  # Если не удалось распарсить — просто показываем текст

        return response
