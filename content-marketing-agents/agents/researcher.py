"""Researcher — Этап 1. Загружает знания о продукте в ChromaDB."""
from __future__ import annotations

from pathlib import Path

from agents.base_agent import BaseAgent
from memory.vector_store import VectorStore
from tools.file_reader import read_file
from tools.web_search import web_search


class Researcher(BaseAgent):
    name = "researcher"

    def __init__(self) -> None:
        super().__init__()
        self.store = VectorStore(collection="product_knowledge")

    # ---------- Ingestion ----------
    def ingest_file(self, path: Path) -> int:
        """Прочитать файл, разбить на чанки, сохранить в ChromaDB."""
        text = read_file(path)
        chunks = self._chunk(text)
        self.store.add(chunks, metadata={"source": str(path), "type": path.suffix})
        self.log.info("Ingested %s (%d chunks)", path, len(chunks))
        return len(chunks)

    def ingest_directory(self, directory: Path) -> None:
        if not directory.exists():
            self.log.warning("Папка не найдена: %s", directory)
            return
        for path in directory.rglob("*"):
            if path.is_file() and path.suffix.lower() in {".pdf", ".docx", ".txt", ".md", ".html"}:
                try:
                    self.ingest_file(path)
                except Exception as exc:  # noqa: BLE001
                    self.log.exception("Не удалось загрузить %s: %s", path, exc)

    def ingest_url(self, url: str) -> None:
        text = read_file(url)
        chunks = self._chunk(text)
        self.store.add(chunks, metadata={"source": url, "type": "url"})
        self.log.info("Ingested URL %s (%d chunks)", url, len(chunks))

    # ---------- Web research ----------
    def research_web(self, query: str) -> str:
        return web_search(self.client, query)

    # ---------- Interactive ----------
    def interactive(self) -> None:
        self.log.info("Интерактивный режим. Введите 'exit' для выхода.")
        while True:
            q = input("> ").strip()
            if q in {"exit", "quit"}:
                break
            hits = self.store.query(q, k=5)
            for h in hits:
                print("—", h[:200])

    # ---------- Report ----------
    def write_report(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        prompt = (
            "На основе загруженных знаний составь структурированный отчёт: "
            "профиль продукта, ЦА, УТП, конкуренты. Markdown."
        )
        # TODO: подмешать top-k чанков из self.store в контекст
        resp = self.call_claude(prompt)
        text = "".join(block.text for block in resp.content if getattr(block, "type", "") == "text")
        path.write_text(text, encoding="utf-8")
        self.log.info("Отчёт сохранён: %s", path)

    # ---------- Helpers ----------
    @staticmethod
    def _chunk(text: str, size: int = 500, overlap: int = 50) -> list[str]:
        """Грубое разбиение по словам (~ токенам)."""
        words = text.split()
        chunks: list[str] = []
        i = 0
        while i < len(words):
            chunks.append(" ".join(words[i : i + size]))
            i += size - overlap
        return chunks
