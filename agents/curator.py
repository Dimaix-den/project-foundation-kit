"""
Куратор — главный менеджер-агент.

Принимает любую задачу, составляет план, вызывает агентов по цепочке.
Если задача ссылается на «текущий контент-план» — подгружает его из БД
и передаёт копирайтеру как контекст.
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
from storage.db import save_draft, get_plan

logger = logging.getLogger(__name__)

AGENTS = {
    "analyst":    AnalystAgent(),
    "strategist": StrategistAgent(),
    "copywriter": CopywriterAgent(),
    "designer":   DesignerAgent(),
    "publisher":  PublisherAgent(),
}

AGENT_INFO = """
- analyst: исследует рынок, тренды, конкурентов, аудиторию.
- strategist: создаёт контент-планы. Автоматически сохраняет в БД.
- copywriter: пишет тексты — посты, статьи, подписи. Знает форматы разных платформ.
- designer: генерирует изображения (Ideogram/Pollinations). Возвращает готовую ссылку.
- publisher: записывает план в Google Sheets, управляет черновиками и публикацией.
"""

PLANNING_SYSTEM = f"""Ты — куратор контент-команды. Получи задачу и составь план.

ДОСТУПНЫЕ АГЕНТЫ:
{AGENT_INFO}

Ответь ТОЛЬКО валидным JSON (без markdown, без пояснений):
{{
  "task_summary": "краткое описание задачи",
  "steps": [
    {{
      "agent": "имя агента",
      "instruction": "точная инструкция на русском",
      "use_previous": true/false,
      "output_label": "название результата"
    }}
  ],
  "final_format": "описание финального результата"
}}

Правила:
- use_previous: true — агент получит результаты предыдущих шагов
- Максимум 4 шага, только нужные агенты
- Для дизайнера: instruction должна описывать ТЕМУ и настроение поста, НЕ просить написать промпт

Примеры:

Задача: "пост про финансовые привычки"
{{"task_summary":"Пост про финансовые привычки","steps":[
  {{"agent":"copywriter","instruction":"Напиши пост для Telegram (400-600 символов) про финансовые привычки казахстанцев. Заголовок + тело + CTA.","use_previous":false,"output_label":"Текст поста"}},
  {{"agent":"designer","instruction":"Визуал для поста про финансовые привычки. Тема: человек с телефоном, считает расходы. Тёмный фон, мятный акцент.","use_previous":false,"output_label":"Изображение"}}
],"final_format":"Пост + изображение"}}

Задача: "контент-план на неделю"
{{"task_summary":"Контент-план на неделю","steps":[
  {{"agent":"strategist","instruction":"Создай контент-план на 7 дней для Sanda. Темы, форматы, цели для каждого дня.","use_previous":false,"output_label":"Контент-план"}},
  {{"agent":"publisher","instruction":"Запиши контент-план в Google Sheets.","use_previous":false,"output_label":"Сохранено в таблицу"}}
],"final_format":"Контент-план + записан в Sheets"}}

Задача: "напишите тексты по текущему контент-плану" / "пропишите посты из плана"
{{"task_summary":"Написать тексты для всех постов из контент-плана","steps":[
  {{"agent":"copywriter","instruction":"Напиши полные тексты для КАЖДОГО поста из контент-плана (он будет в контексте). Для каждого: заголовок, подзаголовок, тело 300-500 символов, CTA. Разделяй посты линией ---","use_previous":true,"output_label":"Тексты постов"}},
  {{"agent":"designer","instruction":"Создай визуал для первого поста из плана. Lifestyle-сцена казахстанца с финансами. Тёмный фон, мятный акцент.","use_previous":false,"output_label":"Визуал для поста №1"}}
],"final_format":"Готовые тексты всех постов + изображение для первого"}}

