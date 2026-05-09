"""
Куратор — главный менеджер-агент.

Принимает любую задачу на естественном языке, составляет план выполнения,
динамически вызывает нужных агентов в нужном порядке и собирает финальный результат.

Отличие от простого оркестратора: не просто роутит к одному агенту,
а планирует многошаговое выполнение с передачей контекста между агентами.
"""
import json
import time
import logging
import anthropic
from config import ANTHROPIC_API_KEY, MODEL
from agents.base import BaseAgent
from agents.analyst import AnalystAgent
from agents.strategist import StrategistAgent
from agents.copywriter import CopywriterAgent
from agents.designer import DesignerAgent
from agents.publisher import PublisherAgent
from storage.db import save_draft

logger = logging.getLogger(__name__)

AGENTS = {
    "analyst":    AnalystAgent(),
    "strategist": StrategistAgent(),
    "copywriter": CopywriterAgent(),
    "designer":   DesignerAgent(),
    "publisher":  PublisherAgent(),
}

AGENT_INFO = """
- analyst: исследует рынок, тренды, конкурентов, аудиторию. Умеет искать в интернете.
- strategist: создаёт контент-планы, рубрики, структуру, углы подачи.
- copywriter: пишет тексты — посты, статьи, тезисы, подписи. Знает форматы разных платформ.
- designer: создаёт промпты для генерации изображений (Midjourney, DALL-E), описывает визуальный стиль.
- publisher: управляет черновиками, статусами, расписанием публикаций.
"""

PLANNING_SYSTEM = f"""Ты — куратор контент-команды. Твоя задача: получить задачу и составить план её выполнения.

ДОСТУПНЫЕ АГЕНТЫ:
{AGENT_INFO}

Ответь ТОЛЬКО валидным JSON в следующем формате (без markdown, без пояснений):
{{
  "task_summary": "краткое описание задачи в 1 предложении",
  "steps": [
    {{
      "agent": "имя агента",
      "instruction": "точная инструкция для агента что именно сделать",
      "use_previous": true/false,
      "output_label": "как назвать результат этого шага"
    }}
  ],
  "final_format": "описание финального результата для пользователя"
}}

Правила:
- use_previous: true означает что агент получит результаты предыдущих шагов как контекст
- Включай только нужных агентов — не все сразу
- Максимум 4 шага
- Инструкции пиши на русском, чётко и конкретно

Примеры задач и планов:

Задача: "пост в Threads про финансовые привычки"
{{
  "task_summary": "Написать пост для Threads про финансовые привычки",
  "steps": [
    {{"agent": "copywriter", "instruction": "Напиши пост для Threads (до 500 символов, без хэштегов, разговорный тон) про финансовые привычки которые меняют жизнь", "use_previous": false, "output_label": "Текст поста"}},
    {{"agent": "designer", "instruction": "Создай промпт для визуала к посту про финансовые привычки. Стиль: минимализм, тёмный фон.", "use_previous": true, "output_label": "Промпт для визуала"}}
  ],
  "final_format": "Готовый пост для Threads + промпт для картинки"
}}

Задача: "контент-план на неделю"
{{
  "task_summary": "Создать контент-план на неделю",
  "steps": [
    {{"agent": "analyst", "instruction": "Найди 3-5 актуальных тренда и болей аудитории по теме личных финансов в Казахстане. Коротко.", "use_previous": false, "output_label": "Тренды и инсайты"}},
    {{"agent": "strategist", "instruction": "Создай контент-план на 7 дней (пн-вс) с темами постов. Используй данные аналитика. Для каждого дня: тема, формат, цель.", "use_previous": true, "output_label": "Контент-план"}}
  ],
  "final_format": "Контент-план на неделю с темами и форматами"
}}"""


