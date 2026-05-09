"""
Агент-дизайнер: генерирует изображения через Ideogram API,
загружает на Google Drive, возвращает ссылку.
"""
import os
import re
import time
import logging
import requests
from agents.base import BaseAgent
from storage.db import save_draft
from storage.drive import upload_image, is_drive_enabled

logger = logging.getLogger(__name__)

IDEOGRAM_API_URL = "https://api.ideogram.ai/generate"


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
- Придумывать визуальную концепцию поста
- Генерировать изображение через Ideogram
- Загружать на Google Drive и прикреплять ссылку

ФОРМАТ ОТВЕТА — строго:

🎨 Концепция: (что изображено, 1-2 предложения)

IMAGE_PROMPT: [промпт на английском, одна строка, детальный. Всегда включай: dark background, mint green #3be8b0 accent, minimalist fintech style, Kazakhstan, no text]

🎭 Стиль: (рекомендации по цвету и настроению)

Отвечай на том же языке, на котором к тебе обращаются."""

    def _generate_via_ideogram(self, prompt: str) -> tuple[bytes | None, str]:
        """Генерирует изображение через Ideogram API."""
        api_key = os.getenv("IDEOGRAM_API_KEY", "")
        if not api_key:
            return None, "IDEOGRAM_API_KEY не задан в Railway Variables"

        try:
            full_prompt = (
                f"{prompt}, dark background, mint green #3be8b0 accent color, "
                f"minimalist fintech design, modern mobile app aesthetic, "
                f"high quality, professional"
            )

            resp = requests.post(
                IDEOGRAM_API_URL,
                headers={
                    "Api-Key": api_key,
                    "Content-Type": "application/json",
                },
                json={
                    "image_request": {
                        "prompt": full_prompt,
                        "aspect_ratio": "ASPECT_1_1",
                        "model": "V_2",
                        "magic_prompt_option": "AUTO",
                    }
                },
                timeout=60,
            )
            resp.raise_for_status()
            data = resp.json()

            image_url = data["data"][0]["url"]
            logger.info(f"[Designer] Ideogram сгенерировал: {image_url[:80]}")

            # Скачиваем байты изображения
            img_resp = requests.get(image_url, timeout=30)
            img_resp.raise_for_status()
            return img_resp.content, ""

        except requests.HTTPError as e:
            return None, f"Ideogram API ошибка {e.response.status_code}: {e.response.text[:200]}"
        except KeyError:
            return None, "Ideogram вернул неожиданный формат ответа"
        except Exception as e:
            return None, str(e)

    def run(self, user_message: str, history: list[dict] = None) -> str:
        # Получаем концепцию и промпт от Claude
        response = super().run(user_message, history)

        # Извлекаем IMAGE_PROMPT
        match = re.search(r"IMAGE_PROMPT:\s*(.+?)(?:\n|$)", response)
        if not match:
            return response

        image_prompt = match.group(1).strip()
        logger.info(f"[Designer] Промпт: {image_prompt[:100]}")

        # Проверяем наличие API ключа
        if not os.getenv("IDEOGRAM_API_KEY"):
            response += (
                "\n\n⚠️ *IDEOGRAM\\_API\\_KEY не задан*\n"
                "Добавь ключ в Railway Variables → Deploy → и попробуй снова.\n"
                "Получить ключ: ideogram.ai → Settings → API"
            )
            return response

        response += "\n\n⏳ _Генерирую изображение через Ideogram..._"

        image_bytes, err = self._generate_via_ideogram(image_prompt)

        if not image_bytes:
            response += f"\n⚠️ Ошибка генерации: {err}"
            return response

        size_kb = len(image_bytes) // 1024
        response += f"\n✅ _Изображение готово ({size_kb} KB)_"

        # Загружаем на Google Drive
        if is_drive_enabled():
            filename = f"sanda_{int(time.time())}.png"
            drive_link = upload_image(image_bytes, filename)
            if drive_link.startswith("http"):
                response += f"\n📁 [Открыть на Google Drive]({drive_link})"
                save_draft(
                    body=response,
                    title=f"Визуал: {user_message[:50]}",
                    agent="designer",
                    visual_prompt=drive_link,
                )
            else:
                response += f"\n{drive_link}"
        else:
            response += (
                "\n💡 _Google Drive не подключён — добавь GOOGLE\\_DRIVE\\_FOLDER\\_ID в Railway "
                "чтобы картинки сохранялись автоматически_"
            )

        return response
