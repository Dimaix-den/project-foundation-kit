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


HEADERS = ["#", "Тема", "Описание", "Платформа", "Дата", "Статус", "Текст к посту", "Добавлено"]


def write_content_plan(items: list, spreadsheet_id: Optional[str] = None) -> str:
    """Записывает контент-план в Google Sheets."""
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
                item.get("body", ""),
                now,
            ])

        ws.append_rows(rows_to_add, value_input_option="USER_ENTERED")
        logger.info(f"[Sheets] Добавлено {len(rows_to_add)} строк")
        return f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}/edit"

    except Exception as e:
        logger.error(f"[Sheets] Ошибка записи: {e}")
        return f"⚠️ Ошибка записи в таблицу: {e}"


def write_texts_to_plan(texts: list, spreadsheet_id: Optional[str] = None) -> str:
    """
    Записывает тексты постов в колонку 'Текст к посту'.
    Каждый элемент texts идёт в отдельную строку таблицы (начиная со строки 2).
    Использует batch_update для надёжности.
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

        header = all_values[0]

        # Находим или создаём колонку "Текст к посту"
        if "Текст к посту" in header:
            text_col_idx = header.index("Текст к посту")
        else:
            # Добавляем колонку после последней
            text_col_idx = len(header)
            ws.update_cell(1, text_col_idx + 1, "Текст к посту")
            try:
                ws.format(f"{chr(65+text_col_idx)}1", {"textFormat": {"bold": True}})
            except Exception:
                pass

        data_rows = all_values[1:]  # без заголовка
        n_rows = min(len(texts), len(data_rows))

        if n_rows == 0:
            return "⚠️ Нет строк для обновления"

        # Формируем batch_update — все ячейки за один запрос
        col_letter = chr(65 + text_col_idx)  # A=65, B=66, ...
        updates = []
        for i in range(n_rows):
            cell = f"{col_letter}{i + 2}"  # строка 2 = первая строка данных
            updates.append({
                "range": cell,
                "values": [[texts[i]]],
            })

        ws.batch_update(updates, value_input_option="USER_ENTERED")
        logger.info(f"[Sheets] Обновлено {n_rows} ячеек в колонке 'Текст к посту'")

        sheet_url = f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}/edit"
        return f"{sheet_url}|{n_rows}"

    except Exception as e:
        logger.error(f"[Sheets] Ошибка записи текстов: {e}")
        return f"⚠️ Ошибка: {e}"


def is_sheets_enabled() -> bool:
    return bool(
        os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "")
        and os.getenv("GOOGLE_SHEETS_ID", "")
    )


def update_plan_row(topic: str, field: str, value: str, spreadsheet_id: Optional[str] = None) -> str:
    """
    Обновляет конкретную ячейку в плане по теме поста.
    field — название колонки (например 'Тема', 'Описание', 'Дата', 'Статус', 'Текст к посту').
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
            return "⚠️ Таблица пуста"

        header = all_values[0]
        if field not in header:
            return f"⚠️ Колонка '{field}' не найдена"
        col_idx = header.index(field)

        # Ищем строку с нужной темой (по колонке "Тема")
        if "Тема" not in header:
            return "⚠️ Колонка 'Тема' не найдена"
        topic_col = header.index("Тема")

        for row_num, row in enumerate(all_values[1:], start=2):
            if len(row) > topic_col and topic.lower() in row[topic_col].lower():
                ws.update_cell(row_num, col_idx + 1, value)
                sheet_url = f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}/edit"
                return f"{sheet_url}"

        return f"⚠️ Тема '{topic}' не найдена в таблице"

    except Exception as e:
        logger.error(f"[Sheets] Ошибка обновления строки: {e}")
        return f"⚠️ Ошибка: {e}"


def rewrite_content_plan(items: list, spreadsheet_id: Optional[str] = None) -> str:
    """
    Полностью перезаписывает контент-план (используется при корректировке).
    """
    if not spreadsheet_id:
        spreadsheet_id = os.getenv("GOOGLE_SHEETS_ID", "")
    if not spreadsheet_id:
        return "⚠️ GOOGLE_SHEETS_ID не задан"

    ws = _get_sheet(spreadsheet_id)
    if not ws:
        return "⚠️ Не удалось подключиться к Google Sheets"

    try:
        ws.clear()
        ws.append_row(HEADERS)
        try:
            ws.format(f"A1:{chr(64+len(HEADERS))}1", {
                "textFormat": {"bold": True},
                "backgroundColor": {"red": 0.0, "green": 0.53, "blue": 0.44},
            })
        except Exception:
            pass

        now = datetime.now().strftime("%d.%m.%Y %H:%M")
        rows = []
        for i, item in enumerate(items, start=1):
            rows.append([
                i,
                item.get("topic", ""),
                item.get("description", ""),
                item.get("platform", "telegram"),
                item.get("scheduled", ""),
                "📝 Черновик",
                item.get("body", ""),
                now,
            ])
        ws.append_rows(rows, value_input_option="USER_ENTERED")

        sheet_url = f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}/edit"
        return f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}/edit"
    except Exception as e:
        return f"⚠️ Ошибка: {e}"
