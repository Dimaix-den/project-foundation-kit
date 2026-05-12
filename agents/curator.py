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
from storage.sheets import write_texts_to_plan, is_sheets_enabled

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
],"final_format":"План записан в Google Sheets"}}

Задача: "мне нравятся тексты, запиши их в таблице" / "запиши их в таблицу" / "сохрани тексты"
{{"task_summary":"Записать готовые тексты постов в Google Sheets","steps":[
  {{"agent":"publisher","instruction":"Запиши тексты постов в таблицу Google Sheets. Возьми тексты из последнего черновика в базе данных. Каждый пост в отдельную строку колонки Текст к посту.","use_previous":false,"output_label":"Тексты записаны в таблицу"}}
],"final_format":"Тексты постов записаны в Google Sheets"}}

Задача: "пост на сегодня" / "сформируйте пост для публикации" / "пост для канала"
— В контексте задачи может быть СПРАВКА с контент-планом. Если есть — возьми тему на ближайшую дату.
— Если темы нет — выбери сам исходя из бренд-контекста.
{{"task_summary":"Пост для публикации сегодня","steps":[
  {{"agent":"copywriter","instruction":"Напиши пост для Telegram на тему из контент-плана (если есть в контексте — возьми ближайшую дату). Заголовок + тело 400-600 символов + CTA.","use_previous":true,"output_label":"Текст поста"}},
  {{"agent":"designer","instruction":"Визуал для поста. Lifestyle-сцена казахстанца с финансами. Тёмный фон, мятный акцент.","use_previous":false,"output_label":"Изображение"}}
],"final_format":"Готовый пост + изображение"}}"""


# Ключевые слова, означающие «используй существующий план из БД»
_EXISTING_PLAN_KEYWORDS = [
    "текущий план", "текущий контент-план", "текущий контент план",
    "из плана", "по плану", "нравится план", "нравится контент-план",
    "тексты к постам", "тексты для постов", "тексты постов",
    "пропиши посты", "напиши посты", "напишите посты",
    "напишите тексты", "пропишите тексты",
    "столбец текст", "текст к посту", "заполните тексты",
    "запишите тексты", "запиши тексты", "написать тексты",
    "в каждую строку", "каждый пост в строку", "по строкам",
    "исправь тексты", "заново запиши", "перезапиши тексты",
    "запиши их", "сохрани их", "нравятся текста", "нравятся тексты",
    "запиши в таблиц", "сохрани в таблиц",
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
        """Подклеиваем план из БД если он есть и задача о создании/работе с контентом."""
        task_lower = task.lower()

        # Явные ключевые слова — всегда подгружаем план
        needs_plan = any(kw in task_lower for kw in _EXISTING_PLAN_KEYWORDS)

        # Запросы на создание поста — тоже проверяем план
        _POST_KEYWORDS = [
            "пост", "публикац", "сегодня", "на неделю", "материал",
            "контент", "текст для", "напиши пост", "создай пост",
            "сформируй", "подготовь", "сделай пост",
        ]
        wants_post = any(kw in task_lower for kw in _POST_KEYWORDS)

        if not needs_plan and not wants_post:
            return task

        plan_ctx = self._load_db_plan_context()
        if not plan_ctx:
            return task

        if needs_plan:
            # Явный запрос — план идёт как жёсткий контекст
            return f"{task}\n\n---\n{plan_ctx}"
        else:
            # Запрос на пост — план идёт как справочная информация
            return f"{task}\n\n---\nСПРАВКА (используй если тема не указана явно):\n{plan_ctx}"

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

    # Ключевые слова "не пиши в чат, сохрани в таблицу"
    _SILENT_KEYWORDS = [
        "не пиши в чат", "не надо в чат", "только в таблицу",
        "сохрани в таблице", "сохрани в таблицу", "запиши в таблицу",
        "не выводи в чат", "сразу сохрани", "без вывода",
    ]

    def run(self, task: str, progress_cb=None) -> dict:
        logger.info(f"[Curator] Задача: {task[:80]}")
        if progress_cb:
            progress_cb("plan", "🧠 *Куратор* анализирует задачу и составляет план...")

        # Режим "только в таблицу" — не дублировать тексты в чат
        task_lower = task.lower()
        silent_mode = any(kw in task_lower for kw in self._SILENT_KEYWORDS)
        if silent_mode:
            logger.info("[Curator] Silent mode: copywriter output won't be sent to chat")

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
                step_msgs = {
                    "analyst":    f"🔍 *Аналитик* изучает тему: _{output_label}_...",
                    "strategist": f"📋 *Стратег* составляет: _{output_label}_...",
                    "copywriter": f"✍️ *Копирайтер* пишет: _{output_label}_...",
                    "designer":   f"🎨 *Дизайнер* создаёт: _{output_label}_...",
                    "publisher":  f"📅 *Менеджер* сохраняет: _{output_label}_...",
                }
                progress_cb(agent_name, step_msgs.get(agent_name, f"{emoji} *{agent_name}* работает..."))

            full_instruction = instruction
            if use_previous and accumulated_context:
                full_instruction = (
                    f"{instruction}\n\nКОНТЕКСТ:\n{accumulated_context}"
                )

            agent = AGENTS[agent_name]

            if agent_name == "copywriter":
                result = BaseAgent.run(agent, full_instruction)
                if "💾 *Черновик сохранён*" in result:
                    result = result.split("💾 *Черновик сохранён*")[0].strip()
            else:
                result = agent.run(full_instruction)

            hide_in_chat = silent_mode and agent_name == "copywriter"
            steps_results.append({
                "step": i + 1,
                "agent": agent_name,
                "label": output_label,
                "result": result,
                "hidden": hide_in_chat,
            })

            # Паблишер получает полный текст (нужен для записи всех постов в Sheets)
            ctx_slice = result if agent_name == "publisher" else result[:3000]
            accumulated_context += f"\n\n[{output_label}]:\n{ctx_slice}"
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

            # Автоматически пишем тексты в Sheets если задача была о написании постов
            _WRITE_TO_SHEETS_KEYWORDS = [
                "таблиц", "sheets", "запиши", "сохрани", "текст к посту",
                "по строкам", "в строку", "столбец",
            ]
            task_wants_sheets = any(kw in task.lower() for kw in _WRITE_TO_SHEETS_KEYWORDS)
            # Или если паблишер был в плане
            publisher_in_plan = any(s.get("agent") == "publisher" for s in plan.get("steps", []))

            if (task_wants_sheets or publisher_in_plan) and is_sheets_enabled():
                try:
                    import re as _re
                    # Парсим тексты по разделителям ===ПОСТ N===
                    parts = _re.split(r'={2,}\s*ПОСТ\s*\d+[^=]*={2,}', copywriter_result, flags=_re.IGNORECASE)
                    texts = [p.strip() for p in parts if p.strip() and len(p.strip()) > 80]
                    # Fallback: по тройным переносам
                    if len(texts) <= 1:
                        parts = _re.split(r'\n{3,}', copywriter_result)
                        texts = [p.strip() for p in parts if p.strip() and len(p.strip()) > 100]
                    if len(texts) > 1:
                        # Убеждаемся что план уже в Sheets — если нет, пишем сначала
                        from storage.sheets import read_sheet
                        existing_rows = read_sheet()
                        if not existing_rows:
                            # План есть в БД, но не в Sheets — пишем его
                            plan_items = get_plan("planned")
                            if plan_items:
                                write_texts_to_plan.__module__  # ensure import
                                from storage.sheets import write_content_plan as _wcp
                                _wcp(plan_items)
                                logger.info("[Curator] Записал план в Sheets перед текстами")
                        sheets_result = write_texts_to_plan(texts)
                        if isinstance(sheets_result, str) and "|" in sheets_result:
                            url, count = sheets_result.split("|", 1)
                            logger.info(f"[Curator] Тексты записаны в Sheets: {count} постов")
                            # Добавляем результат в steps_results чтобы пользователь видел
                            steps_results.append({
                                "step": len(steps_results) + 1,
                                "agent": "publisher",
                                "label": "Тексты в таблице",
                                "result": f"Готово 📊 Записано *{count} текстов* — [Открыть таблицу]({url})",
                            })
                except Exception as e:
                    logger.warning(f"[Curator] Не удалось автосохранить в Sheets: {e}")

        return {
            "plan": plan,
            "steps_results": steps_results,
            "draft_id": draft_id,
            "final_format": plan.get("final_format", ""),
        }
