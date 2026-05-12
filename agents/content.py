"""
ContentAgent — единственный агент.
Принимает запрос, генерирует контент-план с полными текстами постов,
возвращает список словарей готовых к записи в Sheets.
"""
import json
import logging
from datetime import date
from agents.base import BaseAgent

logger = logging.getLogger(__name__)


class ContentAgent(BaseAgent):
    name = "content"
    emoji = "✍️"

    def _system_prompt(self) -> str:
        today = date.today().isoformat()
        brand = self._brand_context()
        return f"""Ты — контент-менеджер финтех-стартапа Sanda (sandawallet.kz).
Sanda — B2C приложение личных финансов для казахстанцев 22–35 лет.
Сегодня: {today}

БРЕНД-КОНТЕКСТ:
{brand}

ТВОЯ ЗАДАЧА:
Создавай контент-план с ПОЛНЫМИ, ГОТОВЫМИ К ПУБЛИКАЦИИ текстами постов.
Никаких заготовок и плейсхолдеров — только реальные тексты.

ПРАВИЛА ТЕКСТОВ:
✅ Живой разговорный стиль, как пишет умный друг
✅ Нейтральное обращение: "Ты замечал?" не "Ты знал?"
✅ Конкретные цифры в тенге (₸), реальные ситуации казахстанцев
✅ Один пост — одна мысль, 400–700 символов для Telegram
✅ CTA: sandawallet.kz или вопрос к аудитории
❌ Без длинных тире — используй запятую или новое предложение
❌ Без шаблона "Не X. А Y."
❌ Без Kaspi — пиши "банковская рассрочка"
❌ Без телеграфных рубленых фраз "Нажал. Готово. Всё."

ФОРМАТЫ (чередуй разные):
- Финансовый лайфхак с конкретным советом
- История узнавания (читатель думает "это про меня")
- Вовлекающий вопрос или опрос
- Фича Sanda с пользой для читателя
- Мотивация и финансовые привычки

ВЕРНИ СТРОГО ТОЛЬКО JSON-МАССИВ (без markdown, без слов до и после):
[
  {{
    "date": "YYYY-MM-DD",
    "time": "HH:MM",
    "platform": "Telegram",
    "topic": "Тема поста одной строкой",
    "text": "Полный текст поста. Заголовок + тело + CTA. Хэштеги в конце.",
    "status": "Черновик"
  }}
]

Выбирай время публикации реалистично: вт-чт 9:00–10:00 или 18:00–20:00, пн 9:00, пт 17:00.
JSON и только JSON."""

    def generate(self, user_request: str) -> list[dict]:
        """Генерирует контент-план, возвращает список постов."""
        raw = self.run(user_request)

        # Убираем возможные markdown-обёртки
        clean = raw.strip()
        if "```" in clean:
            parts = clean.split("```")
            for part in parts:
                part = part.strip()
                if part.startswith("json"):
                    part = part[4:].strip()
                if part.startswith("["):
                    clean = part
                    break

        # Если LLM добавил текст до/после JSON
        start = clean.find("[")
        end = clean.rfind("]")
        if start != -1 and end != -1:
            clean = clean[start:end+1]

        try:
            posts = json.loads(clean)
        except json.JSONDecodeError as e:
            logger.error(f"[ContentAgent] JSON parse error: {e}\nRaw: {raw[:500]}")
            raise ValueError(f"Не удалось разобрать ответ агента: {e}")

        # Нормализация полей
        for i, post in enumerate(posts):
            post.setdefault("status", "Черновик")
            post.setdefault("time", "10:00")
            post.setdefault("platform", "Telegram")

        logger.info(f"[ContentAgent] Сгенерировано {len(posts)} постов")
        return posts
