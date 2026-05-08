"""Базовый класс для всех агентов."""
from __future__ import annotations

import logging
import os
from typing import Any

from anthropic import Anthropic


class BaseAgent:
    """Общий функционал: вызов Claude, логирование, доступ к памяти."""

    name: str = "base"
    model: str = "claude-sonnet-4-5-20250929"

    def __init__(self) -> None:
        self.log = logging.getLogger(self.name)
        self.client = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

    def call_claude(
        self,
        prompt: str,
        *,
        system: str | None = None,
        tools: list[dict[str, Any]] | None = None,
        max_tokens: int = 4096,
    ) -> Any:
        """Вызов Claude messages API."""
        kwargs: dict[str, Any] = {
            "model": self.model,
            "max_tokens": max_tokens,
            "messages": [{"role": "user", "content": prompt}],
        }
        if system:
            kwargs["system"] = system
        if tools:
            kwargs["tools"] = tools
        return self.client.messages.create(**kwargs)
