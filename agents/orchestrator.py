"""
Оркестратор — мозг системы.
Анализирует входящее сообщение и решает, какому агенту его передать.
Использует Claude для классификации намерения.
"""
import anthropic
from config import ANTHROPIC_API_KEY, MODEL
from agents.analyst import AnalystAgent
from agents.strategist import StrategistAgent
from agents.copywriter import CopywriterAgent
from agents.designer import DesignerAgent
from agents.publisher import PublisherAgent

AGENTS = {
    "analyst":    AnalystAgent(),
    "strategist": StrategistAgent(),
    "copywriter": CopywriterAgent(),
    "designer":   DesignerAgent(),
    "publisher":  PublisherAgent(),
}

AGENT_DESCRIPTIONS = """
- analyst: исследование рынка, анализ трендов, конкуренты, аудитория, данные
- strategist: контент-план, рубрики, темы, редакционный календарь, идеи для плана
- copywriter: написать пост, текст, статью, подпись, заголовок, тексты для соцсетей
- designer: визуал, картинка, изображение, промпт для AI-арта, дизайн, обложка
- publisher: статус, что в работе, расписание, черновики, одобрить, опубликовать, план публикаций, Google Sheets, таблица, столбец, записать в таблицу, добавить столбец
"""

ROUTING_SYSTEM = f"""Ты — маршрутизатор для команды ИИ-агентов контент-маркетинга.

Твоя единственная задача — определить, какому агенту передать запрос пользователя.

АГЕНТЫ И ИХ СПЕЦИАЛИЗАЦИЯ:
{AGENT_DESCRIPTIONS}

Ответь ТОЛЬКО одним словом — именем агента (analyst, strategist, copywriter, designer, publisher).
Никакого другого текста, только имя агента."""


class Orchestrator:
    def __init__(self):
        self.client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        # Маппинг: топик → агент по умолчанию
        self._topic_default: dict[int, str] = {}

    def set_topic_defaults(self, topic_map: dict[int, str]):
        """Привязывает Telegram топики к агентам по умолчанию."""
        self._topic_default = topic_map

    def _classify(self, message: str) -> str:
        """Определяет подходящего агента через Claude."""
        try:
            response = self.client.messages.create(
                model=MODEL,
                max_tokens=20,
                system=ROUTING_SYSTEM,
                messages=[{"role": "user", "content": message}],
            )
            agent_name = response.content[0].text.strip().lower()
            if agent_name in AGENTS:
                return agent_name
        except Exception as e:
            print(f"Routing error: {e}")
        return "copywriter"  # fallback

    def route(
        self,
        message: str,
        history: list[dict] = None,
        topic_id: int = 0,
        force_agent: str = None,
    ) -> tuple[str, str]:
        """
        Маршрутизирует сообщение к нужному агенту.
        Возвращает (agent_name, response_text).
        """
        # 1. Принудительный агент (если указан командой)
        if force_agent and force_agent in AGENTS:
            agent_name = force_agent

        # 2. Агент по топику (если топик настроен)
        elif topic_id and topic_id in self._topic_default:
            agent_name = self._topic_default[topic_id]

        # 3. Автоопределение через Claude
        else:
            agent_name = self._classify(message)

        agent = AGENTS[agent_name]
        print(f"→ Routing to [{agent_name}] | Message: {message[:60]}...")

        response = agent.run(message, history)
        return agent_name, response

    def get_agent(self, name: str):
        return AGENTS.get(name)
