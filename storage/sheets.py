"""
Утилита для работы с Google Sheets.

Использует Service Account — никаких OAuth-окон, работает на сервере (Railway).

Настройка (один раз):
1. Зайди в https://console.cloud.google.com
2. Создай проект → включи Google Sheets API
3. IAM → Service Accounts → Create → скачай JSON-ключ
4. Скопируй всё содержимое JSON-ключа в переменную окружения GOOGLE_SERVICE_ACCOUNT_JSON
5. Создай Google Sheet, добавь в него email сервис-аккаунта (поле client_email) как редактора
6. Скопируй ID таблицы из URL (https://docs.google.com/spreadsheets/d/<<SPREADSHEET_ID>>/edit)
7. Добавь GOOGLE_SHEETS_ID в переменные Railway
"""
import json
import logging
import os
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)

# ── Ленивая инициализация клиента ─────────────────────────────────────────────
_gc = None


def _get_client():
    """Возвращает авторизованный gspread клиент (создаётся один раз)."""
    global _gc
    if _gc is not None:
        return _gc

    try:
        import gspread
        from google.oauth2.service_account import Credentials

        sa_json = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "")
        if not sa_json:
            logger.warning("[Sheets] GOOGLE_SERVICE_ACCOUNT_JSON не задан — Google Sheets отключён")
            return None

        sa_info = json.loads(sa_json)
        scopes = [
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive",
        ]
        creds = Credentials.from_service_account_info(sa_info, scopes=scopes)
        _gc = gspread.authorize(creds)
        logger.info("[Sheets] Авторизация Google Sheets успешна")
        return _gc

    except Exception as e:
        logger.error(f"[Sheets] Ошибка авторизации: {e}")
        return None


def _get_sheet(spreadsheet_id: str, worksheet_title: str = "Контент-план"):
    """Открывает (или создаёт) нужный лист в таблице."""
    gc = _get_client()
    if not gc:
        return None

    try:
        spreadsheet = gc.open_by_key(spreadsheet_id)
    except Exception as e:
        logger.error(f"[Sheets] Не удалось открыть таблицу {spreadsheet_id}: {e}")
        return None

    # Ищем лист с нужным именем
    try:
        ws = spreadsheet.worksheet(worksheet_title)
    except Exception:
        # Создаём новый лист
        try:
            ws = spreadsheet.add_worksheet(title=worksheet_title, rows=500, cols=10)
            logger.info(f"[Sheets] Создан лист '{worksheet_title}'")
        except Exception as e:
            logger.error(f"[Sheets] Не удалось создать лист: {e}")
            return None

    return ws


# ── Публичные функции ──────────────────────────────────────────────────────────

def write_content_plan(items: list[dict], spreadsheet_id: Optional[str] = None) -> str:
    """
    Записывает контент-план в Google Sheets.

    items — список словарей: [{topic, description, platform, scheduled}, ...]
    spreadsheet_id — ID таблицы (если None, берём из env GOOGLE_SHEETS_ID)

    Возвращает URL листа или сообщение об ошибке.
    """
    if not spreadsheet_id:
        spreadsheet_id = os.getenv("GOOGLE_SHEETS_ID", "")
    if not spreadsheet_id:
        return "⚠️ GOOGLE_SHEETS_ID не задан — таблица не обновлена"

    ws = _get_sheet(spreadsheet_id)
    if not ws:
        return "⚠️ Не удалось подключиться к Google Sheets"

    try:
        # Заголовки (только если лист пустой)
        existing = ws.get_all_values()
        header = ["#", "Тема", "Описание", "Платформа", "Дата", "Статус", "Добавлено"]

        if not existing or existing[0] != header:
            ws.clear()
            ws.append_row(header)
            # Форматируем заголовок жирным
            try:
                ws.format("A1:G1", {
                    "textFormat": {"bold": True},
                    "backgroundColor": {"red": 0.0, "green": 0.53, "blue": 0.44},  # #00876f
                })
            except Exception:
                pass

        # Находим следующий номер строки
        all_rows = ws.get_all_values()
        next_num = max(1, len(all_rows))  # строк уже есть (включая заголовок)

        # Добавляем строки
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
                now,
            ])

        ws.append_rows(rows_to_add, value_input_option="USER_ENTERED")
        logger.info(f"[Sheets] Добавлено {len(rows_to_add)} строк в таблицу")

        # Возвращаем ссылку
        sheet_url = f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}/edit"
        return f"📊 [Открыть таблицу]({sheet_url}) — добавлено {len(rows_to_add)} тем"

    except Exception as e:
        logger.error(f"[Sheets] Ошибка записи: {e}")
        return f"⚠️ Ошибка записи в таблицу: {e}"


def is_sheets_enabled() -> bool:
    """Проверяет, настроена ли интеграция с Google Sheets."""
    return bool(
        os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "")
        and os.getenv("GOOGLE_SHEETS_ID", "")
    )
