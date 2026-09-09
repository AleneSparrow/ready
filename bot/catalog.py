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
from urllib.parse import quote, unquote

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
    conn = sqlite3.connect(config.CATALOG_DB_PATH, timeout=8)
    conn.execute("PRAGMA busy_timeout=8000")
    return conn


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


def search(query: str, limit: int = 15, fuzzy: bool = True) -> list[SearchResult]:
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

        if not ids and fuzzy:
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


def search_any(terms: list[str], limit: int = 40) -> list[SearchResult]:
    """Несколько слов через OR — для темы вроде продаж: маркетинг, переговоры, сбыт."""
    words: list[str] = []
    for t in terms:
        words.extend(_WORD_RE.findall((t or "").lower()))
    words = [w for w in words if len(w) >= 3][:12]
    if not words:
        return []
    match_expr = " OR ".join(f'"{w}"*' for w in words)
    conn = _connect()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT rowid FROM books_fts WHERE books_fts MATCH ? ORDER BY rank LIMIT ?",
            (match_expr, limit * 3),
        )
        ids = [row[0] for row in cur.fetchall()]
        return _dedupe(_rows_from_ids(conn, ids), limit)
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


CLASSIC_QUERIES = (
    "мастер и маргарита",
    "война и мир",
    "преступление и наказание",
    "евгений онегин",
    "анна каренина",
    "идиот",
    "отцы и дети",
    "собачье сердце",
    "двенадцать стульев",
    "тихий дон",
    "герой нашего времени",
    "мертвые души",
)


def popular(limit: int = 24) -> list[SearchResult]:
    """Запас, если ещё никто ничего не открывал — известные книги каталога."""
    seen: set[int] = set()
    out: list[SearchResult] = []
    queries = CLASSIC_QUERIES if limit > 9 else CLASSIC_QUERIES[:4]
    per = 8 if limit > 24 else 3
    for q in queries:
        for row in search(q, limit=per, fuzzy=False):
            if row.id in seen:
                continue
            seen.add(row.id)
            out.append(row)
            if len(out) >= limit:
                return out
    return out


def _genre_tokens(genre: str) -> list[str]:
    parts = re.split(r"[,;/|]", genre or "")
    out = []
    seen = set()
    for part in parts:
        t = re.sub(r"\s+", " ", part).strip(" .")
        if len(t) < 3:
            continue
        key = t.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(t)
    return out


def _by_genre_needles(needles: list[str], limit: int = 80) -> list[SearchResult]:
    """Книги, у которых в поле genre каталога есть эти куски — не только в названии."""
    needles = [n for n in needles if n and len(n) >= 3][:8]
    if not needles:
        return []
    clauses = " OR ".join(["genre LIKE ?"] * len(needles))
    params = [f"%{n}%" for n in needles]
    conn = _connect()
    try:
        cur = conn.cursor()
        cur.execute(
            f"""
            SELECT rowid, author, title, genre, year, ext
            FROM books
            WHERE (del IS NULL OR del = '0' OR del = 0)
              AND ({clauses})
            LIMIT ?
            """,
            (*params, limit * 3),
        )
        rows = [SearchResult(*r) for r in cur.fetchall()]
        return _dedupe(rows, limit)
    finally:
        conn.close()


def similar_books(book_id: int, limit: int = 6) -> list[SearchResult]:
    """Похожие: тот же жанр из каталога, затем тот же автор — без самой книги."""
    conn = _connect()
    try:
        cur = conn.cursor()
        cur.execute("SELECT author, title, genre FROM books WHERE rowid = ?", (book_id,))
        row = cur.fetchone()
    finally:
        conn.close()
    if not row:
        return []
    raw_author, title, genre = row[0] or "", row[1] or "", row[2] or ""
    seen = {book_id}
    out: list[SearchResult] = []

    def _take(items: list[SearchResult]) -> None:
        for item in items:
            if item.id in seen:
                continue
            seen.add(item.id)
            out.append(item)
            if len(out) >= limit:
                return

    tokens = _genre_tokens(genre)
    if tokens:
        _take(_by_genre_needles(tokens[:4], limit=max(12, limit * 3)))
        if len(out) >= limit:
            return out[:limit]

    author = format_authors(raw_author)
    last = ""
    if author:
        last = author.split(",")[0].strip().split()[-1]
    title_q = " ".join(title.split()[:3])
    for q in (last, title_q):
        if not q or len(q) < 3:
            continue
        _take(search(q, limit=limit, fuzzy=False))
        if len(out) >= limit:
            return out[:limit]
    return out[:limit]


