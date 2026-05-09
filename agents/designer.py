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
- Акцентный цвет: мятный #3be8b0
- Минимализм, glassmorphism
- Реальные люди или абстрактные финансовые метафоры
- НЕ рисуй интерфейс приложения, экраны с UI, скриншоты

ФОРМАТ ОТВЕТА — строго два блока:

IMAGE_PROMPT: [промпт на английском, одна строка. Lifestyle сцена казахстанца с телефоном, или абстрактная финансовая метафора, или тенге/деньги. Стиль: dark cinematic, mint green accent light, no fake app UI, no text in image]

CONCEPT: [2-3 предложения на русском — что изображено и почему это работает для поста]

Больше ничего не пиши — только эти два блока."""

    def _generate_via_ideogram(self, prompt: str) -> tuple[bytes | None, str]:
        api_key = os.getenv("IDEOGRAM_API_KEY", "")
        if not api_key:
            return None, "IDEOGRAM_API_KEY не задан в Railway Variables"
        try:
            full_prompt = f"{prompt}, dark background, mint green #3be8b0 accent, minimalist fintech, high quality, professional"
            resp = requests.post(
                IDEOGRAM_API_URL,
                headers={"Api-Key": api_key, "Content-Type": "application/json"},
                json={"image_request": {"prompt": full_prompt, "aspect_ratio": "ASPECT_1_1", "model": "V_2", "magic_prompt_option": "AUTO"}},
                timeout=60,
            )
            resp.raise_for_status()
            image_url = resp.json()["data"][0]["url"]
            img_resp = requests.get(image_url, timeout=30)
            img_resp.raise_for_status()
            return img_resp.content, ""
        except requests.HTTPError as e:
            return None, f"Ideogram ошибка {e.response.status_code}"
        except Exception as e:
            return None, str(e)

    def _generate_via_pollinations(self, prompt: str) -> tuple[bytes | None, str]:
        try:
            full_prompt = f"{prompt}, dark background, mint green accent, minimalist fintech, no text, no UI mockups"
            encoded = requests.utils.quote(full_prompt)
            url = f"https://image.pollinations.ai/prompt/{encoded}?width=1080&height=1080&nologo=true&seed={int(time.time())}"
            resp = requests.get(url, timeout=60)
            resp.raise_for_status()
            if resp.headers.get("content-type", "").startswith("image/"):
                return resp.content, ""
            return None, "Не удалось получить изображение"
        except Exception as e:
            return None, str(e)

    def run(self, user_message: str, history: list[dict] = None) -> str:
        raw = super().run(user_message, history)

        # Извлекаем промпт и концепцию — пользователю не показываем
        prompt_match = re.search(r"IMAGE_PROMPT:\s*(.+?)(?:\n|$)", raw)
        concept_match = re.search(r"CONCEPT:\s*(.+?)(?:\n\n|$)", raw, re.DOTALL)

        image_prompt = prompt_match.group(1).strip() if prompt_match else user_message
        concept = concept_match.group(1).strip() if concept_match else ""

        # Генерируем изображение
        use_ideogram = bool(os.getenv("IDEOGRAM_API_KEY"))
        if use_ideogram:
            image_bytes, err = self._generate_via_ideogram(image_prompt)
        else:
            image_bytes, err = self._generate_via_pollinations(image_prompt)

        if not image_bytes:
            return f"Не получилось сгенерировать изображение: {err}"

        # Загружаем на Drive или даём прямую ссылку
        if is_drive_enabled():
            filename = f"sanda_{int(time.time())}.png"
            link = upload_image(image_bytes, filename)
            if link.startswith("http"):
                result = f"Готово 🎨\n\n{concept}\n\n[Открыть изображение]({link})"
                save_draft(body=result, title=f"Визуал: {user_message[:50]}", agent="designer", visual_prompt=link)
                return result
            else:
                return f"Изображение создано, но не удалось загрузить на Drive: {link}\n\n{concept}"
        else:
            encoded = requests.utils.quote(image_prompt + ", dark background, mint green accent, minimalist fintech, no text")
            link = f"https://image.pollinations.ai/prompt/{encoded}?width=1080&height=1080&nologo=true"
            return f"Готово 🎨\n\n{concept}\n\n[Посмотреть изображение]({link})\n\n_Чтобы сохранять на Google Drive — добавь GOOGLE\\_DRIVE\\_FOLDER\\_ID в Railway_"
