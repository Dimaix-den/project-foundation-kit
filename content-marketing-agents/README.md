# AI Content Marketing Agents

Набор автономных AI-агентов на чистом Python, которые закрывают весь цикл контент-маркетинга: исследование продукта → копирайтинг → визуал → стратегия → публикация в Instagram, LinkedIn, Threads.

## Стек
Python 3.11+ · Anthropic Claude SDK · ChromaDB · Playwright · Replicate / DALL·E · Meta Graph API · LinkedIn API · Threads API

## Структура
```
content-marketing-agents/
├── agents/           # base_agent, researcher, seo_writer, visual_designer, strategist, publisher
├── orchestrator/     # планировщик задач между агентами
├── memory/           # обёртка ChromaDB + локальная векторная БД
├── tools/            # web_search, file_reader, image_gen
├── platforms/        # instagram, linkedin, threads
├── data/             # brand_book, product_docs, outputs
├── tests/
├── .env.example
├── requirements.txt
└── main.py
```

## План разработки
1. **Researcher** — *текущий этап*: ingestion документов в ChromaDB + веб-исследование
2. **SEOWriter** — копирайтер постов
3. **VisualDesigner** — генерация визуала
4. **Strategist** — контент-план на месяц
5. **Publisher** — автопубликация по расписанию

## Быстрый старт (Этап 1)
```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env  # заполнить ключи
python main.py research --input ./data/product_docs/
```

## Этап 1: Researcher
- Ingestion mode: читает локальные файлы (PDF, DOCX, TXT, MD, HTML)
- Web research mode: поиск через Claude `web_search` tool
- Interactive mode: диалог для уточнения профиля продукта
- Результат: ChromaDB + `data/outputs/research_report.md`

### CLI
| Команда | Описание |
|---|---|
| `python main.py research --input ./data/product_docs/` | Загрузить файлы из папки |
| `python main.py research --url https://example.com` | Загрузить контент с сайта |
| `python main.py research --interactive` | Интерактивный диалог |

## Соглашения по коду
- Type hints везде
- Docstrings (Google style)
- Pydantic-схемы для I/O агентов
- Тесты `tests/test_{agent}.py`
- Коммиты: `feat(researcher): add PDF ingestion`