THEMES = (
    {
        "id": "t:sales",
        "title": "Продажи",
        "emoji": "💬",
        "needles": ("продаж", "маркетинг", "сбыт", "ритейл", "переговор", "коммерц", "клиент"),
    },
    {
        "id": "t:psych",
        "title": "Психология",
        "emoji": "🧠",
        "needles": ("психолог", "психотерап", "психиатр", "самооценк", "эмоци"),
    },
    {
        "id": "t:business",
        "title": "Бизнес",
        "emoji": "💼",
        "needles": ("бизнес", "управлен", "менеджмент", "предпринимат", "стартап"),
    },
    {
        "id": "t:self",
        "title": "Саморазвитие",
        "emoji": "🌱",
        "needles": ("саморазвит", "мотивац", "успех", "привычк", "продуктивн"),
    },
)

AUTHOR_SHELVES = (
    {"id": "ru", "group": "Авторы", "title": "Русские авторы", "emoji": "🇷🇺", "queries": ("толстой", "достоевский", "булгаков", "чехов", "пушкин")},
    {"id": "usa", "group": "Авторы", "title": "Американские авторы", "emoji": "🇺🇸", "queries": ("кинг", "хемингуэй", "фитцджеральд", "твен", "лондон")},
    {"id": "world", "group": "Авторы", "title": "Зарубежные авторы", "emoji": "🌍", "queries": ("шекспир", "дюма", "маркес", "мураками")},
)

# Старое имя — архив раздела ещё ссылается на него.
SHELVES = AUTHOR_SHELVES

_EMOJI_RX = (
    (re.compile(r"фантаст|фэнтез|фэнтези", re.I), "✨"),
    (re.compile(r"детектив|триллер|криминал|боевик", re.I), "🔍"),
    (re.compile(r"любовн|романс", re.I), "💕"),
    (re.compile(r"психол", re.I), "🧠"),
    (re.compile(r"истори", re.I), "🏛"),
    (re.compile(r"поэз|стих", re.I), "✒️"),
    (re.compile(r"детск|сказк", re.I), "🧸"),
    (re.compile(r"юмор|сатир", re.I), "😄"),
    (re.compile(r"научн|учебн", re.I), "🔬"),
    (re.compile(r"компьютер|программ", re.I), "💻"),
    (re.compile(r"религ|православ", re.I), "🕯"),
    (re.compile(r"приключ", re.I), "🧭"),
    (re.compile(r"проза", re.I), "📖"),
)

_shelves_memo: tuple[float, list[dict]] | None = None


def _genre_emoji(title: str) -> str:
    for rx, emoji in _EMOJI_RX:
        if rx.search(title):
            return emoji
    return "📚"


