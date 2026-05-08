"""Чтение PDF, DOCX, TXT, MD, HTML и URL."""
from __future__ import annotations

from pathlib import Path
from typing import Union

import httpx
from bs4 import BeautifulSoup


def read_file(source: Union[str, Path]) -> str:
    """Универсальное чтение: путь или URL."""
    if isinstance(source, str) and source.startswith(("http://", "https://")):
        return _read_url(source)
    path = Path(source)
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return _read_pdf(path)
    if suffix == ".docx":
        return _read_docx(path)
    if suffix in {".txt", ".md", ".html"}:
        return path.read_text(encoding="utf-8", errors="ignore")
    raise ValueError(f"Неподдерживаемый формат: {suffix}")


def _read_pdf(path: Path) -> str:
    from PyPDF2 import PdfReader

    reader = PdfReader(str(path))
    return "\n".join((page.extract_text() or "") for page in reader.pages)


def _read_docx(path: Path) -> str:
    import docx

    doc = docx.Document(str(path))
    return "\n".join(p.text for p in doc.paragraphs)


def _read_url(url: str) -> str:
    resp = httpx.get(url, timeout=30, follow_redirects=True)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")
    for tag in soup(["script", "style", "nav", "footer"]):
        tag.decompose()
    return soup.get_text(separator="\n", strip=True)
