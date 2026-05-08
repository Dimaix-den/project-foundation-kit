"""Тесты для Researcher (Этап 1)."""
from agents.researcher import Researcher


def test_chunking_basic():
    text = " ".join(str(i) for i in range(1200))
    chunks = Researcher._chunk(text, size=500, overlap=50)
    assert len(chunks) >= 3
    assert all(isinstance(c, str) and c for c in chunks)


def test_chunk_overlap():
    text = " ".join(f"w{i}" for i in range(600))
    chunks = Researcher._chunk(text, size=500, overlap=50)
    # второй чанк должен начинаться с w450 (500 - 50)
    assert chunks[1].startswith("w450 ")