def _genre_shelves_from_db() -> list[dict]:
    conn = _connect()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT genre, COUNT(*) FROM books
            WHERE genre IS NOT NULL AND trim(genre) != ''
              AND (del IS NULL OR del = '0' OR del = 0)
            GROUP BY genre
            ORDER BY COUNT(*) DESC
            LIMIT 400
            """
        )
        raw = cur.fetchall()
    finally:
        conn.close()
    counts: dict[str, tuple[str, int]] = {}
    for genre, n in raw:
        for token in _genre_tokens(genre or ""):
            key = token.lower()
            if key in counts:
                title, c = counts[key]
                if len(token) > len(title):
                    title = token
                counts[key] = (title, c + n)
            else:
                counts[key] = (token, n)
    ranked = sorted(counts.values(), key=lambda x: -x[1])
    out = []
    for title, n in ranked:
        if n < 20:
            continue
        out.append(
            {
                "id": "g:" + quote(title, safe=""),
                "group": "Жанры каталога",
                "title": title,
                "emoji": _genre_emoji(title),
                "count": n,
                "authors": "any",
            }
        )
        if len(out) >= 80:
            break
    return out


def list_shelves() -> list[dict]:
    global _shelves_memo
    import time as _time

    now = _time.monotonic()
    if _shelves_memo and now - _shelves_memo[0] < 1800:
        return _shelves_memo[1]
    themes = [
        {
            "id": t["id"],
            "group": "Темы",
            "title": t["title"],
            "emoji": t["emoji"],
            "authors": "any",
        }
        for t in THEMES
    ]
    authors = [
        {
            "id": s["id"],
            "group": s["group"],
            "title": s["title"],
            "emoji": s["emoji"],
            "authors": "any",
        }
        for s in AUTHOR_SHELVES
    ]
    try:
        genres = _genre_shelves_from_db()
    except Exception:
        genres = []
    items = themes + authors + genres
    _shelves_memo = (now, items)
    return items


def _needles_for_shelf(shelf_id: str) -> list[str] | None:
    if shelf_id.startswith("g:"):
        token = unquote(shelf_id[2:])
        return [token] if token else None
    if shelf_id.startswith("t:"):
        theme = next((t for t in THEMES if t["id"] == shelf_id), None)
        return list(theme["needles"]) if theme else None
    return None


def _year_int(year) -> int | None:
    if not year:
        return None
    m = re.search(r"(19|20)\d{2}", str(year))
    return int(m.group(0)) if m else None


def _author_ok(author: str, mode: str) -> bool:
    if mode in ("", "any", None):
        return True
    text = format_authors(author or "")
    has_cyr = bool(re.search(r"[А-Яа-яЁё]", text))
    if mode == "ru":
        return has_cyr
    if mode == "en":
        return bool(text) and not has_cyr
    return True


def _year_ok(year, year_from, year_to) -> bool:
    if year_from is None and year_to is None:
        return True
    y = _year_int(year)
    if y is None:
        return False
    if year_from is not None and y < int(year_from):
        return False
    if year_to is not None and y > int(year_to):
        return False
    return True


def _filter_rows(rows: list[SearchResult], authors, year_from, year_to, limit) -> list[SearchResult]:
    mode = authors if authors in ("ru", "en", "any") else "any"
    out: list[SearchResult] = []
    seen: set[int] = set()
    for row in rows:
        if row.id in seen:
            continue
        if not _author_ok(row.author, mode):
            continue
        if not _year_ok(row.year, year_from, year_to):
            continue
        seen.add(row.id)
        out.append(row)
        if len(out) >= limit:
            break
    return out


def catalog_books(
    shelf_id: str,
    authors: str = "any",
    year_from: int | None = None,
    year_to: int | None = None,
    limit: int = 24,
) -> list[SearchResult]:
    """Раздел: жанр/тема из поля catalog.genre плюс близкие слова, затем фильтры."""
    limit = min(max(int(limit), 1), 48)
    needles = _needles_for_shelf(shelf_id)
    pool: list[SearchResult] = []
    seen: set[int] = set()

    def _add(items: list[SearchResult]) -> None:
        for row in items:
            if row.id in seen:
                continue
            seen.add(row.id)
            pool.append(row)

    if needles:
        _add(_by_genre_needles(needles, limit=max(48, limit * 2)))
        if len(pool) < limit:
            _add(search_any(needles, limit=limit))
    else:
        shelf = next((s for s in AUTHOR_SHELVES if s["id"] == shelf_id), None)
        if not shelf:
            return []
        for q in shelf.get("queries") or ():
            _add(search(q, limit=16, fuzzy=False))
    return _filter_rows(pool, authors, year_from, year_to, limit)
