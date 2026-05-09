"""
Базовый класс для всех агентов.
Каждый агент — это Claude с особым системным промптом и набором инструментов.
"""
from __future__ import annotations
import time
import logging
import anthropic
from config import (
    ANTHROPIC_API_KEY, MODEL,
    BRAND_NICHE, BRAND_TONE, BRAND_LANGUAGE, BRAND_AUDIENCE,
    BRAND_NAME, BRAND_TAGLINE, BRAND_WEBSITE, BRAND_STAGE,
    BRAND_PRODUCT, BRAND_POSITIONING,
)
from storage.db import get_all_brand

logger = logging.getLogger(__name__)


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

        # Фолбэк — полный встроенный контекст Sanda из config
        return f"""БРЕНД: {BRAND_NAME}
СЛОГАН: {BRAND_TAGLINE}
САЙТ: {BRAND_WEBSITE}
СТАДИЯ: {BRAND_STAGE}

ПРОДУКТ:
{BRAND_PRODUCT}

АУДИТОРИЯ:
{BRAND_AUDIENCE}

ПОЗИЦИОНИРОВАНИЕ:
{BRAND_POSITIONING}

ТОН И ГОЛОС БРЕНДА:
{BRAND_TONE}

НИША: {BRAND_NICHE}
ЯЗЫК: {BRAND_LANGUAGE}""".strip()

    def _telegram_rules(self) -> str:
        """Правила форматирования для Telegram — применяются ко всем агентам."""
        return """
ПРАВИЛА ОБЩЕНИЯ В TELEGRAM (строго обязательно):

1. Пиши как живой человек, не как инструмент. Короткие абзацы, разговорный тон.

2. ЗАПРЕЩЕНО использовать:
   — Markdown-таблицы (| col | col |) — в Telegram не отображаются
   — Горизонтальные линии (--- или ===)
   — HTML-теги
   — Заголовки с # (# Заголовок) — выглядят как обычный текст со значком
   — Вложенные списки с отступами

3. РАЗРЕШЕНО:
   — *жирный* текст для выделения важного
   — _курсив_ для подзаголовков или акцентов
   — `код` для терминов, команд, цифр
   — Списки через дефис (- пункт) или цифры (1. пункт)
   — Эмодзи для структуры — умеренно

4. Если нужна таблица — замени её структурированным текстом:
   Вместо таблицы пиши блоками:
   *Название:* значение
   *Другое:* значение

5. Если пользователь явно просит таблицу — скажи что создашь её в Google Sheets
   и сделай это через инструменты (не рисуй таблицу текстом).

6. Длинный ответ — разбивай на абзацы через пустую строку. Не стены текста.
"""

    def _system_prompt(self) -> str:
        raise NotImplementedError

    def _full_system_prompt(self) -> str:
        """Системный промпт агента + правила Telegram."""
        return self._system_prompt() + "\n" + self._telegram_rules()

    def run(self, user_message: str, history: list[dict] = None) -> str:
        """
        Вызывает агента и возвращает текстовый ответ.
        history — список {'role': 'user'|'assistant', 'content': '...'} из БД.
        При ошибке 529 (overloaded) — автоматически повторяет до 3 раз.
        """
        messages = []
        if history:
            for h in history[-8:]:
                messages.append({"role": h["role"], "content": h["content"]})
        messages.append({"role": "user", "content": user_message})

        max_retries = 3
        retry_delays = [10, 30, 60]

        for attempt in range(max_retries):
            try:
                response = self.client.messages.create(
                    model=MODEL,
                    max_tokens=2048,
                    system=self._full_system_prompt(),
                    messages=messages,
                )
                return response.content[0].text

            except anthropic.APIStatusError as e:
                if e.status_code == 529 and attempt < max_retries - 1:
                    wait = retry_delays[attempt]
                    logger.warning(f"[{self.name}] API перегружен (529), жду {wait}с... (попытка {attempt+1}/{max_retries})")
                    time.sleep(wait)
                    continue
                raise

            except anthropic.APIConnectionError as e:
                if attempt < max_retries - 1:
                    wait = retry_delays[attempt]
                    logger.warning(f"[{self.name}] Ошибка соединения, жду {wait}с...")
                    time.sleep(wait)
                    continue
                raise
