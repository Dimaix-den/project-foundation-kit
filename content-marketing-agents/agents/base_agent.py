"""
BaseAgent — базовый класс для всех агентов системы контент-маркетинга.
"""
import logging
import os
from typing import Any
import anthropic
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)


class BaseAgent:
    def __init__(self, name: str):
        self.name = name
        self.client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
        self.model = os.getenv("CLAUDE_MODEL", "claude-sonnet-4-20250514")
        self.logger = logging.getLogger(f"agent.{name}")
        self.logger.info(f"[{self.name}] Агент инициализирован")

    def call_claude(
        self,
        messages: list[dict],
        system: str = "",
        tools: list[dict] | None = None,
        max_tokens: int = 4096,
    ) -> anthropic.types.Message:
        """Вызов Claude API с опциональными инструментами."""
        kwargs: dict[str, Any] = {
            "model": self.model,
            "max_tokens": max_tokens,
            "messages": messages,
        }
        if system:
            kwargs["system"] = system
        if tools:
            kwargs["tools"] = tools

        self.logger.debug(f"[{self.name}] Вызов Claude, messages={len(messages)}")
        response = self.client.messages.create(**kwargs)
        self.logger.debug(f"[{self.name}] Ответ получен, stop_reason={response.stop_reason}")
        return response

    def extract_text(self, response: anthropic.types.Message) -> str:
        """Извлекает текстовый контент из ответа Claude."""
        texts = [block.text for block in response.content if hasattr(block, "text")]
        return "\n".join(texts)

    def log(self, level: str, message: str) -> None:
        """Логирование с именем агента."""
        getattr(self.logger, level.lower(), self.logger.info)(f"[{self.name}] {message}")

    def run(self, task: dict) -> dict:
        """Точка входа для оркестратора. Переопределяется в каждом агенте."""
        raise NotImplementedError(f"Агент {self.name} должен реализовать метод run()")
