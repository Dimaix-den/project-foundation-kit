"""
Утилита для работы с Google Sheets.
Service Account — без OAuth, работает на Railway.
Поддерживает: чтение, запись, обновление строк/ячеек/столбцов, удаление.
"""
import json
import logging
import os
import re
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)
_gc = None

HEADERS = ["#", "Тема", "Описание", "Платформа", "Дата", "Статус", "Текст к посту", "Добавлено"]


def _get_client():
    global _gc
    if _gc is not None:
        return _gc
    try:
        import gspread
        from google.oauth2.service_account import Credentials
        sa_json = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "")
        if not sa_json:
            return None
        sa_info = json.loads(sa_json)
        scopes = [
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive",
        ]
        creds = Credentials.from_service_account_info(sa_info, scopes=scopes)
        _gc = gspread.authorize(creds)
        return _gc
    except Exception as e:
        logger.error(f"[Sheets] Ошибка авторизации: {e}")
        return None


def _get_sheet(spreadsheet_id: str, worksheet_title: str = "Контент-план"):
    gc = _get_client()
    if not gc:
        return None
    try:
        spreadsheet = gc.open_by_key(spreadsheet_id)
    except Exception as e:
        logger.error(f"[Sheets] Не удалось открыть таблицу: {e}")
        return None
    try:
        ws = spreadsheet.worksheet(worksheet_title)
    except Exception:
        try:
            ws = spreadsheet.add_worksheet(title=worksheet_title, rows=500, cols=20)
        except Exception as e:
            logger.error(f"[Sheets] Не удалось создать лист: {e}")
            return None
    return ws


def _sid() -> str:
    return os.getenv("GOOGLE_SHEETS_ID", "")


def _sheet_url(sid: str) -> str:
    return f"https://docs.google.com/spreadsheets/d/{sid}/edit"


# ── READ ──────────────────────────────────────────────────────────────────────

def read_sheet(spreadsheet_id: Optional[str] = None) -> list:
    """
    Читает таблицу и возвращает список строк как словарей {колонка: значение}.
    Строка 1 = заголовки, остальные = данные.
    """
    sid = spreadsheet_id or _sid()
    if not sid:
        return []
    ws = _get_sheet(sid)
    if not ws:
        return []
    try:
        all_values = ws.get_all_values()
        if not all_values:
            return []
        headers = all_values[0]
        rows = []
        for i, row in enumerate(all_values[1:], start=2):
            # Дополняем строку пустыми значениями если короче заголовков
            padded = row + [""] * (len(headers) - len(row))
            rows.append({"_row": i, **dict(zip(headers, padded))})
        return rows
    except Exception as e:
        logger.error(f"[Sheets] Ошибка чтения: {e}")
        return []


def read_sheet_as_text(spreadsheet_id: Optional[str] = None) -> str:
    """Возвращает читаемое текстовое представление таблицы для передачи в LLM."""
    rows = read_sheet(spreadsheet_id)
    if not rows:
        return "Таблица пуста или недоступна."
    lines = []
    for r in rows:
        row_num = r["_row"]
        topic = r.get("Тема", "")
        desc = r.get("Описание", "")
        date = r.get("Дата", "")
        platform = r.get("Платформа", "")
        status = r.get("Статус", "")
        text_preview = r.get("Текст к посту", "")[:60] + ("..." if len(r.get("Текст к посту", "")) > 60 else "")
        lines.append(f"Строка {row_num}: [{date}] {platform} | {topic} | {desc} | {status} | текст: {text_preview or '—'}")
    return "\n".join(lines)


# ── WRITE / CREATE ─────────────────────────────────────────────────────────────

