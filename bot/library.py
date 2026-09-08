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
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS folders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            created_at REAL NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS folder_books (
            folder_id INTEGER NOT NULL,
            book_id INTEGER NOT NULL,
            added_at REAL NOT NULL,
            PRIMARY KEY (folder_id, book_id)
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


def remove_bookmark(user_id: int, book_id: int) -> None:
    conn = _connect()
    try:
        conn.execute("DELETE FROM bookmarks WHERE user_id=? AND book_id=?", (user_id, book_id))
        conn.commit()
    finally:
        conn.close()


def remove_to_read(user_id: int, book_id: int) -> None:
    conn = _connect()
    try:
        conn.execute("DELETE FROM to_read WHERE user_id=? AND book_id=?", (user_id, book_id))
        conn.commit()
    finally:
        conn.close()


def remove_history(user_id: int, book_id: int) -> None:
    conn = _connect()
    try:
        conn.execute(
            "DELETE FROM reading_history WHERE user_id=? AND book_id=?", (user_id, book_id)
        )
        conn.commit()
    finally:
        conn.close()


def reset_user(user_id: int) -> None:
    """Стирает все личные данные пользователя: закладки, 'читать дальше', историю."""
    conn = _connect()
    try:
        conn.execute("DELETE FROM bookmarks WHERE user_id=?", (user_id,))
        conn.execute("DELETE FROM to_read WHERE user_id=?", (user_id,))
        conn.execute("DELETE FROM reading_history WHERE user_id=?", (user_id,))
        conn.execute(
            """
            DELETE FROM folder_books WHERE folder_id IN
            (SELECT id FROM folders WHERE user_id=?)
            """,
            (user_id,),
        )
        conn.execute("DELETE FROM folders WHERE user_id=?", (user_id,))
        conn.commit()
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


def _clean_folder_name(name: str) -> str:
    return " ".join((name or "").split())[:60]


def list_folders(user_id: int) -> list[dict]:
    conn = _connect()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT f.id, f.name, COUNT(fb.book_id)
            FROM folders f
            LEFT JOIN folder_books fb ON fb.folder_id = f.id
            WHERE f.user_id=?
            GROUP BY f.id
            ORDER BY f.created_at ASC
            """,
            (user_id,),
        )
        return [{"id": r[0], "name": r[1], "count": r[2]} for r in cur.fetchall()]
    finally:
        conn.close()


def create_folder(user_id: int, name: str) -> dict:
    name = _clean_folder_name(name)
    if not name:
        raise ValueError("Нужно название папки")
    conn = _connect()
    try:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO folders (user_id, name, created_at) VALUES (?, ?, ?)",
            (user_id, name, time.time()),
        )
        conn.commit()
        return {"id": cur.lastrowid, "name": name, "count": 0}
    finally:
        conn.close()


def rename_folder(user_id: int, folder_id: int, name: str) -> dict | None:
    name = _clean_folder_name(name)
    if not name:
        raise ValueError("Нужно название папки")
    conn = _connect()
    try:
        cur = conn.cursor()
        cur.execute(
            "UPDATE folders SET name=? WHERE id=? AND user_id=?",
            (name, folder_id, user_id),
        )
        conn.commit()
        if cur.rowcount == 0:
            return None
        return {"id": folder_id, "name": name}
    finally:
        conn.close()


def delete_folder(user_id: int, folder_id: int) -> bool:
    conn = _connect()
    try:
        cur = conn.cursor()
        cur.execute("SELECT 1 FROM folders WHERE id=? AND user_id=?", (folder_id, user_id))
        if not cur.fetchone():
            return False
        cur.execute("DELETE FROM folder_books WHERE folder_id=?", (folder_id,))
        cur.execute("DELETE FROM folders WHERE id=? AND user_id=?", (folder_id, user_id))
        conn.commit()
        return True
    finally:
        conn.close()


def get_folder_books(user_id: int, folder_id: int) -> list[int] | None:
    conn = _connect()
    try:
        cur = conn.cursor()
        cur.execute("SELECT 1 FROM folders WHERE id=? AND user_id=?", (folder_id, user_id))
        if not cur.fetchone():
            return None
        cur.execute(
            "SELECT book_id FROM folder_books WHERE folder_id=? ORDER BY added_at DESC",
            (folder_id,),
        )
        return [r[0] for r in cur.fetchall()]
    finally:
        conn.close()


def add_book_to_folder(user_id: int, folder_id: int, book_id: int) -> bool:
    conn = _connect()
    try:
        cur = conn.cursor()
        cur.execute("SELECT 1 FROM folders WHERE id=? AND user_id=?", (folder_id, user_id))
        if not cur.fetchone():
            return False
        cur.execute(
            "INSERT OR IGNORE INTO folder_books (folder_id, book_id, added_at) VALUES (?, ?, ?)",
            (folder_id, book_id, time.time()),
        )
        conn.commit()
        return True
    finally:
        conn.close()


def remove_book_from_folder(user_id: int, folder_id: int, book_id: int) -> bool:
    conn = _connect()
    try:
        cur = conn.cursor()
        cur.execute("SELECT 1 FROM folders WHERE id=? AND user_id=?", (folder_id, user_id))
        if not cur.fetchone():
            return False
        cur.execute(
            "DELETE FROM folder_books WHERE folder_id=? AND book_id=?",
            (folder_id, book_id),
        )
        conn.commit()
        return True
    finally:
        conn.close()
