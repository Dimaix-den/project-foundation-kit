"""Обёртка над ChromaDB."""
from __future__ import annotations

import os
import uuid
from typing import Any

import chromadb


class VectorStore:
    def __init__(self, collection: str = "default", path: str | None = None) -> None:
        self.client = chromadb.PersistentClient(
            path=path or os.getenv("CHROMA_PATH", "./memory/chroma_db")
        )
        self.collection = self.client.get_or_create_collection(collection)

    def add(self, chunks: list[str], metadata: dict[str, Any] | None = None) -> None:
        if not chunks:
            return
        ids = [str(uuid.uuid4()) for _ in chunks]
        metadatas = [dict(metadata or {}) for _ in chunks]
        self.collection.add(documents=chunks, ids=ids, metadatas=metadatas)

    def query(self, text: str, k: int = 5) -> list[str]:
        res = self.collection.query(query_texts=[text], n_results=k)
        docs = res.get("documents") or [[]]
        return docs[0]

    def reset(self) -> None:
        name = self.collection.name
        self.client.delete_collection(name)
        self.collection = self.client.get_or_create_collection(name)
