"""
Google Sheets — единственная база данных контент-плана.
Таблица = источник правды. Бот читает и пишет только сюда.
"""
import os
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional

logger = logging.getLogger(__name__)

# Казахстан UTC+5
KZ_TZ = timezone(timedelta(hours=5))

# Структура таблицы
HEADERS = ["#", "Дата", "Время", "Платформа", "Тема", "Текст поста", "Статус", "Опубликовано"]

# Статусы
STATUS_DRAFT     = "Черновик"
STATUS_READY     = "На публикацию"
STATUS_PUBLISHED = "Опубликовано"


def _sid() -> str:
    return os.getenv("GOOGLE_SHEETS_ID", "")


def _get_client():
    sa_json = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "")
    if not sa_json:
        return None
    try:
        import gspread
        from google.oauth2.service_account import Credentials
        import json as _json
        creds = Credentials.from_service_account_info(
            _json.loads(sa_json),
            scopes=["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"],
        )
        return gspread.authorize(creds)
    except Exception as e:
        logger.error(f"[Sheets] Ошибка авторизации: {e}")
        return None


def _get_sheet(sid: str = None):
    client = _get_client()
    if not client:
        return None
    sid = sid or _sid()
    if not sid:
        return None
    try:
        return client.open_by_key(sid).sheet1
    except Exception as e:
        logger.error(f"[Sheets] Ошибка открытия: {e}")
        return None


def is_enabled() -> bool:
    return bool(os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON") and os.getenv("GOOGLE_SHEETS_ID"))


def sheet_url() -> str:
    sid = _sid()
    return f"https://docs.google.com/spreadsheets/d/{sid}" if sid else ""


def _ensure_headers(ws):
    """Создаёт заголовки если таблица пустая."""
    try:
        first = ws.row_values(1)
        if not first or first[0] != "#":
            ws.insert_row(HEADERS, 1)
            ws.format("A1:H1", {
                "textFormat": {"bold": True},
                "backgroundColor": {"red": 0.0, "green": 0.53, "blue": 0.44},
            })
    except Exception as e:
        logger.warning(f"[Sheets] ensure_headers: {e}")


def _next_id(ws) -> int:
    """Возвращает следующий порядковый номер."""
    try:
        vals = ws.col_values(1)  # колонка "#"
        nums = [int(v) for v in vals[1:] if v.strip().isdigit()]
        return max(nums) + 1 if nums else 1
    except Exception:
        return 1


def add_posts(posts: list[dict]) -> str:
    """
    Добавляет посты в таблицу.
    Возвращает URL таблицы или строку с ошибкой.
    """
    if not posts:
        return "⚠️ Нет постов для записи"
    ws = _get_sheet()
    if not ws:
        return "⚠️ Не удалось подключиться к Google Sheets"
    try:
        _ensure_headers(ws)
        next_id = _next_id(ws)
        rows = []
        for i, post in enumerate(posts):
            row = [
                next_id + i,
                post.get("date", ""),
                post.get("time", "10:00"),
                post.get("platform", "Telegram"),
                post.get("topic", ""),
                post.get("text", ""),
                post.get("status", STATUS_DRAFT),
                "",  # Опубликовано — пусто
            ]
            rows.append(row)
        ws.append_rows(rows, value_input_option="USER_ENTERED")
        logger.info(f"[Sheets] Добавлено {len(rows)} постов")
        return sheet_url()
    except Exception as e:
        logger.error(f"[Sheets] Ошибка add_posts: {e}")
        return f"⚠️ Ошибка записи: {e}"


def get_posts_to_publish() -> list[dict]:
    """
    Возвращает посты со статусом 'На публикацию',
    у которых дата+время <= сейчас (по Алматы UTC+5).
    """
    ws = _get_sheet()
    if not ws:
        return []
    try:
        all_vals = ws.get_all_values()
        if len(all_vals) < 2:
            return []
        now = datetime.now(KZ_TZ)
        result = []
        for row_idx, row in enumerate(all_vals[1:], start=2):  # row_idx — номер строки в Sheets
            if len(row) < 7:
                continue
            status = row[6].strip()
            if status != STATUS_READY:
                continue
            date_str = row[1].strip()
            time_str = row[2].strip() or "10:00"
            try:
                dt = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")
                dt = dt.replace(tzinfo=KZ_TZ)
            except ValueError:
                logger.warning(f"[Sheets] Невалидная дата в строке {row_idx}: '{date_str} {time_str}'")
                continue
            if dt <= now:
                result.append({
                    "_row": row_idx,
                    "id": row[0],
                    "date": date_str,
                    "time": time_str,
                    "platform": row[3],
                    "topic": row[4],
                    "text": row[5],
                    "status": status,
                })
        return result
    except Exception as e:
        logger.error(f"[Sheets] Ошибка get_posts_to_publish: {e}")
        return []


def get_post_by_number(n: int) -> Optional[dict]:
    """Возвращает пост по номеру (#) из первой колонки."""
    ws = _get_sheet()
    if not ws:
        return None
    try:
        all_vals = ws.get_all_values()
        for row_idx, row in enumerate(all_vals[1:], start=2):
            if row and str(row[0]).strip() == str(n):
                return {
                    "_row": row_idx,
                    "id": row[0],
                    "date": row[1] if len(row) > 1 else "",
                    "time": row[2] if len(row) > 2 else "",
                    "platform": row[3] if len(row) > 3 else "",
                    "topic": row[4] if len(row) > 4 else "",
                    "text": row[5] if len(row) > 5 else "",
                    "status": row[6] if len(row) > 6 else "",
                }
        return None
    except Exception as e:
        logger.error(f"[Sheets] get_post_by_number({n}): {e}")
        return None


def mark_published(row_idx: int):
    """Ставит статус 'Опубликовано' и время публикации."""
    ws = _get_sheet()
    if not ws:
        return
    try:
        now_str = datetime.now(KZ_TZ).strftime("%Y-%m-%d %H:%M")
        ws.update_cell(row_idx, 7, STATUS_PUBLISHED)   # Статус
        ws.update_cell(row_idx, 8, now_str)             # Опубликовано
        logger.info(f"[Sheets] Строка {row_idx} → Опубликовано ({now_str})")
    except Exception as e:
        logger.error(f"[Sheets] mark_published({row_idx}): {e}")


def update_status(row_idx: int, status: str):
    """Обновляет статус произвольной строки."""
    ws = _get_sheet()
    if not ws:
        return
    try:
        ws.update_cell(row_idx, 7, status)
    except Exception as e:
        logger.error(f"[Sheets] update_status({row_idx}): {e}")
