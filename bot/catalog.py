"""Поиск по каталогу flibusta_catalog.db (SQLite + FTS5).

Стратегия поиска:
1. books_fts — обычный полнотекстовый индекс по словам (title + author_search,
   где author_search уже в естественном порядке "Имя Отчество Фамилия").
   Матчит по словам независимо от их порядка и регистра — "Иван Тургенев" и
   "Тургенев Иван" находят одно и то же, опечатки не прощает.
2. Если по (1) пусто — books_trgm (триграммный индекс) — терпит опечатки и
   неполный ввод, за счёт более широкого (и медленного) поиска по подстрокам.
"""
import re
import sqlite3
from typing import NamedTuple

from . import config
from .format_author import format_authors


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
    libid: str
    source_inp: str


def _connect() -> sqlite3.Connection:
    return sqlite3.connect(config.CATALOG_DB_PATH)


_WORD_RE = re.compile(r"[^\W_]+", re.UNICODE)


def _fts_query(query: str) -> str:
    """Собирает MATCH-запрос: каждое слово — обязательный префикс (AND)."""
    words = _WORD_RE.findall(query.lower())
    if not words:
        return ""
    # экранируем кавычки на всякий случай и берём префиксное совпадение
    terms = [f'"{w}"*' for w in words]
    return " AND ".join(terms)


def _trigram_query(query: str) -> str:
    """Собирает MATCH-запрос по триграммам: OR всех 3-граммов каждого слова.
    AND между триграммами слишком строг — одна опечатка ломает 2-3 из них,
    поэтому берём OR и полагаемся на bm25()-ранжирование по числу совпадений."""
    words = _WORD_RE.findall(query.lower())
    grams: list[str] = []
    for w in words:
        if len(w) < 3:
            grams.append(w)
            continue
        grams.extend(w[i : i + 3] for i in range(len(w) - 2))
    if not grams:
        return ""
    terms = [f'"{g}"' for g in grams]
    return " OR ".join(terms)


def _rows_from_ids(conn: sqlite3.Connection, ids: list[int]) -> list[SearchResult]:
    if not ids:
        return []
    placeholders = ",".join("?" * len(ids))
    cur = conn.cursor()
    cur.execute(
        f"""
        SELECT rowid, author, title, genre, year, ext
        FROM books
        WHERE rowid IN ({placeholders})
          AND (del IS NULL OR del = '0' OR del = 0)
        """,
        ids,
    )
    by_id = {row[0]: SearchResult(*row) for row in cur.fetchall()}
    # сохраняем порядок релевантности, который вернул FTS
    return [by_id[i] for i in ids if i in by_id]


def _normalize_title(title: str) -> str:
    # схлопываем пробелы и убираем пунктуацию по краям — в каталоге одна и та
    # же книга из fb2/epub источников иногда отличается лишь этим
    t = re.sub(r"\s+", " ", title.strip().lower())
    return t.strip(" .,-—:;")


def _dedupe(results: list[SearchResult], limit: int) -> list[SearchResult]:
    """В каталоге много одинаковых книг из разных источников/форматов
    (flibusta/librusec, fb2/epub) — схлопываем по (название, автор), оставляя
    первое (самое релевантное) вхождение. Автор сравнивается в отформатированном
    виде — сырые строки в каталоге иногда чуть различаются мелочами."""
    seen: set[tuple[str, str]] = set()
    deduped = []
    for r in results:
        key = (_normalize_title(r.title), format_authors(r.author).strip().lower())
        if key in seen:
            continue
        seen.add(key)
        deduped.append(r)
        if len(deduped) >= limit:
            break
    return deduped


def search(query: str, limit: int = 15) -> list[SearchResult]:
    query = query.strip()
    if not query:
        return []

    # берём с запасом — после дедупликации по (название, автор) части
    # результатов не хватило бы на полный limit
    fetch_limit = limit * 4

    conn = _connect()
    try:
        match_expr = _fts_query(query)
        if not match_expr:
            return []

        cur = conn.cursor()
        cur.execute(
            "SELECT rowid FROM books_fts WHERE books_fts MATCH ? ORDER BY rank LIMIT ?",
            (match_expr, fetch_limit),
        )
        ids = [row[0] for row in cur.fetchall()]

        if not ids:
            # запасной вариант — терпит опечатки за счёт триграмм
            trgm_query = _trigram_query(query)
            if not trgm_query:
                return []
            cur.execute(
                "SELECT rowid FROM books_trgm WHERE books_trgm MATCH ? ORDER BY rank LIMIT ?",
                (trgm_query, fetch_limit),
            )
            ids = [row[0] for row in cur.fetchall()]

        rows = _rows_from_ids(conn, ids)
        return _dedupe(rows, limit)
    finally:
        conn.close()


def get_book(book_id: int) -> BookMeta | None:
    conn = _connect()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT rowid, author, title, archive, file, ext, libid, source_inp FROM books WHERE rowid = ?",
            (book_id,),
        )
        row = cur.fetchone()
        return BookMeta(*row) if row else None
    finally:
        conn.close()
