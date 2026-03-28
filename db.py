import sqlite3
from pathlib import Path
from datetime import datetime
from config import DB_PATH


def get_conn() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with get_conn() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS files (
                id              INTEGER PRIMARY KEY,
                source_path     TEXT UNIQUE NOT NULL,
                status          TEXT NOT NULL DEFAULT 'pending',
                skip_reason     TEXT,
                dest_path       TEXT,
                new_name        TEXT,
                author          TEXT,
                title           TEXT,
                year            TEXT,
                language        TEXT,
                category        TEXT,
                confidence      REAL,
                llm_raw         TEXT,
                processed_at    TEXT
            );

            CREATE INDEX IF NOT EXISTS idx_status ON files(status);
            CREATE INDEX IF NOT EXISTS idx_source ON files(source_path);
        """)


def upsert_pending(source_path: str) -> bool:
    """Добавить файл со статусом pending если его ещё нет. Возвращает True если добавлен."""
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT OR IGNORE INTO files (source_path) VALUES (?)",
            (source_path,)
        )
        return cur.rowcount > 0


def get_pending(limit: int = 100) -> list[sqlite3.Row]:
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM files WHERE status = 'pending' ORDER BY id LIMIT ?",
            (limit,)
        ).fetchall()


def mark_processed(source_path: str, dest_path: str, new_name: str,
                   author: str, title: str, year: str, language: str,
                   category: str, confidence: float, llm_raw: str) -> None:
    with get_conn() as conn:
        conn.execute("""
            UPDATE files SET
                status       = 'processed',
                dest_path    = ?,
                new_name     = ?,
                author       = ?,
                title        = ?,
                year         = ?,
                language     = ?,
                category     = ?,
                confidence   = ?,
                llm_raw      = ?,
                processed_at = ?
            WHERE source_path = ?
        """, (dest_path, new_name, author, title, year, language,
              category, confidence, llm_raw,
              datetime.now().isoformat(), source_path))


def mark_skipped(source_path: str, reason: str, llm_raw: str = "") -> None:
    with get_conn() as conn:
        conn.execute("""
            UPDATE files SET
                status       = 'skipped',
                skip_reason  = ?,
                llm_raw      = ?,
                processed_at = ?
            WHERE source_path = ?
        """, (reason, llm_raw, datetime.now().isoformat(), source_path))


def mark_error(source_path: str, reason: str) -> None:
    with get_conn() as conn:
        conn.execute("""
            UPDATE files SET
                status       = 'error',
                skip_reason  = ?,
                processed_at = ?
            WHERE source_path = ?
        """, (reason, datetime.now().isoformat(), source_path))


def get_stats() -> dict:
    with get_conn() as conn:
        rows = conn.execute("""
            SELECT status, COUNT(*) as cnt FROM files GROUP BY status
        """).fetchall()
        return {row["status"]: row["cnt"] for row in rows}
