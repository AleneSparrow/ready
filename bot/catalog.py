"""Поиск по каталогу flibusta_catalog.db (SQLite, создан заранее)."""
import sqlite3
from typing import NamedTuple

from . import config


class SearchResult(NamedTuple):
    id: int
    author: str
    title: str
    genre: str
    year: str
    ext: str


class BookMeta(NamedTuple):
    id: int
    author: str
    title: str
    archive: str
    file: str
    ext: str


def _connect() -> sqlite3.Connection:
    return sqlite3.connect(config.CATALOG_DB_PATH)


def search(query: str, limit: int = 15) -> list[SearchResult]:
    query = query.strip()
    if not query:
        return []
    like = f"%{query}%"
    conn = _connect()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT rowid, author, title, genre, year, ext
            FROM books
            WHERE (title LIKE ? OR author LIKE ?)
              AND (del IS NULL OR del = '0' OR del = 0)
            ORDER BY length(title) ASC
            LIMIT ?
            """,
            (like, like, limit),
        )
        return [SearchResult(*row) for row in cur.fetchall()]
    finally:
        conn.close()


def get_book(book_id: int) -> BookMeta | None:
    conn = _connect()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT rowid, author, title, archive, file, ext FROM books WHERE rowid = ?",
            (book_id,),
        )
        row = cur.fetchone()
        return BookMeta(*row) if row else None
    finally:
        conn.close()
