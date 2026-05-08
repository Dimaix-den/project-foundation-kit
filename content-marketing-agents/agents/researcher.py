"""
Researcher — агент-исследователь (Этап 1).

Режимы работы:
- ingest: загрузка файлов в ChromaDB
- web:    веб-исследование продукта/конкурентов
- report: генерация итогового отчёта
- chat:   диалог для уточнения информации
"""
import os
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

from agents.base_agent import BaseAgent
from memory.vector_store import VectorStore
from tools.file_reader import read_file, read_directory, chunk_text
from tools.web_search import web_search, search_product_info

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """Ты — AI-агент Researcher (Исследователь) в системе контент-маркетинга.

Твои задачи:
1. Изучать материалы о продукте (документы, веб-страницы)
2. Исследовать конкурентов и рынок
3. Формировать структурированную базу знаний
4. Отвечать на вопросы о продукте на основе загруженных материалов

При анализе всегда выделяй:
- Описание продукта и его характеристики
- Целевую аудиторию (ЦА)
- Уникальное торговое предложение (УТП)
- Конкурентов и их позиционирование
- Ключевые преимущества и боли клиентов

Отвечай на русском языке. Будь конкретным и структурированным."""


class Researcher(BaseAgent):
    def __init__(self, vector_store: Optional[VectorStore] = None):
        super().__init__(name="researcher")
        self.vs = vector_store or VectorStore()
        self.outputs_dir = Path(os.getenv("OUTPUTS_DIR", "./data/outputs"))
        self.outputs_dir.mkdir(parents=True, exist_ok=True)

    # ──────────────────────────────────────────────
    # Публичные методы (вызываются из Telegram-бота)
    # ──────────────────────────────────────────────

    def ingest_file(self, path: str) -> dict:
        """Загружает один файл в ChromaDB. Возвращает {'chunks': int, 'name': str}."""
        content = read_file(path)
        if not content:
            return {"error": f"Не удалось прочитать файл: {path}"}

        file_name = Path(path).name
        chunks = chunk_text(content)
        ids = [f"{file_name}__chunk_{i}" for i in range(len(chunks))]
        metadatas = [{"source": file_name, "type": "file", "path": path} for _ in chunks]

        added = self.vs.add(chunks, ids, metadatas)
        self.log("info", f"Загружен файл {file_name}: {added} чанков")
        return {"chunks": added, "name": file_name}

    def ingest_directory(self, directory: str) -> dict:
        """Загружает все файлы из папки. Возвращает сводку."""
        files = read_directory(directory)
        if not files:
            return {"error": f"Нет поддерживаемых файлов в папке: {directory}"}

        total_chunks = 0
        loaded_files = []
        for file_info in files:
            result = self.ingest_file(file_info["path"])
            if "error" not in result:
                total_chunks += result["chunks"]
                loaded_files.append(result["name"])

        return {
            "files": loaded_files,
            "total_chunks": total_chunks,
            "total_files": len(loaded_files),
        }

    def web_research(self, query: str) -> str:
        """Веб-исследование по запросу. Результат сохраняется в ChromaDB."""
        self.log("info", f"Веб-исследование: {query}")
        result = web_search(query)

        # Сохраняем результат в базу знаний
        chunks = chunk_text(result)
        ids = [f"web_{datetime.now().strftime('%Y%m%d%H%M%S')}__chunk_{i}" for i in range(len(chunks))]
        metadatas = [{"source": f"web_search: {query}", "type": "web"} for _ in chunks]
        self.vs.add(chunks, ids, metadatas)

        return result

    def research_product(self, product_name: str) -> str:
        """Комплексное исследование продукта и конкурентов."""
        self.log("info", f"Комплексное исследование: {product_name}")
        result = search_product_info(product_name)

        # Сохраняем в базу
        chunks = chunk_text(result)
        ids = [f"product_{datetime.now().strftime('%Y%m%d%H%M%S')}__chunk_{i}" for i in range(len(chunks))]
        metadatas = [{"source": f"product_research: {product_name}", "type": "web"} for _ in chunks]
        self.vs.add(chunks, ids, metadatas)

        return result

    def generate_report(self) -> str:
        """Генерирует итоговый research_report.md на основе всех данных в ChromaDB."""
        if self.vs.count() == 0:
            return "❌ База знаний пуста. Сначала загрузите материалы."

        self.log("info", "Генерация итогового отчёта")

        # Собираем релевантные данные по ключевым аспектам
        aspects = {
            "Описание продукта": "описание продукта характеристики функции",
            "Целевая аудитория": "целевая аудитория клиенты пользователи",
            "УТП": "уникальное торговое предложение преимущества отличия",
            "Конкуренты": "конкуренты рынок сравнение",
        }

        context_parts = []
        for aspect, query in aspects.items():
            results = self.vs.query(query, n_results=3)
            if results:
                texts = "\n".join([r["text"] for r in results])
                context_parts.append(f"### {aspect}\n{texts}")

        context = "\n\n".join(context_parts)
        sources = self.vs.list_sources()

        messages = [
            {
                "role": "user",
                "content": (
                    f"На основе следующих материалов создай структурированный исследовательский отчёт.\n\n"
                    f"МАТЕРИАЛЫ:\n{context}\n\n"
                    f"ИСТОЧНИКИ: {', '.join(sources)}\n\n"
                    "Отчёт должен содержать разделы:\n"
                    "1. Описание продукта\n"
                    "2. Целевая аудитория (ЦА)\n"
                    "3. Уникальное торговое предложение (УТП)\n"
                    "4. Конкурентный анализ\n"
                    "5. Ключевые инсайты для контент-маркетинга\n"
                    "Используй Markdown-форматирование."
                ),
            }
        ]

        response = self.call_claude(messages, system=SYSTEM_PROMPT, max_tokens=4096)
        report = self.extract_text(response)

        # Сохраняем отчёт
        report_path = self.outputs_dir / "research_report.md"
        with open(report_path, "w", encoding="utf-8") as f:
            f.write(f"# Research Report\n_Сгенерировано: {datetime.now().strftime('%d.%m.%Y %H:%M')}_\n\n")
            f.write(report)

        self.log("info", f"Отчёт сохранён: {report_path}")
        return report

    def chat(self, user_message: str, history: list[dict] | None = None) -> str:
        """
        Диалог с агентом. Использует RAG: ищет релевантные данные в ChromaDB,
        затем отвечает с учётом контекста.
        """
        # RAG: ищем релевантный контекст
        context = ""
        if self.vs.count() > 0:
            results = self.vs.query(user_message, n_results=4)
            if results:
                context_texts = "\n\n".join([r["text"] for r in results])
                context = f"\n\nРЕЛЕВАНТНЫЙ КОНТЕКСТ ИЗ БАЗЫ ЗНАНИЙ:\n{context_texts}"

        messages = list(history or [])
        messages.append({
            "role": "user",
            "content": user_message + context,
        })

        response = self.call_claude(messages, system=SYSTEM_PROMPT, max_tokens=2048)
        return self.extract_text(response)

    def get_status(self) -> dict:
        """Возвращает статус базы знаний."""
        return {
            "chunks": self.vs.count(),
            "sources": self.vs.list_sources(),
        }

    def run(self, task: dict) -> dict:
        """Точка входа для оркестратора."""
        mode = task.get("mode", "chat")
        if mode == "ingest":
            return self.ingest_file(task["path"])
        elif mode == "ingest_dir":
            return self.ingest_directory(task["directory"])
        elif mode == "web":
            return {"result": self.web_research(task["query"])}
        elif mode == "report":
            return {"result": self.generate_report()}
        elif mode == "chat":
            return {"result": self.chat(task["message"], task.get("history"))}
        else:
            return {"error": f"Неизвестный режим: {mode}"}
