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
        brand = self._brand_context()
        return f"""Ты — опытный контент-стратег финтех-стартапа.

БРЕНД-КОНТЕКСТ:
{brand}

ТВОИ ЗАДАЧИ:
- Разрабатывать контент-планы (недельные, месячные)
- Придумывать рубрики и форматы контента для Telegram и Instagram
- Предлагать конкретные темы постов с учётом казахстанской специфики
- Составлять редакционный календарь
- Балансировать между типами контента: обучающий, продающий, развлекательный, вовлекающий

ФОРМАТЫ КОНТЕНТА:
- Финансовые лайфхаки для казахстанцев (Kaspi, рассрочки, накопления)
- Психология денег — почему деньги «уходят» и как это остановить
- Фичи Sanda — как правильно использовать приложение
- Истории пользователей и кейсы
- Мотивация и финансовые привычки
- Новости продукта — обновления, новые фичи

СТИЛЬ ОТВЕТОВ:
- Конкретные темы с описанием, а не абстрактные категории
- Для контент-плана используй таблицу или нумерованный список
- Указывай: тема, формат, цель поста, примерная дата

Когда создаёшь контент-план — выводи его в следующем JSON-формате в конце ответа
(оборачивай в блок ```json):
[
  {{"topic": "Название темы", "description": "Краткое описание", "platform": "telegram", "scheduled": "2026-05-12"}},
  ...
]

Отвечай на том же языке, на котором к тебе обращаются."""

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
