"""
Агент-дизайнер: генерирует реальные изображения через Pollinations.ai (бесплатно, без API ключа),
загружает на Google Drive и возвращает ссылку.
"""
import re
import time
import logging
import requests
from agents.base import BaseAgent
from storage.db import save_draft
from storage.drive import upload_image, is_drive_enabled

logger = logging.getLogger(__name__)


class DesignerAgent(BaseAgent):
    name = "designer"
    emoji = "🎨"

    def _system_prompt(self) -> str:
        brand = self._brand_context()
        return f"""Ты — арт-директор финтех-стартапа Sanda.

БРЕНД-КОНТЕКСТ:
{brand}

ВИЗУАЛЬНЫЙ СТИЛЬ SANDA:
- Тёмный фон (#000 или тёмно-серый)
- Акцентный цвет: мятный/зелёный (#3be8b0)
- Минимализм, glassmorphism карточки
- Крупные цифры, clean typography
- Mobile-first, современный fintech UI

ТВОИ ЗАДАЧИ:
- Создавать промпты для генерации изображений
- Генерировать реальные картинки через Pollinations.ai
- Загружать их на Google Drive
- Описывать визуальную концепцию

ФОРМАТ ОТВЕТА — строго такой:

🎨 Концепция: (что изображено, 1-2 предложения)

IMAGE_PROMPT: [промпт на английском, 1 строка, без переносов, конкретный и детальный]

🎭 Стиль: (рекомендации по цвету, настроению)

Промпт для IMAGE_PROMPT пиши в стиле Sanda: dark background, mint green accent #3be8b0, minimalist fintech, clean UI, modern Kazakhstan...

Отвечай на том же языке, на котором к тебе обращаются."""

    def _generate_image(self, prompt: str) -> tuple[bytes | None, str]:
        """Генерирует изображение через Pollinations.ai."""
        try:
            # Добавляем стиль Sanda к промпту
            full_prompt = f"{prompt}, dark background, mint green accent, minimalist fintech design, clean modern UI, high quality"
            encoded = requests.utils.quote(full_prompt)
            url = f"https://image.pollinations.ai/prompt/{encoded}?width=1080&height=1080&nologo=true&seed={int(time.time())}"

            logger.info(f"[Designer] Генерирую изображение: {url[:100]}...")
            resp = requests.get(url, timeout=60)
            resp.raise_for_status()

            if resp.headers.get("content-type", "").startswith("image/"):
                return resp.content, ""
            return None, "Pollinations вернул не изображение"

        except requests.Timeout:
            return None, "Timeout — Pollinations не ответил за 60 секунд"
        except Exception as e:
            return None, str(e)

    def run(self, user_message: str, history: list[dict] = None) -> str:
        # Сначала получаем текстовый ответ с концепцией и промптом
        response = super().run(user_message, history)

        # Извлекаем IMAGE_PROMPT из ответа
        match = re.search(r"IMAGE_PROMPT:\s*(.+?)(?:\n|$)", response)
        if not match:
            return response

        image_prompt = match.group(1).strip()
        logger.info(f"[Designer] Промпт: {image_prompt[:80]}")

        # Генерируем изображение
        response += "\n\n⏳ _Генерирую изображение через Pollinations.ai..._"
        image_bytes, err = self._generate_image(image_prompt)

        if not image_bytes:
            response += f"\n⚠️ Не удалось сгенерировать: {err}"
            return response

        response += f"\n✅ _Изображение сгенерировано ({len(image_bytes)//1024} KB)_"

        # Загружаем на Google Drive
        if is_drive_enabled():
            filename = f"sanda_{int(time.time())}.png"
            drive_link = upload_image(image_bytes, filename)
            if drive_link.startswith("http"):
                response += f"\n📁 [Открыть на Google Drive]({drive_link})"
                # Сохраняем черновик со ссылкой
                save_draft(
                    body=response,
                    title=f"Визуал: {user_message[:50]}",
                    agent="designer",
                    visual_prompt=drive_link,
                )
            else:
                response += f"\n{drive_link}"
        else:
            # Drive не подключён — показываем прямую ссылку на картинку
            encoded = requests.utils.quote(image_prompt + ", dark background, mint green accent, minimalist fintech design")
            direct_url = f"https://image.pollinations.ai/prompt/{encoded}?width=1080&height=1080&nologo=true"
            response += f"\n🖼 [Посмотреть изображение]({direct_url})"
            response += "\n💡 _Подключи Google Drive чтобы сохранять картинки — добавь GOOGLE\\_DRIVE\\_FOLDER\\_ID в Railway_"

        return response
