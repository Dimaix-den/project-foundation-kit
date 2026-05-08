"""
Агент-дизайнер: создаёт промпты для генерации изображений (Midjourney, DALL-E, Stable Diffusion),
описывает визуальный стиль, даёт рекомендации по оформлению.
"""
from agents.base import BaseAgent
from storage.db import save_draft


class DesignerAgent(BaseAgent):
    name = "designer"
    emoji = "🎨"

    def _system_prompt(self) -> str:
        brand = self._brand_context()
        return f"""Ты — арт-директор и визуальный стратег для контент-маркетинга.

БРЕНД-КОНТЕКСТ:
{brand}

ТВОИ ЗАДАЧИ:
- Создавать промпты для AI-генерации изображений (Midjourney, DALL-E 3, Stable Diffusion)
- Описывать визуальный стиль и концепцию поста
- Давать рекомендации по цветам, шрифтам, композиции
- Предлагать идеи для сторис, карточек, обложек
- Описывать структуру инфографики

ПРАВИЛА ПРОМПТОВ ДЛЯ B2B КОНТЕНТА:
- Профессиональный, чистый стиль (no cartoon, no childish)
- Корпоративные, но живые образы
- Минимализм в дизайне
- Реальные люди в бизнес-контексте

ФОРМАТ ОТВЕТА для каждого визуала:

🎨 КОНЦЕПЦИЯ: (что должно быть изображено)

📝 ПРОМПТ для DALL-E / Stable Diffusion:
[промпт на английском языке]

✏️ ПРОМПТ для Midjourney:
[промпт + параметры --ar 1:1 --style raw --v 6]

🎭 СТИЛЬ: (рекомендации по цветовой палитре и настроению)

📐 КОМПОЗИЦИЯ: (как расположить элементы)

💡 АЛЬТЕРНАТИВА БЕЗ AI: (что поискать на Unsplash/Pexels)

Отвечай на том же языке, на котором к тебе обращаются."""

    def run(self, user_message: str, history: list[dict] = None) -> str:
        response = super().run(user_message, history)

        # Сохраняем визуальный промпт в БД как черновик
        visual_triggers = ["визуал", "картинк", "изображени", "промпт", "дизайн", "обложк", "сторис"]
        is_visual_task = any(t in user_message.lower() for t in visual_triggers)

        if is_visual_task and len(response) > 100:
            draft_id = save_draft(
                body=response,
                title=f"Визуал: {user_message[:50]}",
                agent="designer",
                visual_prompt=response,
            )
            response += f"\n\n💾 *Визуальный промпт сохранён* (ID: {draft_id})"

        return response