def write_content_plan(items: list, spreadsheet_id: Optional[str] = None) -> str:
    """Добавляет строки в конец таблицы."""
    sid = spreadsheet_id or _sid()
    if not sid:
        return "⚠️ GOOGLE_SHEETS_ID не задан"
    ws = _get_sheet(sid)
    if not ws:
        return "⚠️ Не удалось подключиться к Google Sheets"
    try:
        existing = ws.get_all_values()
        if not existing or existing[0] != HEADERS:
            ws.clear()
            ws.append_row(HEADERS)
            _format_header(ws)
        all_rows = ws.get_all_values()
        next_num = max(1, len(all_rows))
        now = datetime.now().strftime("%d.%m.%Y %H:%M")
        rows_to_add = []
        for i, item in enumerate(items):
            rows_to_add.append([
                next_num + i,
                item.get("topic", ""),
                item.get("description", ""),
                item.get("platform", "telegram"),
                item.get("scheduled", ""),
                "📝 Черновик",
                item.get("body", ""),
                now,
            ])
        ws.append_rows(rows_to_add, value_input_option="USER_ENTERED")
        logger.info(f"[Sheets] Добавлено {len(rows_to_add)} строк")
        return _sheet_url(sid)
    except Exception as e:
        logger.error(f"[Sheets] Ошибка записи: {e}")
        return f"⚠️ Ошибка: {e}"


def rewrite_content_plan(items: list, spreadsheet_id: Optional[str] = None) -> str:
    """Полностью перезаписывает таблицу."""
    sid = spreadsheet_id or _sid()
    if not sid:
        return "⚠️ GOOGLE_SHEETS_ID не задан"
    ws = _get_sheet(sid)
    if not ws:
        return "⚠️ Не удалось подключиться к Google Sheets"
    try:
        ws.clear()
        ws.append_row(HEADERS)
        _format_header(ws)
        now = datetime.now().strftime("%d.%m.%Y %H:%M")
        rows = []
        for i, item in enumerate(items, start=1):
            rows.append([
                i, item.get("topic", ""), item.get("description", ""),
                item.get("platform", "telegram"), item.get("scheduled", ""),
                "📝 Черновик", item.get("body", ""), now,
            ])
        if rows:
            ws.append_rows(rows, value_input_option="USER_ENTERED")
        return _sheet_url(sid)
    except Exception as e:
        return f"⚠️ Ошибка: {e}"


# ── UPDATE ────────────────────────────────────────────────────────────────────

def apply_changes(changes: list, spreadsheet_id: Optional[str] = None) -> str:
    """
    Применяет список изменений к таблице.
    changes — список словарей:
      {"action": "update", "row": 3, "field": "Статус", "value": "✅ Готово"}
      {"action": "update_by_topic", "topic": "Рассрочки Kaspi", "field": "Описание", "value": "новый текст"}
      {"action": "add", "topic": "Новая тема", "description": "...", "platform": "telegram", "scheduled": "2026-05-12"}
      {"action": "delete_by_topic", "topic": "Тема для удаления"}
      {"action": "add_column", "name": "Ссылка на пост"}
    Возвращает URL таблицы или ошибку.
    """
    sid = spreadsheet_id or _sid()
    if not sid:
        return "⚠️ GOOGLE_SHEETS_ID не задан"
    ws = _get_sheet(sid)
    if not ws:
        return "⚠️ Не удалось подключиться к Google Sheets"

    if not changes:
        return "⚠️ Нет изменений для применения"

    try:
        all_values = ws.get_all_values()
        if not all_values:
            return "⚠️ Таблица пуста"
        headers = list(all_values[0])

        batch_updates = []
        rows_to_delete = []
        rows_to_add = []
        applied = 0

        for change in changes:
            action = change.get("action", "update")

            if action == "add_column":
                col_name = change.get("name", "").strip()
                if col_name and col_name not in headers:
                    new_col = len(headers) + 1
                    ws.update_cell(1, new_col, col_name)
                    headers.append(col_name)
                    try:
                        ws.format(f"{chr(64+new_col)}1", {"textFormat": {"bold": True}})
                    except Exception:
                        pass
                    applied += 1

            elif action in ("update", "update_by_topic"):
                field = change.get("field", "")
                value = change.get("value", "")
                if field not in headers:
                    continue
                col_idx = headers.index(field) + 1

                if action == "update" and change.get("row"):
                    row_num = int(change["row"])
                    batch_updates.append({"range": f"{_col_letter(col_idx)}{row_num}", "values": [[value]]})
                    applied += 1

                elif action == "update_by_topic":
                    topic = change.get("topic", "").lower()
                    topic_col = headers.index("Тема") if "Тема" in headers else -1
                    if topic_col == -1:
                        continue
                    for row_num, row in enumerate(all_values[1:], start=2):
                        padded = row + [""] * (len(headers) - len(row))
                        if topic in padded[topic_col].lower():
                            batch_updates.append({"range": f"{_col_letter(col_idx)}{row_num}", "values": [[value]]})
                            applied += 1
                            break

            elif action == "delete_by_topic":
                topic = change.get("topic", "").lower()
                topic_col = headers.index("Тема") if "Тема" in headers else -1
                if topic_col == -1:
                    continue
                for row_num, row in enumerate(all_values[1:], start=2):
                    padded = row + [""] * (len(headers) - len(row))
                    if topic in padded[topic_col].lower():
                        rows_to_delete.append(row_num)
                        applied += 1
                        break

            elif action == "add":
                now = datetime.now().strftime("%d.%m.%Y %H:%M")
                rows_to_add.append([
                    "", change.get("topic", ""), change.get("description", ""),
                    change.get("platform", "telegram"), change.get("scheduled", ""),
                    "📝 Черновик", change.get("body", ""), now,
                ])
                applied += 1

        # Применяем batch updates
        if batch_updates:
            ws.batch_update(batch_updates, value_input_option="USER_ENTERED")

        # Добавляем новые строки
        if rows_to_add:
            ws.append_rows(rows_to_add, value_input_option="USER_ENTERED")

        # Удаляем строки (с конца, чтобы не сбить индексы)
        for row_num in sorted(rows_to_delete, reverse=True):
            ws.delete_rows(row_num)

        logger.info(f"[Sheets] Применено {applied} изменений")
        return _sheet_url(sid)

    except Exception as e:
        logger.error(f"[Sheets] Ошибка apply_changes: {e}")
        return f"⚠️ Ошибка: {e}"


