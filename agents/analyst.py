"""
Агент-аналитик с реальными инструментами (tool_use).

Умеет:
- Искать в интернете (DuckDuckGo)
- Открывать и читать URL (веб-страницы, статьи, сайты конкурентов)
- Читать документы: PDF, DOCX, TXT
- Сам решает что и когда использовать — через Claude tool_use
"""
from __future__ import annotations
import json
import logging
import time
import re
import anthropic
from config import ANTHROPIC_API_KEY, MODEL
from agents.base import BaseAgent

logger = logging.getLogger(__name__)

TOOLS = [
    {
        "name": "web_search",
        "description": "Поиск в интернете через DuckDuckGo. Используй для поиска трендов, новостей, конкурентов, информации о рынке.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Поисковый запрос"},
                "max_results": {"type": "integer", "description": "Количество результатов (по умолчанию 5)", "default": 5}
            },
            "required": ["query"]
        }
    },
    {
        "name": "fetch_url",
        "description": "Открывает URL и возвращает текстовое содержимое страницы. Используй для чтения сайтов конкурентов, статей, новостей по ссылке.",
        "input_schema": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "Полный URL страницы (с https://)"}
            },
            "required": ["url"]
        }
    },
    {
        "name": "read_document",
        "description": "Читает содержимое документа по пути к файлу. Поддерживает PDF, DOCX, TXT.",
        "input_schema": {
            "type": "object",
            "properties": {
                "file_path": {"type": "string", "description": "Путь к файлу"}
            },
            "required": ["file_path"]
        }
    }
]


def _tool_web_search(query: str, max_results: int = 5) -> str:
    try:
        from duckduckgo_search import DDGS
        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=min(max_results, 10)))
        if not results:
            return "Ничего не найдено."
        out = []
        for i, r in enumerate(results, 1):
            out.append(f"{i}. {r.get('title','')}\n   {r.get('href','')}\n   {r.get('body','')[:300]}")
        return "\n\n".join(out)
    except Exception as e:
        return f"Ошибка поиска: {e}"


def _tool_fetch_url(url: str) -> str:
    try:
        import requests
        from bs4 import BeautifulSoup
        headers = {"User-Agent": "Mozilla/5.0 (compatible; SandaBot/1.0)"}
        resp = requests.get(url, headers=headers, timeout=15)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
            tag.decompose()
        text = soup.get_text(separator="\n", strip=True)
        lines = [l.strip() for l in text.splitlines() if l.strip()]
        text = "\n".join(lines)
        if len(text) > 6000:
            text = text[:6000] + "\n\n[... обрезано ...]"
        return f"URL: {url}\n\n{text}"
    except Exception as e:
        return f"Не удалось открыть {url}: {e}"


def _tool_read_document(file_path: str) -> str:
    try:
        file_path = file_path.strip()
        if file_path.lower().endswith(".pdf"):
            from pypdf import PdfReader
            reader = PdfReader(file_path)
            text = "\n".join(page.extract_text() or "" for page in reader.pages)
        elif file_path.lower().endswith(".docx"):
            from docx import Document
            doc = Document(file_path)
            text = "\n".join(p.text for p in doc.paragraphs if p.text.strip())
        elif file_path.lower().endswith(".txt"):
            with open(file_path, encoding="utf-8", errors="ignore") as f:
                text = f.read()
        else:
            return "Формат не поддерживается. Поддерживаются: PDF, DOCX, TXT"
        if len(text) > 8000:
            text = text[:8000] + "\n\n[... обрезано ...]"
        return f"Файл: {file_path}\n\n{text}" if text.strip() else "Документ пустой."
    except FileNotFoundError:
        return f"Файл не найден: {file_path}"
    except Exception as e:
        return f"Ошибка чтения: {e}"


def _execute_tool(name: str, inputs: dict) -> str:
    if name == "web_search":
        return _tool_web_search(inputs.get("query", ""), inputs.get("max_results", 5))
    elif name == "fetch_url":
        return _tool_fetch_url(inputs.get("url", ""))
    elif name == "read_document":
        return _tool_read_document(inputs.get("file_path", ""))
    return f"Инструмент '{name}' не найден"


class AnalystAgent(BaseAgent):
    name = "analyst"
    emoji = "🔍"

    def __init__(self):
        super().__init__()
        self.client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    def _system_prompt(self) -> str:
        brand = self._brand_context()
        return f"""Ты — опытный контент-аналитик и маркетолог-исследователь финтех-стартапа.

БРЕНД-КОНТЕКСТ:
{brand}

ТВОИ ЗАДАЧИ:
- Анализировать тренды в нише личных финансов, fintech, Казахстан
- Исследовать конкурентов и их контент-стратегии
- Выявлять боли и запросы целевой аудитории
- Читать документы, статьи, сайты которые предоставляет пользователь
- Давать практические инсайты для контент-стратегии Sanda

ИНСТРУМЕНТЫ — используй их активно:
- web_search: ищи актуальную информацию, тренды, конкурентов
- fetch_url: открывай конкретные сайты для детального анализа
- read_document: читай документы загруженные пользователем

СТИЛЬ: структурированно, с источниками, конкретные выводы для Sanda.
Отвечай на том же языке, на котором к тебе обращаются."""

    def run(self, user_message: str, history: list[dict] = None, file_path: str = None) -> str:
        messages = []
        if history:
            for h in history[-6:]:
                messages.append({"role": h["role"], "content": h["content"]})

        content = user_message
        if file_path:
            content += f"\n\n[Пользователь загрузил файл: {file_path}]"

        urls = re.findall(r'https?://[^\s]+', user_message)
        if urls:
            content += f"\n\n[Обнаружены ссылки: {', '.join(urls)}]"

        messages.append({"role": "user", "content": content})

        max_retries = 3
        retry_delays = [10, 30, 60]

        for _round in range(6):  # максимум 6 раундов tool_use
            for attempt in range(max_retries):
                try:
                    response = self.client.messages.create(
                        model=MODEL,
                        max_tokens=4096,
                        system=self._full_system_prompt(),
                        tools=TOOLS,
                        messages=messages,
                    )
                    break
                except anthropic.APIStatusError as e:
                    if e.status_code == 529 and attempt < max_retries - 1:
                        wait = retry_delays[attempt]
                        logger.warning(f"[Analyst] API 529, жду {wait}с...")
                        time.sleep(wait)
                    else:
                        raise

            if response.stop_reason == "end_turn":
                text_blocks = [b.text for b in response.content if hasattr(b, "text")]
                return "\n\n".join(text_blocks) or "Анализ завершён."

            if response.stop_reason == "tool_use":
                messages.append({"role": "assistant", "content": response.content})
                tool_results = []
                for block in response.content:
                    if block.type == "tool_use":
                        logger.info(f"[Analyst] {block.name}({json.dumps(block.input, ensure_ascii=False)[:80]})")
                        result = _execute_tool(block.name, block.input)
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": result,
                        })
                messages.append({"role": "user", "content": tool_results})
                continue

            break

        text_blocks = [b.text for b in response.content if hasattr(b, "text")]
        return "\n\n".join(text_blocks) or "Анализ завершён."
