"""
Утилита для загрузки файлов на Google Drive.
Использует тот же Service Account что и Google Sheets.

Настройка:
1. Создай папку на Google Drive
2. Расшарь её с sanda-content-bot@sanda-e5af1.iam.gserviceaccount.com (Редактор)
3. Скопируй ID папки из URL и добавь в Railway: GOOGLE_DRIVE_FOLDER_ID=...
"""
import io
import json
import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)


def _get_drive_service():
    """Возвращает авторизованный Drive клиент."""
    try:
        from googleapiclient.discovery import build
        from google.oauth2.service_account import Credentials

        sa_json = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "")
        if not sa_json:
            return None, "GOOGLE_SERVICE_ACCOUNT_JSON не задан"

        sa_info = json.loads(sa_json)
        scopes = ["https://www.googleapis.com/auth/drive"]
        creds = Credentials.from_service_account_info(sa_info, scopes=scopes)
        service = build("drive", "v3", credentials=creds)
        return service, None
    except Exception as e:
        return None, str(e)


def upload_image(image_bytes: bytes, filename: str, folder_id: Optional[str] = None) -> str:
    """
    Загружает изображение на Google Drive.
    Возвращает публичную ссылку или сообщение об ошибке.
    """
    if not folder_id:
        folder_id = os.getenv("GOOGLE_DRIVE_FOLDER_ID", "")
    if not folder_id:
        return "⚠️ GOOGLE_DRIVE_FOLDER_ID не задан"

    service, err = _get_drive_service()
    if not service:
        return f"⚠️ Ошибка Drive: {err}"

    try:
        from googleapiclient.http import MediaIoBaseUpload

        file_metadata = {
            "name": filename,
            "parents": [folder_id],
        }
        media = MediaIoBaseUpload(
            io.BytesIO(image_bytes),
            mimetype="image/png",
            resumable=False,
        )
        file = service.files().create(
            body=file_metadata,
            media_body=media,
            fields="id, webViewLink",
        ).execute()

        # Делаем файл публичным (только просмотр)
        service.permissions().create(
            fileId=file["id"],
            body={"type": "anyone", "role": "reader"},
        ).execute()

        link = file.get("webViewLink", "")
        logger.info(f"[Drive] Загружено: {filename} → {link}")
        return link

    except Exception as e:
        logger.error(f"[Drive] Ошибка загрузки: {e}")
        return f"⚠️ Ошибка загрузки на Drive: {e}"


def is_drive_enabled() -> bool:
    return bool(
        os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "")
        and os.getenv("GOOGLE_DRIVE_FOLDER_ID", "")
    )
