"""
Базовый класс для всех агентов.
Каждый агент — это Claude с особым системным промптом и набором инструментов.
"""
from __future__ import annotations
import anthropic
from config import ANTHROPIC_API_KEY, MODEL, BRAND_NICHE, BRAND_TONE, BRAND_LANGUAGE, BRAND_AUDIENCE
from storage.db import get_all_brand


class BaseAgent:
    name: str = "agent"
    emoji: str = "🤖"
    role_description: str = ""

    def __init__(self):
        self.client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    def _brand_context(self) -> str:
        """Достаёт брендовые настройки из БД (или дефолтные из config)."""
        brand = get_all_brand()

        # Если в БД есть полный контекст Sanda — используем его
        if brand.get("name") and brand.get("product_description"):
            return f"""
БРЕНД: {brand.get('name', 'Sanda')}
СЛОГАН: {brand.get('tagline', '')}
САЙТ: {brand.get('website', '')}
СТАДИЯ: {brand.get('stage', '')}

ПРОДУКТ:
{brand.get('product_description', '')}

АУДИТОРИЯ:
{brand.get('audience', '')}

ПОЗИЦИОНИРОВАНИЕ:
{brand.get('positioning', '')}

ВИЗУАЛЬНЫЙ СТИЛЬ:
{brand.get('visual_style', '')}

ТОН И ГОЛОС БРЕНДА:
{brand.get('tone', '')}

КОНТЕНТ-СТРАТЕГИЯ:
{brand.get('content_strategy', '')}

ДОПОЛНИТЕЛЬНО:
{brand.get('extra', '')}
""".strip()

        # Фолбэк на простые поля
        niche    = brand.get("niche",    BRAND_NICHE)
        tone     = brand.get("tone",     BRAND_TONE)
        language = brand.get("language", BRAND_LANGUAGE)
        audience = brand.get("audience", BRAND_AUDIENCE)
        extra    = brand.get("extra",    "")
        return (
            f"Ниша: {niche}\n"
            f"Тон: {tone}\n"
            f"Язык: {language}\n"
            f"Аудитория: {audience}\n"
            + (f"Доп. инфо о бренде: {extra}" if extra else "")
        )

    def _system_prompt(self) -> str:
        raise NotImplementedError

    def run(self, user_message: str, history: list[dict] = None) -> str:
        """
        Вызывает агента и возвращает текстовый ответ.
        history — список {'role': 'user'|'assistant', 'content': '...'} из БД.
        """
        messages = []
        if history:
            for h in history[-8:]:  # последние 8 сообщений контекста
                messages.append({"role": h["role"], "content": h["content"]})
        messages.append({"role": "user", "content": user_message})

        response = self.client.messages.create(
            model=MODEL,
            max_tokens=2048,
            system=self._system_prompt(),
            messages=messages,
        )
        return response.content[0].text
