"""
Утилита для работы с Google Sheets.
Service Account — без OAuth, работает на Railway.
"""
import json
import logging
import os
import re
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)

_gc = None


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
            ws = spreadsheet.add_worksheet(title=worksheet_title, rows=500, cols=12)
        except Exception as e:
            logger.error(f"[Sheets] Не удалось создать лист: {e}")
            return None
    return ws


# Заголовки таблицы (с колонкой текста)
HEADERS = ["#", "Тема", "Описание", "Платформа", "Дата", "Статус", "Текст к посту", "Добавлено"]


def write_content_plan(items: list[dict], spreadsheet_id: Optional[str] = None) -> str:
    """
    Записывает контент-план в Google Sheets (с пустой колонкой 'Текст к посту').
    items — [{topic, description, platform, scheduled, body(optional)}, ...]
    """
    if not spreadsheet_id:
        spreadsheet_id = os.getenv("GOOGLE_SHEETS_ID", "")
    if not spreadsheet_id:
        return "⚠️ GOOGLE_SHEETS_ID не задан"

    ws = _get_sheet(spreadsheet_id)
    if not ws:
        return "⚠️ Не удалось подключиться к Google Sheets"

    try:
        existing = ws.get_all_values()
        if not existing or existing[0] != HEADERS:
            ws.clear()
            ws.append_row(HEADERS)
            try:
                ws.format(f"A1:{chr(64+len(HEADERS))}1", {
                    "textFormat": {"bold": True},
                    "backgroundColor": {"red": 0.0, "green": 0.53, "blue": 0.44},
                })
            except Exception:
                pass

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
                item.get("body", ""),   # Текст к посту (пусто если не передан)
                now,
            ])

        ws.append_rows(rows_to_add, value_input_option="USER_ENTERED")
        logger.info(f"[Sheets] Добавлено {len(rows_to_add)} строк")

        sheet_url = f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}/edit"
        return f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}/edit"

    except Exception as e:
        logger.error(f"[Sheets] Ошибка записи: {e}")
        return f"⚠️ Ошибка записи в таблицу: {e}"


def write_texts_to_plan(texts: list[str], spreadsheet_id: Optional[str] = None) -> str:
    """
    Записывает тексты постов в колонку 'Текст к посту'.
    texts — список текстов в том же порядке что и строки в таблице (начиная со строки 2).
    """
    if not spreadsheet_id:
        spreadsheet_id = os.getenv("GOOGLE_SHEETS_ID", "")
    if not spreadsheet_id:
        return "⚠️ GOOGLE_SHEETS_ID не задан"

    ws = _get_sheet(spreadsheet_id)
    if not ws:
        return "⚠️ Не удалось подключиться к Google Sheets"

    try:
        all_values = ws.get_all_values()
        if not all_values:
            return "⚠️ Таблица пуста — сначала создай контент-план"

        # Находим индекс колонки "Текст к посту"
        header = all_values[0]
        try:
            text_col_idx = header.index("Текст к посту")
        except ValueError:
            # Колонки нет — добавляем
            text_col_idx = len(header)
            # Обновляем заголовок
            ws.update_cell(1, text_col_idx + 1, "Текст к посту")

        # Обновляем строки с текстами (строка 2 = индекс 1)
        data_rows = all_values[1:]  # без заголовка
        updated = 0
        for i, text in enumerate(texts):
            if i >= len(data_rows):
                break
            row_num = i + 2  # в Sheets строки с 1, плюс заголовок
            col_num = text_col_idx + 1
            ws.update_cell(row_num, col_num, text)
            updated += 1

        sheet_url = f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}/edit"
        return f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}/edit|{updated}"

    except Exception as e:
        logger.error(f"[Sheets] Ошибка записи текстов: {e}")
        return f"⚠️ Ошибка: {e}"


def is_sheets_enabled() -> bool:
    return bool(
        os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "")
        and os.getenv("GOOGLE_SHEETS_ID", "")
    )
