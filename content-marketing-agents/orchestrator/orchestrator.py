"""Оркестратор — координирует работу агентов."""
from __future__ import annotations


class Orchestrator:
    """Планировщик задач между агентами. TODO: реализовать на этапе 4-5."""

    def __init__(self) -> None:
        self.agents: dict[str, object] = {}

    def register(self, name: str, agent: object) -> None:
        self.agents[name] = agent

    def run_pipeline(self) -> None:
        raise NotImplementedError
