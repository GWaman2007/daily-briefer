"""SQLite database for preferences, events, and reply history."""
from __future__ import annotations

import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone, timedelta

from daily_briefer.config import Config


def _connect(config: Config) -> sqlite3.Connection:
    db_dir = os.path.dirname(config.db_path)
    if db_dir and not os.path.exists(db_dir):
        os.makedirs(db_dir, exist_ok=True)
    conn = sqlite3.connect(config.db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


@contextmanager
def get_conn(config: Config):
    conn = _connect(config)
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db(config: Config) -> None:
    """Create tables if they don't exist."""
    with get_conn(config) as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS user_preferences (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                keyword TEXT UNIQUE NOT NULL,
                weight INTEGER DEFAULT 5,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT NOT NULL,
                description TEXT NOT NULL,
                status TEXT DEFAULT 'pending',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS briefs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT UNIQUE NOT NULL,
                email_sent_at TEXT,
                preferences_snapshot TEXT,
                brief_content TEXT
            );

            CREATE TABLE IF NOT EXISTS reply_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email_subject TEXT NOT NULL,
                email_body TEXT NOT NULL,
                processed_at TEXT DEFAULT CURRENT_TIMESTAMP,
                changes_applied TEXT
            );
        """)


# --- User Preferences ---

def add_preference(config: Config, keyword: str, weight: int = 5) -> bool:
    """Add or increment a preference keyword."""
    with get_conn(config) as conn:
        row = conn.execute(
            "SELECT id, weight FROM user_preferences WHERE LOWER(keyword) = LOWER(?)",
            (keyword,),
        ).fetchone()
        if row:
            new_weight = max(row["weight"] + weight, weight)
            conn.execute(
                "UPDATE user_preferences SET weight = ?, created_at = CURRENT_TIMESTAMP WHERE id = ?",
                (new_weight, row["id"]),
            )
        else:
            conn.execute(
                "INSERT OR IGNORE INTO user_preferences (keyword, weight) VALUES (?, ?)",
                (keyword, weight),
            )
        return True


def remove_preference(config: Config, keyword: str) -> None:
    with get_conn(config) as conn:
        conn.execute(
            "DELETE FROM user_preferences WHERE LOWER(keyword) = LOWER(?)",
            (keyword,),
        )


def get_preferences(config: Config) -> list[dict]:
    with get_conn(config) as conn:
        rows = conn.execute(
            "SELECT keyword, weight FROM user_preferences ORDER BY weight DESC"
        ).fetchall()
        return [dict(r) for r in rows]


def get_top_keywords(config: Config, n: int = 20) -> list[str]:
    rows = get_preferences(config)
    return [r["keyword"] for r in rows[:n]]


def list_all_preferences(config: Config) -> list[dict]:
    return get_preferences(config)


# --- Events ---

def add_event(config: Config, date: str, description: str) -> int:
    """Add an event reminder. Returns event id."""
    with get_conn(config) as conn:
        cur = conn.execute(
            "INSERT INTO events (date, description, status) VALUES (?, ?, 'pending')",
            (date, description),
        )
        return cur.lastrowid


def remove_event(config: Config, event_id: int) -> None:
    with get_conn(config) as conn:
        conn.execute(
            "DELETE FROM events WHERE id = ?",
            (event_id,),
        )


def get_pending_events(config: Config) -> list[dict]:
    """Get events scheduled for today or earlier that haven't been delivered."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    with get_conn(config) as conn:
        rows = conn.execute(
            "SELECT id, date, description FROM events WHERE date <= ? AND status = 'pending' ORDER BY date",
            (today,),
        ).fetchall()
        return [dict(r) for r in rows]


def get_upcoming_events(config: Config, n: int = 30) -> list[dict]:
    """Get upcoming events."""
    with get_conn(config) as conn:
        rows = conn.execute(
            "SELECT id, date, description, status FROM events WHERE status = 'pending' ORDER BY date LIMIT ?",
            (n,),
        ).fetchall()
        return [dict(r) for r in rows]


def mark_event_delivered(config: Config, event_id: int) -> None:
    with get_conn(config) as conn:
        conn.execute(
            "UPDATE events SET status = 'delivered' WHERE id = ?",
            (event_id,),
        )


def mark_event_expired(config: Config, event_id: int) -> None:
    with get_conn(config) as conn:
        conn.execute(
            "UPDATE events SET status = 'expired' WHERE id = ?",
            (event_id,),
        )


def get_all_events(config: Config) -> list[dict]:
    """Get all events for the model to see context."""
    with get_conn(config) as conn:
        rows = conn.execute(
            "SELECT id, date, description, status FROM events ORDER BY date"
        ).fetchall()
        return [dict(r) for r in rows]


def cleanup_old_events(config: Config) -> int:
    """Delete events that are past their date and already delivered/expired."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    with get_conn(config) as conn:
        cur = conn.execute(
            "DELETE FROM events WHERE date < ? AND status != 'pending'",
            (today,),
        )
        return cur.rowcount


# --- Briefs ---

def save_brief_record(config: Config, date: str, brief_content: str,
                      preferences_snapshot: list[dict] | None = None,
                      email_sent_at: str | None = None) -> int:
    snap_json = json.dumps(preferences_snapshot) if preferences_snapshot else None
    with get_conn(config) as conn:
        cur = conn.execute(
            """INSERT INTO briefs (date, email_sent_at, preferences_snapshot, brief_content)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(date) DO UPDATE SET
                 email_sent_at = excluded.email_sent_at,
                 preferences_snapshot = excluded.preferences_snapshot,
                 brief_content = excluded.brief_content""",
            (date, email_sent_at, snap_json, brief_content),
        )
        return cur.lastrowid


def get_recent_briefs(config: Config, n: int = 7) -> list[dict]:
    with get_conn(config) as conn:
        rows = conn.execute(
            "SELECT date, email_sent_at, preferences_snapshot FROM briefs ORDER BY date DESC LIMIT ?",
            (n,),
        ).fetchall()
        return [dict(r) for r in rows]


def cleanup_old_briefs(config: Config) -> int:
    cutoff_date = (datetime.now(timezone.utc) - timedelta(days=config.brief_retention_days)).strftime("%Y-%m-%d")
    with get_conn(config) as conn:
        cur = conn.execute(
            "DELETE FROM briefs WHERE date < ?",
            (cutoff_date,),
        )
        return cur.rowcount


# --- Reply History ---

def save_reply(config: Config, subject: str, body: str, changes: str) -> None:
    with get_conn(config) as conn:
        conn.execute(
            "INSERT INTO reply_history (email_subject, email_body, changes_applied) VALUES (?, ?, ?)",
            (subject, body, changes),
        )


def get_recent_replies(config: Config, n: int = 10) -> list[dict]:
    with get_conn(config) as conn:
        rows = conn.execute(
            "SELECT id, email_subject, processed_at FROM reply_history ORDER BY processed_at DESC LIMIT ?",
            (n,),
        ).fetchall()
        return [dict(r) for r in rows]
