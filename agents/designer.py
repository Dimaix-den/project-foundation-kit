"""
Агент-дизайнер: генерирует изображения через Ideogram API или Pollinations,
отправляет напрямую в Telegram (без Google Drive).
"""
import os
import re
import time
import logging
import tempfile
import requests
from agents.base import BaseAgent
from storage.db import save_draft

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
- Акцентный цвет: мятный #3be8b0
- Минимализм, lifestyle-фотография
- Реальные люди (казахстанцы с телефоном, кошельком, в кафе/дома) или абстрактные финансовые метафоры
- НЕ рисуй интерфейс приложения, экраны с UI, скриншоты, фейковые мобильные интерфейсы

ТВОЙ ОТВЕТ — строго два блока, ничего лишнего:

IMAGE_PROMPT: [промпт на английском, одна строка. Конкретная lifestyle-сцена или абстрактная метафора. Пример: "Young Kazakh woman in cozy apartment checking finances on phone, dark moody lighting, mint green accent, cinematic, no UI mockups"]

CONCEPT: [2-3 предложения на русском — что изображено и почему это работает для поста]

Только эти два блока. Больше ничего."""

    def _generate_via_ideogram(self, prompt: str) -> tuple:
        api_key = os.getenv("IDEOGRAM_API_KEY", "")
        if not api_key:
            return None, "IDEOGRAM_API_KEY не задан"
        try:
            full_prompt = (
                f"{prompt}, dark background, mint green #3be8b0 accent light, "
                "minimalist fintech aesthetic, high quality, cinematic lighting, "
                "no fake phone UI, no text overlays"
            )
            resp = requests.post(
                IDEOGRAM_API_URL,
                headers={"Api-Key": api_key, "Content-Type": "application/json"},
                json={
                    "image_request": {
                        "prompt": full_prompt,
                        "aspect_ratio": "ASPECT_1_1",
                        "model": "V_2",
                        "magic_prompt_option": "AUTO",
                    }
                },
                timeout=90,
            )
            resp.raise_for_status()
            data = resp.json()
            image_url = data["data"][0]["url"]
            img_resp = requests.get(image_url, timeout=60)
            img_resp.raise_for_status()
            return img_resp.content, ""
        except requests.HTTPError as e:
            return None, f"Ideogram ошибка {e.response.status_code}: {e.response.text[:200]}"
        except Exception as e:
            return None, str(e)

    def _generate_via_pollinations(self, prompt: str) -> tuple:
        """Fallback: Pollinations.ai — только английский промпт."""
        try:
            has_cyrillic = bool(re.search(r'[а-яА-Я]', prompt))
            if has_cyrillic:
                prompt = "Young person managing finances on smartphone, dark moody background, mint green light accent, cinematic lifestyle"

            full_prompt = f"{prompt}, dark background, mint green accent, minimalist, high quality, no UI mockups, no text"
            encoded = requests.utils.quote(full_prompt)
            url = f"https://image.pollinations.ai/prompt/{encoded}?width=1080&height=1080&nologo=true&seed={int(time.time())}"
            resp = requests.get(url, timeout=90, stream=True)
            resp.raise_for_status()
            if "image" in resp.headers.get("content-type", ""):
                return resp.content, ""
            return None, f"Неожиданный content-type: {resp.headers.get('content-type')}"
        except Exception as e:
            return None, str(e)

    def run(self, user_message: str, history: list[dict] = None) -> str:
        # Получаем от Claude промпт и концепцию
        raw = super().run(user_message, history)

        # Извлекаем IMAGE_PROMPT
        prompt_match = re.search(r"\*{0,2}IMAGE_PROMPT\*{0,2}:\s*(.+?)(?:\n|$)", raw, re.IGNORECASE)
        concept_match = re.search(r"\*{0,2}CONCEPT\*{0,2}:\s*(.+?)(?:\n\n|\Z)", raw, re.IGNORECASE | re.DOTALL)

        image_prompt = prompt_match.group(1).strip() if prompt_match else ""
        concept = concept_match.group(1).strip() if concept_match else ""

        # Если нет English промпта — дефолтный
        if not image_prompt or re.search(r'[а-яА-Я]', image_prompt):
            logger.warning(f"[Designer] IMAGE_PROMPT не найден или кириллица, использую дефолтный")
            image_prompt = "Young Kazakh person managing personal finances on smartphone, cozy home setting, dark cinematic lighting, mint green accent, lifestyle photography"

        # Генерируем изображение
        use_ideogram = bool(os.getenv("IDEOGRAM_API_KEY"))
        if use_ideogram:
            image_bytes, err = self._generate_via_ideogram(image_prompt)
            if not image_bytes:
                logger.warning(f"[Designer] Ideogram failed: {err}, пробую Pollinations")
                image_bytes, err = self._generate_via_pollinations(image_prompt)
        else:
            image_bytes, err = self._generate_via_pollinations(image_prompt)

        if not image_bytes:
            # Fallback: возвращаем прямую ссылку на Pollinations
            encoded = requests.utils.quote(image_prompt + ", dark background, mint green accent, minimalist fintech, no text")
            link = f"https://image.pollinations.ai/prompt/{encoded}?width=1080&height=1080&nologo=true"
            return f"Готово 🎨\n\n{concept}\n\n[Посмотреть изображение]({link})"

        # Сохраняем во временный файл — handler.py отправит как фото в Telegram
        try:
            tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False, dir="/tmp")
            tmp.write(image_bytes)
            tmp.close()
            save_draft(
                body=concept,
                title=f"Визуал: {user_message[:50]}",
                agent="designer",
                visual_prompt=image_prompt,
            )
            return f"Готово 🎨\n\n{concept}\n[IMAGE_FILE:{tmp.name}]"
        except Exception as e:
            logger.warning(f"[Designer] Не удалось сохранить файл: {e}")
            encoded = requests.utils.quote(image_prompt + ", dark background, mint green accent, minimalist fintech, no text")
            link = f"https://image.pollinations.ai/prompt/{encoded}?width=1080&height=1080&nologo=true"
            return f"Готово 🎨\n\n{concept}\n\n[Посмотреть изображение]({link})"
