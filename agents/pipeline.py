"""
Пайплайн — цепочка агентов, которые работают вместе над одной задачей.
Каждый агент получает результат предыдущего как контекст.
"""
import logging
from agents.analyst import AnalystAgent
from agents.strategist import StrategistAgent
from agents.copywriter import CopywriterAgent
from agents.designer import DesignerAgent
from storage.db import save_draft

logger = logging.getLogger(__name__)


class ContentPipeline:
    """
    Полный цикл создания контента:
    Аналитик → Стратег → Копирайтер → Дизайнер
    """

    def __init__(self):
        self.analyst    = AnalystAgent()
        self.strategist = StrategistAgent()
        self.copywriter = CopywriterAgent()
        self.designer   = DesignerAgent()

    def run(self, topic: str, progress_cb=None) -> dict:
        """
        Запускает полный пайплайн.
        progress_cb(step, text) — коллбэк для отправки промежуточных результатов.
        Возвращает dict со всеми результатами и draft_id.
        """
        results = {}

        # ── Шаг 1: Аналитик исследует тему ──────────────────────
        logger.info(f"[Pipeline] Шаг 1: Аналитик → '{topic}'")
        if progress_cb:
            progress_cb("analyst", "🔍 *Аналитик* исследует тему...")

        analyst_prompt = (
            f"Исследуй тему для контент-маркетинга: «{topic}»\n"
            f"Дай краткий анализ: ключевые боли аудитории, актуальные углы подачи, "
            f"что уже есть у конкурентов и чего не хватает. "
            f"Максимум 200 слов — только самое важное для написания поста."
        )
        analyst_result = self.analyst.run(analyst_prompt)
        results["analyst"] = analyst_result
        logger.info(f"[Pipeline] Аналитик завершил: {analyst_result[:100]}...")

        # ── Шаг 2: Стратег определяет угол и формат ─────────────
        logger.info(f"[Pipeline] Шаг 2: Стратег → определяет структуру")
        if progress_cb:
            progress_cb("strategist", "📋 *Стратег* определяет угол и структуру...")

        strategist_prompt = (
            f"Тема поста: «{topic}»\n\n"
            f"Данные от аналитика:\n{analyst_result}\n\n"
            f"На основе этого определи:\n"
            f"1. Лучший угол подачи (что зацепит аудиторию)\n"
            f"2. Структуру поста (как построить)\n"
            f"3. Главный месседж (одна фраза)\n"
            f"4. Призыв к действию\n"
            f"Кратко, только по делу — это ТЗ для копирайтера."
        )
        strategist_result = self.strategist.run(strategist_prompt)
        results["strategist"] = strategist_result
        logger.info(f"[Pipeline] Стратег завершил: {strategist_result[:100]}...")

        # ── Шаг 3: Копирайтер пишет пост ────────────────────────
        logger.info(f"[Pipeline] Шаг 3: Копирайтер → пишет текст")
        if progress_cb:
            progress_cb("copywriter", "✍️ *Копирайтер* пишет текст...")

        copywriter_prompt = (
            f"Напиши пост для Telegram-канала на тему: «{topic}»\n\n"
            f"ТЗ от стратега:\n{strategist_result}\n\n"
            f"Требования: живой язык, никакого канцелярита, "
            f"абзацы по 2-3 строки, эмодзи как разделители. "
            f"В конце хэштеги и призыв к действию."
        )
        # Не используем автосохранение копирайтера — сохраним сами со всеми данными
        copywriter_result = CopywriterAgent().run(copywriter_prompt)
        # Убираем строку автосохранения если она добавилась
        if "💾 *Черновик сохранён*" in copywriter_result:
            copywriter_result = copywriter_result.split("💾 *Черновик сохранён*")[0].strip()
        results["copywriter"] = copywriter_result
        logger.info(f"[Pipeline] Копирайтер завершил: {copywriter_result[:100]}...")

        # ── Шаг 4: Дизайнер создаёт промпт для визуала ──────────
        logger.info(f"[Pipeline] Шаг 4: Дизайнер → создаёт промпт")
        if progress_cb:
            progress_cb("designer", "🎨 *Дизайнер* придумывает визуал...")

        designer_prompt = (
            f"Создай промпт для генерации изображения к посту на тему: «{topic}»\n\n"
            f"Текст поста:\n{copywriter_result[:300]}...\n\n"
            f"Дай промпт для DALL-E и Midjourney. "
            f"Стиль: профессиональный B2B, чистый минимализм."
        )
        designer_result = self.designer.run(designer_prompt)
        results["designer"] = designer_result
        logger.info(f"[Pipeline] Дизайнер завершил: {designer_result[:100]}...")

        # ── Сохраняем всё в БД ───────────────────────────────────
        draft_id = save_draft(
            body=copywriter_result,
            title=topic[:80],
            agent="pipeline",
            visual_prompt=designer_result,
        )
        results["draft_id"] = draft_id
        logger.info(f"[Pipeline] Черновик сохранён: draft_id={draft_id}")

        return results