class CuratorAgent:
    """
    Куратор — планирует и координирует работу агентов.
    """

    def __init__(self):
        self.client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    def _plan(self, task: str) -> dict:
        """Составляет план выполнения задачи. Retry при 529."""
        max_retries = 3
        retry_delays = [10, 30, 60]

        for attempt in range(max_retries):
            try:
                response = self.client.messages.create(
                    model=MODEL,
                    max_tokens=1024,
                    system=PLANNING_SYSTEM,
                    messages=[{"role": "user", "content": f"Задача: {task}"}],
                )
                break
            except anthropic.APIStatusError as e:
                if e.status_code == 529 and attempt < max_retries - 1:
                    wait = retry_delays[attempt]
                    logger.warning(f"[Curator] API перегружен (529), жду {wait}с...")
                    time.sleep(wait)
                else:
                    raise

        raw = response.content[0].text.strip()
        # Убираем markdown если Claude всё же добавил
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        return json.loads(raw)

    def run(self, task: str, progress_cb=None) -> dict:
        """
        Выполняет задачу: планирует → запускает агентов → собирает результат.

        progress_cb(step_label, text) — коллбэк для отправки статуса пользователю.
        Возвращает dict: {steps_results, plan, draft_id (если есть)}
        """
        # ── Шаг 0: Планирование ──────────────────────────────────
        logger.info(f"[Curator] Планирую задачу: {task[:80]}")
        if progress_cb:
            progress_cb("plan", "🧠 *Куратор* составляет план...")

        try:
            plan = self._plan(task)
        except (json.JSONDecodeError, Exception) as e:
            logger.error(f"[Curator] Ошибка планирования: {e}")
            # Фолбэк: отдать напрямую копирайтеру
            plan = {
                "task_summary": task,
                "steps": [{"agent": "copywriter", "instruction": task, "use_previous": False, "output_label": "Результат"}],
                "final_format": "Готовый контент"
            }

        logger.info(f"[Curator] План: {json.dumps(plan, ensure_ascii=False)[:300]}")

        agent_emojis = {
            "analyst": "🔍", "strategist": "📋",
            "copywriter": "✍️", "designer": "🎨", "publisher": "📅",
        }

        # ── Выполнение шагов ─────────────────────────────────────
        steps_results = []
        accumulated_context = ""

        for i, step in enumerate(plan.get("steps", [])):
            agent_name = step.get("agent", "copywriter")
            instruction = step.get("instruction", task)
            use_previous = step.get("use_previous", False)
            output_label = step.get("output_label", f"Шаг {i+1}")

            if agent_name not in AGENTS:
                agent_name = "copywriter"

            emoji = agent_emojis.get(agent_name, "🤖")
            logger.info(f"[Curator] Шаг {i+1}/{len(plan['steps'])}: {agent_name} → {instruction[:60]}")

            if progress_cb:
                progress_cb(
                    agent_name,
                    f"{emoji} *{agent_name.capitalize()}* работает над: _{output_label}_..."
                )

            # Добавляем контекст предыдущих шагов если нужно
            full_instruction = instruction
            if use_previous and accumulated_context:
                full_instruction = (
                    f"{instruction}\n\n"
                    f"---\nКОНТЕКСТ ОТ ПРЕДЫДУЩИХ ШАГОВ:\n{accumulated_context}"
                )

            agent = AGENTS[agent_name]

            # Для копирайтера — вызываем базовый run без автосохранения
            if agent_name == "copywriter":
                result = BaseAgent.run(agent, full_instruction)
                # Убираем строку автосохранения если есть
                if "💾 *Черновик сохранён*" in result:
                    result = result.split("💾 *Черновик сохранён*")[0].strip()
            else:
                result = agent.run(full_instruction)

            steps_results.append({
                "step": i + 1,
                "agent": agent_name,
                "label": output_label,
                "result": result,
            })

            # Накапливаем контекст для следующих шагов
            accumulated_context += f"\n\n[{output_label}]:\n{result[:600]}"
            logger.info(f"[Curator] Шаг {i+1} завершён: {result[:80]}...")

        # ── Сохранение черновика ──────────────────────────────────
        draft_id = None
        # Ищем результат копирайтера для сохранения
        copywriter_result = next(
            (s["result"] for s in steps_results if s["agent"] == "copywriter"), None
        )
        designer_result = next(
            (s["result"] for s in steps_results if s["agent"] == "designer"), None
        )

        if copywriter_result:
            draft_id = save_draft(
                body=copywriter_result,
                title=plan.get("task_summary", task)[:80],
                agent="curator",
                visual_prompt=designer_result or "",
            )
            logger.info(f"[Curator] Черновик сохранён: draft_id={draft_id}")

        return {
            "plan": plan,
            "steps_results": steps_results,
            "draft_id": draft_id,
            "final_format": plan.get("final_format", ""),
        }
