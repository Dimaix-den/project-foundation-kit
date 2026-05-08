"""
SQLite storage — хранит контент-план, черновики, брендбук и историю публикаций.
"""
import sqlite3
import json
from datetime import datetime
from config import DATABASE_PATH


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """Создаёт таблицы при первом запуске."""
    with get_conn() as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS brand (
            key   TEXT PRIMARY KEY,
            value TEXT
        );

        CREATE TABLE IF NOT EXISTS content_plan (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            topic       TEXT NOT NULL,
            description TEXT,
            platform    TEXT DEFAULT 'telegram',
            scheduled   TEXT,
            status      TEXT DEFAULT 'planned',
            created_at  TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS drafts (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            plan_id     INTEGER REFERENCES content_plan(id),
            agent       TEXT,
            title       TEXT,
            body        TEXT NOT NULL,
            visual_prompt TEXT,
            status      TEXT DEFAULT 'draft',
            created_at  TEXT DEFAULT (datetime('now')),
            updated_at  TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS published (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            draft_id    INTEGER REFERENCES drafts(id),
            channel     TEXT,
            message_id  INTEGER,
            published_at TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS chat_history (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id     INTEGER,
            role        TEXT,
            content     TEXT,
            agent       TEXT,
            created_at  TEXT DEFAULT (datetime('now'))
        );
        """)
    print("✅ База данных инициализирована")


# ─── Brand ───────────────────────────────────────────────────────

def set_brand(key: str, value: str):
    with get_conn() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO brand(key, value) VALUES (?,?)", (key, value)
        )

def get_brand(key: str, default: str = "") -> str:
    with get_conn() as conn:
        row = conn.execute("SELECT value FROM brand WHERE key=?", (key,)).fetchone()
    return row["value"] if row else default

def get_all_brand() -> dict:
    with get_conn() as conn:
        rows = conn.execute("SELECT key, value FROM brand").fetchall()
    return {r["key"]: r["value"] for r in rows}


# ─── Content plan ────────────────────────────────────────────────

def add_plan_items(items: list[dict]) -> list[int]:
    ids = []
    with get_conn() as conn:
        for item in items:
            cur = conn.execute(
                "INSERT INTO content_plan(topic, description, platform, scheduled) VALUES (?,?,?,?)",
                (item.get("topic"), item.get("description"), item.get("platform", "telegram"), item.get("scheduled")),
            )
            ids.append(cur.lastrowid)
    return ids

def get_plan(status: str = "planned") -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM content_plan WHERE status=? ORDER BY scheduled, id", (status,)
        ).fetchall()
    return [dict(r) for r in rows]

def update_plan_status(plan_id: int, status: str):
    with get_conn() as conn:
        conn.execute("UPDATE content_plan SET status=? WHERE id=?", (status, plan_id))


# ─── Drafts ──────────────────────────────────────────────────────

def save_draft(
    body: str,
    title: str = "",
    agent: str = "copywriter",
    visual_prompt: str = "",
    plan_id: int = None,
) -> int:
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO drafts(plan_id, agent, title, body, visual_prompt) VALUES (?,?,?,?,?)",
            (plan_id, agent, title, body, visual_prompt),
        )
    return cur.lastrowid

def get_draft(draft_id: int) -> dict | None:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM drafts WHERE id=?", (draft_id,)).fetchone()
    return dict(row) if row else None

def get_drafts(status: str = "draft") -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM drafts WHERE status=? ORDER BY created_at DESC", (status,)
        ).fetchall()
    return [dict(r) for r in rows]

def update_draft_status(draft_id: int, status: str):
    with get_conn() as conn:
        conn.execute(
            "UPDATE drafts SET status=?, updated_at=datetime('now') WHERE id=?",
            (status, draft_id),
        )

def update_draft_body(draft_id: int, body: str):
    with get_conn() as conn:
        conn.execute(
            "UPDATE drafts SET body=?, updated_at=datetime('now') WHERE id=?",
            (body, draft_id),
        )


# ─── Published ───────────────────────────────────────────────────

def save_published(draft_id: int, channel: str, message_id: int):
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO published(draft_id, channel, message_id) VALUES (?,?,?)",
            (draft_id, channel, message_id),
        )


# ─── Chat history (context per user) ─────────────────────────────

def add_to_history(user_id: int, role: str, content: str, agent: str = ""):
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO chat_history(user_id, role, content, agent) VALUES (?,?,?,?)",
            (user_id, role, content, agent),
        )

def get_history(user_id: int, limit: int = 10) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT role, content FROM chat_history
               WHERE user_id=? ORDER BY created_at DESC LIMIT ?""",
            (user_id, limit),
        ).fetchall()
    return [dict(r) for r in reversed(rows)]
