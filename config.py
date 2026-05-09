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
# Дефолтный контекст Sanda — работает даже без /brand_init и без БД
BRAND_NICHE    = os.getenv("BRAND_NICHE",    "fintech / личные финансы / Казахстан")
BRAND_TONE     = os.getenv("BRAND_TONE",     "дружелюбный, прямой, простой — как умный друг который разбирается в деньгах")
BRAND_LANGUAGE = os.getenv("BRAND_LANGUAGE", "русский (с учётом казахстанской специфики)")
BRAND_AUDIENCE = os.getenv("BRAND_AUDIENCE", "жители Казахстана 22-35 лет: молодые специалисты, молодые семьи, начинающие предприниматели")

# ─── Sanda brand context (встроенный, не требует /brand_init) ────
BRAND_NAME = "Sanda"
BRAND_TAGLINE = "Знай, сколько можешь потратить сегодня"
BRAND_WEBSITE = "sandawallet.kz / sandawallet.com"
BRAND_STAGE = "стартап, готовится к запуску в App Store"
BRAND_PRODUCT = """Sanda — мобильное приложение для личных финансов (iOS/Android).
Главная идея: в любой момент показывать одну ключевую цифру — «сколько ты можешь потратить сегодня» с учётом всех планов, сбережений и обязательств.
Ключевые экраны: Сегодня (дашборд), Планы (бюджеты), Капитал (счета, сбережения, кредиты), Статистика.
Технологии: React + TypeScript + Capacitor + Firebase. Валюта: тенге (₸).
Аутентификация: Google Sign-In, Apple Sign-In, гостевой режим."""
BRAND_POSITIONING = """Конкуренты: CoinKeeper, Money Manager, встроенная аналитика Kaspi, Excel.
Отличие: один экран — одна цифра. Умный дневной бюджет, тёмный минималистичный дизайн,
геймификация (streak), поддержка казахстанской специфики (Kaspi, рассрочки, тенге)."""

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
