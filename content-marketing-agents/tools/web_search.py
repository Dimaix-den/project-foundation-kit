"""Поиск в вебе через Claude `web_search` tool use."""
from __future__ import annotations

from typing import Any


def web_search(client: Any, query: str, max_uses: int = 5) -> str:
    """Запросить Claude с включённым инструментом web_search."""
    resp = client.messages.create(
        model="claude-sonnet-4-5-20250929",
        max_tokens=4096,
        tools=[{"type": "web_search_20250305", "name": "web_search", "max_uses": max_uses}],
        messages=[{"role": "user", "content": query}],
    )
    parts: list[str] = []
    for block in resp.content:
        if getattr(block, "type", "") == "text":
            parts.append(block.text)
    return "\n".join(parts)
