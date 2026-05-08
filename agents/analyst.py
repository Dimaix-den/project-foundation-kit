"""
Агент-аналитик: исследует рынок, тренды, конкурентов, аудиторию.
Умеет искать в интернете через DuckDuckGo (без API-ключа).
"""
from __future__ import annotations
import json
import anthropic
from config import ANTHROPIC_API_KEY, MODEL
from agents.base import BaseAgent

try:
    from duckduckgo_search import DDGS
    SEARCH_AVAILABLE = True
except ImportError:
    SEARCH_AVAILABLE = False


class AnalystAgent(BaseAgent):
    name = "analyst"
    emoji = "🔍"

    def _system_prompt(self) -> str:
        brand = self._brand_context()
        return f"""Ты — опытный контент-аналитик и маркетолог-исследователь.

БРЕНД-КОНТЕКСТ:
{brand}

ТВОИ ЗАДАЧИ:
- Анализировать тренды в нише
- Исследовать конкурентов и их контент-стратегии
- Выявлять боли, интересы и запросы целевой аудитории
- Давать практические инсайты для контент-стратегии
- Предлагать темы и форматы контента на основе данных

СТИЛЬ ОТВЕТОВ:
- Структурированно, с заголовками и списками
- Конкретно и по делу — факты, цифры, примеры
- В конце всегда давай 2-3 практических вывода

Отвечай на том же языке, на котором к тебе обращаются."""

    def _search_web(self, query: str, max_results: int = 5) -> list[dict]:
        """Поиск через DuckDuckGo без API-ключа."""
        if not SEARCH_AVAILABLE:
            return []
        try:
            with DDGS() as ddgs:
                results = list(ddgs.text(query, max_results=max_results))
            return results
        except Exception as e:
            print(f"Search error: {e}")
            return []

    def run(self, user_message: str, history: list[dict] = None) -> str:
        """
        Если сообщение выглядит как запрос на исследование —
        сначала ищем в интернете, потом отдаём результаты Claude для анализа.
        """
        search_keywords = ["тренд", "конкурент", "рынок", "исследован", "найди", "что сейчас", "популярн", "анализ"]
        needs_search = any(kw in user_message.lower() for kw in search_keywords)

        search_context = ""
        if needs_search and SEARCH_AVAILABLE:
            results = self._search_web(user_message, max_results=6)
            if results:
                snippets = "\n\n".join(
                    f"[{r.get('title', '')}]\n{r.get('body', '')}"
                    for r in results
                )
                search_context = f"\n\n---\nРЕЗУЛЬТАТЫ ПОИСКА (используй как источник данных):\n{snippets}\n---\n"

        enriched_message = user_message + search_context
        return super().run(enriched_message, history)