def write_texts_to_plan(texts: list, spreadsheet_id: Optional[str] = None) -> str:
    """Записывает тексты постов в колонку 'Текст к посту' (по порядку строк)."""
    sid = spreadsheet_id or _sid()
    if not sid:
        return "⚠️ GOOGLE_SHEETS_ID не задан"
    ws = _get_sheet(sid)
    if not ws:
        return "⚠️ Не удалось подключиться к Google Sheets"
    try:
        all_values = ws.get_all_values()
        if not all_values:
            return "⚠️ Таблица пуста"
        headers = all_values[0]
        if "Текст к посту" in headers:
            text_col_idx = headers.index("Текст к посту")
        else:
            text_col_idx = len(headers)
            ws.update_cell(1, text_col_idx + 1, "Текст к посту")
            try:
                ws.format(f"{chr(65+text_col_idx)}1", {"textFormat": {"bold": True}})
            except Exception:
                pass

        data_rows = all_values[1:]
        n = min(len(texts), len(data_rows))
        if n == 0:
            return "⚠️ Нет строк для обновления"

        col_letter = _col_letter(text_col_idx + 1)
        updates = [{"range": f"{col_letter}{i+2}", "values": [[texts[i]]]} for i in range(n)]
        ws.batch_update(updates, value_input_option="USER_ENTERED")
        logger.info(f"[Sheets] Записано {n} текстов")
        return f"{_sheet_url(sid)}|{n}"
    except Exception as e:
        logger.error(f"[Sheets] Ошибка write_texts: {e}")
        return f"⚠️ Ошибка: {e}"


# ── HELPERS ───────────────────────────────────────────────────────────────────

def _col_letter(col_idx: int) -> str:
    """Конвертирует номер колонки (1-based) в букву: 1→A, 27→AA и т.д."""
    result = ""
    while col_idx > 0:
        col_idx, remainder = divmod(col_idx - 1, 26)
        result = chr(65 + remainder) + result
    return result


def _format_header(ws):
    try:
        ws.format(f"A1:{_col_letter(len(HEADERS))}1", {
            "textFormat": {"bold": True},
            "backgroundColor": {"red": 0.0, "green": 0.53, "blue": 0.44},
        })
    except Exception:
        pass


def is_sheets_enabled() -> bool:
    return bool(os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "") and os.getenv("GOOGLE_SHEETS_ID", ""))
