"""Личные данные читателя: закладки, список "читать дальше", история чтения.

Хранится ОТДЕЛЬНО от flibusta_catalog.db (тот периодически перекачивается
целиком с Google Drive и не должен содержать ничего, что нельзя потерять).

Пользователь идентифицируется по Telegram user_id (из initDataUnsafe.user.id
на фронте) — своя авторизация не нужна, бот и так только для одного человека.
"""
import os
import sqlite3
import time

from . import config

LIBRARY_DB_PATH = os.environ.get(
    "LIBRARY_DB_PATH", os.path.join(os.path.dirname(config.CATALOG_DB_PATH), "library.db")
)


def _connect() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(LIBRARY_DB_PATH) or ".", exist_ok=True)
    conn = sqlite3.connect(LIBRARY_DB_PATH)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS bookmarks (
            user_id INTEGER NOT NULL,
            book_id INTEGER NOT NULL,
            created_at REAL NOT NULL,
            PRIMARY KEY (user_id, book_id)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS to_read (
            user_id INTEGER NOT NULL,
            book_id INTEGER NOT NULL,
            created_at REAL NOT NULL,
            PRIMARY KEY (user_id, book_id)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS reading_history (
            user_id INTEGER NOT NULL,
            book_id INTEGER NOT NULL,
            last_page INTEGER NOT NULL DEFAULT 0,
            total_pages INTEGER NOT NULL DEFAULT 0,
            opened_at REAL NOT NULL,
            updated_at REAL NOT NULL,
            finished INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (user_id, book_id)
        )
        """
    )
    return conn


def toggle_bookmark(user_id: int, book_id: int) -> bool:
    """Возвращает True если добавили, False если убрали."""
    conn = _connect()
    try:
        cur = conn.cursor()
        cur.execute("SELECT 1 FROM bookmarks WHERE user_id=? AND book_id=?", (user_id, book_id))
        if cur.fetchone():
            cur.execute("DELETE FROM bookmarks WHERE user_id=? AND book_id=?", (user_id, book_id))
            conn.commit()
            return False
        cur.execute(
            "INSERT INTO bookmarks (user_id, book_id, created_at) VALUES (?, ?, ?)",
            (user_id, book_id, time.time()),
        )
        conn.commit()
        return True
    finally:
        conn.close()


def toggle_to_read(user_id: int, book_id: int) -> bool:
    conn = _connect()
    try:
        cur = conn.cursor()
        cur.execute("SELECT 1 FROM to_read WHERE user_id=? AND book_id=?", (user_id, book_id))
        if cur.fetchone():
            cur.execute("DELETE FROM to_read WHERE user_id=? AND book_id=?", (user_id, book_id))
            conn.commit()
            return False
        cur.execute(
            "INSERT INTO to_read (user_id, book_id, created_at) VALUES (?, ?, ?)",
            (user_id, book_id, time.time()),
        )
        conn.commit()
        return True
    finally:
        conn.close()


def update_progress(user_id: int, book_id: int, page: int, total_pages: int, finished: bool) -> None:
    conn = _connect()
    try:
        now = time.time()
        conn.execute(
            """
            INSERT INTO reading_history (user_id, book_id, last_page, total_pages, opened_at, updated_at, finished)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_id, book_id) DO UPDATE SET
                last_page=excluded.last_page,
                total_pages=excluded.total_pages,
                updated_at=excluded.updated_at,
                finished=MAX(reading_history.finished, excluded.finished)
            """,
            (user_id, book_id, page, total_pages, now, now, int(finished)),
        )
        conn.commit()
    finally:
        conn.close()


def get_bookmarks(user_id: int) -> list[int]:
    conn = _connect()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT book_id FROM bookmarks WHERE user_id=? ORDER BY created_at DESC", (user_id,)
        )
        return [r[0] for r in cur.fetchall()]
    finally:
        conn.close()


def get_to_read(user_id: int) -> list[int]:
    conn = _connect()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT book_id FROM to_read WHERE user_id=? ORDER BY created_at DESC", (user_id,)
        )
        return [r[0] for r in cur.fetchall()]
    finally:
        conn.close()


def get_history(user_id: int, limit: int = 20) -> list[dict]:
    conn = _connect()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT book_id, last_page, total_pages, finished, updated_at
            FROM reading_history WHERE user_id=?
            ORDER BY updated_at DESC LIMIT ?
            """,
            (user_id, limit),
        )
        return [
            {
                "book_id": r[0],
                "last_page": r[1],
                "total_pages": r[2],
                "finished": bool(r[3]),
                "updated_at": r[4],
            }
            for r in cur.fetchall()
        ]
    finally:
        conn.close()


def get_stats(user_id: int) -> dict:
    conn = _connect()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT COUNT(*), SUM(finished) FROM reading_history WHERE user_id=?", (user_id,)
        )
        opened, finished = cur.fetchone()
        cur.execute("SELECT COUNT(*) FROM bookmarks WHERE user_id=?", (user_id,))
        bookmarks_count = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM to_read WHERE user_id=?", (user_id,))
        to_read_count = cur.fetchone()[0]
        return {
            "books_opened": opened or 0,
            "books_finished": finished or 0,
            "bookmarks_count": bookmarks_count,
            "to_read_count": to_read_count,
        }
    finally:
        conn.close()