Задача: "зафиксируй план в таблице"
{{"task_summary":"Записать план в Google Sheets","steps":[
  {{"agent":"publisher","instruction":"Запиши контент-план в Google Sheets.","use_previous":false,"output_label":"Сохранено в таблицу"}}
],"final_format":"План записан в Google Sheets"}}"""


# Ключевые слова, означающие «используй существующий план из БД»
_EXISTING_PLAN_KEYWORDS = [
    "текущий план", "текущий контент-план", "текущий контент план",
    "из плана", "по плану", "нравится план", "нравится контент-план",
    "тексты к постам", "тексты для постов", "тексты постов",
    "пропиши посты", "напиши посты", "напишите посты",
    "напишите тексты", "пропишите тексты",
]


class CuratorAgent:

    def __init__(self):
        self.client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    def _load_db_plan_context(self) -> str:
        """Загружает текущий контент-план из БД в читаемом виде."""
        items = get_plan("planned")
        if not items:
            return ""
        lines = ["ТЕКУЩИЙ КОНТЕНТ-ПЛАН ИЗ БД:"]
        for item in items[:14]:
            date = item.get("scheduled", "?")
            topic = item.get("topic", "")
            desc = item.get("description", "")
            platform = item.get("platform", "")
            lines.append(f"- {date} | {platform} | {topic}: {desc}")
        return "\n".join(lines)

    def _enrich_task_with_plan(self, task: str) -> str:
        """Если задача касается существующего плана — подклеиваем его из БД."""
        task_lower = task.lower()
        needs_plan = any(kw in task_lower for kw in _EXISTING_PLAN_KEYWORDS)
        if not needs_plan:
            return task

        plan_ctx = self._load_db_plan_context()
        if not plan_ctx:
            return task

        return f"{task}\n\n---\n{plan_ctx}"

    def _plan(self, task: str) -> dict:
        """Составляет план выполнения задачи."""
        max_retries = 3
        retry_delays = [10, 30, 60]
        response = None

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
                    logger.warning(f"[Curator] 529, жду {wait}с...")
                    time.sleep(wait)
                else:
                    raise
            except anthropic.APIConnectionError:
                if attempt < max_retries - 1:
                    time.sleep(retry_delays[attempt])
                else:
                    raise

        raw = response.content[0].text.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        return json.loads(raw)

    def run(self, task: str, progress_cb=None) -> dict:
        logger.info(f"[Curator] Задача: {task[:80]}")
        if progress_cb:
            progress_cb("plan", "🧠 Куратор составляет план...")

        # Подгружаем план из БД если задача о нём
        enriched_task = self._enrich_task_with_plan(task)
        if enriched_task != task:
            logger.info("[Curator] Контент-план подгружен из БД в контекст задачи")

        try:
            plan = self._plan(enriched_task)
        except Exception as e:
            logger.error(f"[Curator] Ошибка планирования: {e}")
            plan = {
                "task_summary": task,
                "steps": [{"agent": "copywriter", "instruction": enriched_task, "use_previous": False, "output_label": "Результат"}],
                "final_format": "Готовый контент",
            }

        logger.info(f"[Curator] План: {json.dumps(plan, ensure_ascii=False)[:300]}")

        agent_emojis = {
            "analyst": "🔍", "strategist": "📋",
            "copywriter": "✍️", "designer": "🎨", "publisher": "📅",
        }

        steps_results = []
        # Если задача обогащена планом — стартовый контекст уже содержит план
        accumulated_context = ""
        if enriched_task != task:
            plan_ctx = self._load_db_plan_context()
            if plan_ctx:
                accumulated_context = f"[Контент-план]:\n{plan_ctx}"

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
                progress_cb(agent_name, f"{emoji} {agent_name.capitalize()} работает...")

            full_instruction = instruction
            if use_previous and accumulated_context:
                full_instruction = (
                    f"{instruction}\n\n"
                    f"---\nКОНТЕКСТ:\n{accumulated_context}"
                )

            agent = AGENTS[agent_name]

            if agent_name == "copywriter":
                result = BaseAgent.run(agent, full_instruction)
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

            accumulated_context += f"\n\n[{output_label}]:\n{result[:800]}"
            logger.info(f"[Curator] Шаг {i+1} готов: {result[:80]}...")

        # Сохраняем черновик от копирайтера
        draft_id = None
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
            logger.info(f"[Curator] Черновик #{draft_id} сохранён")

        return {
            "plan": plan,
            "steps_results": steps_results,
            "draft_id": draft_id,
            "final_format": plan.get("final_format", ""),
        }
