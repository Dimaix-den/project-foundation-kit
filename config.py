import os
from dotenv import load_dotenv

load_dotenv()

# ─── API Keys ────────────────────────────────────────────────────
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")

# ─── Model ───────────────────────────────────────────────────────
# claude-haiku-4-5-20251001   → самый дешёвый, быстрый
# claude-sonnet-4-6           → баланс качества и цены (рекомендуем)
# claude-opus-4-6             → лучшее качество, дороже
MODEL = os.getenv("MODEL", "claude-sonnet-4-6")

# ─── Database ────────────────────────────────────────────────────
DATABASE_PATH = os.getenv("DATABASE_PATH", "content_team.db")

# ─── Brand settings ──────────────────────────────────────────────
BRAND_NICHE      = os.getenv("BRAND_NICHE",    "B2B бизнес и предпринимательство")
BRAND_TONE       = os.getenv("BRAND_TONE",     "профессиональный, экспертный, с практической пользой")
BRAND_LANGUAGE   = os.getenv("BRAND_LANGUAGE", "русский")
BRAND_AUDIENCE   = os.getenv("BRAND_AUDIENCE", "предприниматели, руководители, B2B-специалисты")

# ─── Telegram Topic IDs ──────────────────────────────────────────
# После создания суперчата с топиками — вставь ID каждого топика сюда.
# Как получить ID: включи бота в чат, напиши в топик /topic_id
# 0 = общий чат (без топиков)
TOPIC_GENERAL   = int(os.getenv("TOPIC_GENERAL",   "0"))
TOPIC_ANALYTICS = int(os.getenv("TOPIC_ANALYTICS", "0"))
TOPIC_DRAFTS    = int(os.getenv("TOPIC_DRAFTS",    "0"))
TOPIC_VISUALS   = int(os.getenv("TOPIC_VISUALS",   "0"))
TOPIC_REVIEW    = int(os.getenv("TOPIC_REVIEW",    "0"))
TOPIC_PUBLISHED = int(os.getenv("TOPIC_PUBLISHED", "0"))

# ─── Publishing channel ──────────────────────────────────────────
# ID или @username канала, куда публикуется одобренный контент
PUBLISH_CHANNEL = os.getenv("PUBLISH_CHANNEL", "")

# ─── Allowed users ───────────────────────────────────────────────
# Telegram user IDs, которым разрешено управлять ботом
# Оставь пустым — бот ответит всем
ALLOWED_USER_IDS_RAW = os.getenv("ALLOWED_USER_IDS", "")
ALLOWED_USER_IDS = (
    [int(uid.strip()) for uid in ALLOWED_USER_IDS_RAW.split(",") if uid.strip()]
    if ALLOWED_USER_IDS_RAW
    else []
)
