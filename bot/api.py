import asyncio
import os
import time
from urllib.parse import quote

from fastapi import FastAPI, HTTPException, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import catalog, config, cover, extract, library
from .format_author import format_authors

app = FastAPI(title="Flibusta Reader")

_mem: dict = {}


def _memo(key, ttl, fn):
    now = time.monotonic()
    hit = _mem.get(key)
    if hit and now - hit[0] < ttl:
        return hit[1]
    val = fn()
    _mem[key] = (now, val)
    return val


def _brief(book_id: int) -> dict | None:
    meta = catalog.get_book(book_id)
    if meta is None:
        return None
    return {
        "id": book_id,
        "author": format_authors(meta.author),
        "title": meta.title,
        "ext": meta.ext,
    }


@app.get("/api/_debug/disk")
def api_debug_disk():
    import shutil

    def dir_size(path):
        total = 0
        count = 0
        if os.path.isdir(path):
            for root, _dirs, files in os.walk(path):
                for f in files:
                    try:
                        total += os.path.getsize(os.path.join(root, f))
                        count += 1
                    except OSError:
                        pass
        return {"bytes": total, "count": count}

    usage = shutil.disk_usage("/data")
    return {
        "disk_total": usage.total,
        "disk_used": usage.used,
        "disk_free": usage.free,
        "catalog_db": dir_size(config.CATALOG_DB_PATH) if os.path.isfile(config.CATALOG_DB_PATH) else {"bytes": os.path.getsize(config.CATALOG_DB_PATH) if os.path.exists(config.CATALOG_DB_PATH) else 0},
        "archives": dir_size(os.path.join(config.CACHE_DIR, "archives")),
        "books": dir_size(os.path.join(config.CACHE_DIR, "books")),
        "cover_archives": dir_size(os.path.join(config.CACHE_DIR, "cover_archives")),
        "covers": dir_size(os.path.join(config.CACHE_DIR, "covers")),
    }


@app.post("/api/_debug/clear_cache")
def api_debug_clear_cache():
    from . import cache_utils

    freed = 0
    for sub in ("archives", "books", "cover_archives", "covers"):
        freed += cache_utils.clear_dir(os.path.join(config.CACHE_DIR, sub))
    return {"freed_bytes": freed}


def _popular_items(limit: int) -> list:
    limit = min(max(int(limit), 1), 48)
    return _memo(("popular", limit), 180, lambda: _popular_uncached(limit))


def _popular_uncached(limit: int) -> list:
    ids = library.popular_book_ids(limit, since_days=14)
    if len(ids) < max(3, limit // 3):
        ids = library.popular_book_ids(limit, since_days=90)
    if not ids:
        ids = library.popular_book_ids(limit, since_days=None)
    items = [b for b in (_brief(i) for i in ids) if b]
    if items:
        return items[:limit]
    have: set[int] = set()
    for row in catalog.popular(limit):
        brief = _brief(row.id)
        if not brief or brief["id"] in have:
            continue
        items.append(brief)
        have.add(brief["id"])
        if len(items) >= limit:
            break
    return items[:limit]


@app.get("/api/popular")
def api_popular(limit: int = 9):
    return _popular_items(limit)


def _recs_from_history(user_id: int, limit: int) -> list:
    items = []
    have: set[int] = set()
    history = library.get_history(user_id, limit=8)
    for entry in history:
        have.add(entry["book_id"])
        for row in catalog.similar_books(entry["book_id"], limit=8):
            if row.id in have:
                continue
            brief = _brief(row.id)
            if not brief:
                continue
            items.append(brief)
            have.add(row.id)
            if len(items) >= limit:
                return items
    if items:
        return items[:limit]
    return _popular_items(limit)


@app.get("/api/recommendations/{user_id}")
def api_recommendations(user_id: int, limit: int = 9):
    """Короткая лента на главной: похожие на недавно читаемые."""
    return _memo(("recs", user_id, limit), 60, lambda: _recs_from_history(user_id, min(max(int(limit), 1), 36)))


@app.get("/api/recommendations/{user_id}/by-books")
def api_recommendations_by_books(user_id: int):
    """По 6 похожих на каждую книгу из «читать дальше» / истории."""
    groups = []
    for entry in library.get_history(user_id, limit=4):
        src = _brief(entry["book_id"])
        if not src:
            continue
        sims = []
        for row in catalog.similar_books(entry["book_id"], limit=6):
            brief = _brief(row.id)
            if brief:
                sims.append(brief)
        groups.append({"book": src, "items": sims})
    return {"groups": groups}


@app.get("/api/search")
def api_search(q: str):
    results = catalog.search(q)
    return [
        {
            "id": r.id,
            "author": format_authors(r.author),
            "title": r.title,
            "genre": r.genre,
            "year": r.year,
            "ext": r.ext,
        }
        for r in results
    ]


def _row_brief(r) -> dict:
    return {
        "id": r.id,
        "author": format_authors(r.author),
        "title": r.title,
        "ext": r.ext,
        "year": r.year,
        "genre": r.genre,
    }


@app.get("/api/catalog/shelves")
def api_catalog_shelves():
    return catalog.list_shelves()


@app.get("/api/catalog/books")
def api_catalog_books(
    shelf: str,
    authors: str = "any",
    year_from: int | None = None,
    year_to: int | None = None,
    limit: int = 24,
):
    rows = catalog.catalog_books(shelf, authors, year_from, year_to, limit)
    return [_row_brief(r) for r in rows]


_send_jobs: set[int] = set()


async def _run_catalog_send(user_id: int, shelf: str, authors: str, year_from, year_to) -> None:
    import io
    import zipfile

    from aiogram.types import BufferedInputFile

    from . import bookfile
    from .telegram_bot import bot

    try:
        await bot.send_message(
            user_id,
            "Собираю раздел. Пришлю до 6 книг одним архивом — не все сразу, чтобы не зависнуть.",
        )
        rows = await asyncio.to_thread(catalog.catalog_books, shelf, authors, year_from, year_to, 6)
        files: list[tuple[bytes, str]] = []
        fresh = 0
        for r in rows:
            got = None
            for download in (False, True):
                if download and fresh >= 2:
                    break
                try:
                    got = await asyncio.to_thread(bookfile.get_book_file, r.id, download)
                    if download:
                        fresh += 1
                    break
                except bookfile.BookFileError:
                    got = None
            if got:
                files.append(got)
        if not files:
            await bot.send_message(
                user_id,
                "В этом разделе пока нечего собрать. Открой пару книг, потом снова нажми «скачать раздел».",
            )
            return
        if len(files) == 1:
            data, name = files[0]
            if len(data) > bookfile.TELEGRAM_DOC_MAX:
                await bot.send_message(user_id, "Файл слишком большой для Telegram.")
                return
            await bot.send_document(user_id, BufferedInputFile(data, filename=name))
            return
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            total = 0
            for data, name in files:
                if total + len(data) > 45 * 1024 * 1024:
                    break
                zf.writestr(name, data)
                total += len(data)
        payload = buf.getvalue()
        if len(payload) > bookfile.TELEGRAM_DOC_MAX:
            await bot.send_message(user_id, "Архив получился слишком большим. Скачай книги по одной.")
            return
        zip_name = "razdel.zip"
        meta = next((s for s in catalog.CATALOG_SHELVES if s["id"] == shelf), None)
        if meta:
            zip_name = f"{meta['title']}.zip"
        elif shelf.startswith("g:"):
            from urllib.parse import unquote as _unquote
            zip_name = f"{_unquote(shelf[2:])}.zip"
        await bot.send_document(
            user_id,
            BufferedInputFile(payload, filename=zip_name),
            caption=f"{len(files)} книг из раздела. Это не вся полка — только первая пачка.",
        )
    except Exception:
        await bot.send_message(user_id, "Не получилось собрать раздел. Попробуй ещё раз через минуту.")
    finally:
        _send_jobs.discard(user_id)


@app.post("/api/catalog/send")
async def api_catalog_send(
    user_id: int,
    shelf: str,
    authors: str = "any",
    year_from: int | None = None,
    year_to: int | None = None,
):
    if not user_id:
        raise HTTPException(400, "Нет пользователя")
    if user_id in _send_jobs:
        return {"ok": True, "busy": True}
    _send_jobs.add(user_id)
    asyncio.create_task(_run_catalog_send(user_id, shelf, authors, year_from, year_to))
    return {"ok": True, "busy": False}


@app.get("/api/book/{book_id}")
def api_book(book_id: int):
    import time

    t0 = time.monotonic()
    meta = catalog.get_book(book_id)
    if meta is None:
        raise HTTPException(404, "Книга не найдена в каталоге")

    if meta.ext not in ("fb2", "epub"):
        raise HTTPException(415, f"Формат {meta.ext} пока не поддерживается")

    was_cached = os.path.exists(
        os.path.join(extract.BOOK_CACHE_DIR, f"{meta.archive}__{meta.file}.{meta.ext}")
    )
    archive_was_cached = os.path.exists(os.path.join(extract.ARCHIVE_CACHE_DIR, meta.archive))

    try:
        raw = extract.extract_book(meta.archive, meta.file, meta.ext)
    except FileNotFoundError as e:
        raise HTTPException(404, str(e))
    except Exception as e:
        raise HTTPException(502, f"Не удалось получить книгу с Google Drive: {e}")
    t1 = time.monotonic()

    if meta.ext == "fb2":
        from .parse_fb2 import parse_fb2

        parsed = parse_fb2(raw)
    else:
        from .parse_epub import parse_epub

        parsed = parse_epub(raw)
    t2 = time.monotonic()

    print(
        f"[timing] book={book_id} archive={meta.archive} "
        f"book_cached={was_cached} archive_cached={archive_was_cached} "
        f"extract={t1 - t0:.2f}s parse={t2 - t1:.2f}s",
        flush=True,
    )

    return {
        "id": book_id,
        "title": parsed["title"] or meta.title,
        "author": parsed["author"] or format_authors(meta.author),
        "chapters": parsed["chapters"],
    }


@app.get("/api/book/{book_id}/file")
def api_book_file(book_id: int):
    from . import bookfile

    try:
        data, name = bookfile.get_book_file(book_id)
    except bookfile.BookFileError as e:
        raise HTTPException(404, str(e))
    return Response(
        content=data,
        media_type="application/octet-stream",
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{quote(name)}",
            "Cache-Control": "private, max-age=3600",
        },
    )


@app.post("/api/book/{book_id}/send")
async def api_send_book(book_id: int, user_id: int):
    from aiogram.types import BufferedInputFile

    from . import bookfile
    from .telegram_bot import bot

    if not user_id:
        raise HTTPException(400, "Нет пользователя")
    try:
        data, name = await asyncio.to_thread(bookfile.get_book_file, book_id)
    except bookfile.BookFileError as e:
        raise HTTPException(404, str(e))
    if len(data) > bookfile.TELEGRAM_DOC_MAX:
        raise HTTPException(413, "Файл слишком большой для Telegram")
    await bot.send_document(chat_id=user_id, document=BufferedInputFile(data, filename=name))
    return {"ok": True}


@app.get("/api/cover/{book_id}")
def api_cover(book_id: int):
    meta = catalog.get_book(book_id)
    if meta is None:
        raise HTTPException(404, "Книга не найдена")
    jpeg = cover.get_cover_jpeg(book_id, meta.libid, meta.source_inp)
    if jpeg is None:
        raise HTTPException(404, "Нет обложки")
    return Response(content=jpeg, media_type="image/jpeg", headers={"Cache-Control": "public, max-age=604800"})


class ProgressBody(BaseModel):
    page: int
    total_pages: int
    finished: bool = False


@app.post("/api/library/{user_id}/bookmark/{book_id}")
def api_toggle_bookmark(user_id: int, book_id: int):
    added = library.toggle_bookmark(user_id, book_id)
    return {"bookmarked": added}


@app.post("/api/library/{user_id}/to-read/{book_id}")
def api_toggle_to_read(user_id: int, book_id: int):
    added = library.toggle_to_read(user_id, book_id)
    return {"to_read": added}


@app.post("/api/library/{user_id}/progress/{book_id}")
def api_update_progress(user_id: int, book_id: int, body: ProgressBody):
    library.update_progress(user_id, book_id, body.page, body.total_pages, body.finished)
    return {"ok": True}


@app.get("/api/library/{user_id}/state/{book_id}")
def api_book_state(user_id: int, book_id: int):
    """Быстрая проверка — в закладках ли книга / в списке "читать дальше"."""
    return {
        "bookmarked": book_id in set(library.get_bookmarks(user_id)),
        "to_read": book_id in set(library.get_to_read(user_id)),
    }


@app.delete("/api/library/{user_id}/bookmark/{book_id}")
def api_remove_bookmark(user_id: int, book_id: int):
    library.remove_bookmark(user_id, book_id)
    return {"ok": True}


@app.delete("/api/library/{user_id}/to-read/{book_id}")
def api_remove_to_read(user_id: int, book_id: int):
    library.remove_to_read(user_id, book_id)
    return {"ok": True}


@app.delete("/api/library/{user_id}/history/{book_id}")
def api_remove_history(user_id: int, book_id: int):
    library.remove_history(user_id, book_id)
    return {"ok": True}


@app.post("/api/library/{user_id}/reset")
def api_library_reset(user_id: int):
    library.reset_user(user_id)
    return {"ok": True}


@app.get("/api/library/{user_id}/overview")
def api_library_overview(user_id: int):
    stats = library.get_stats(user_id)
    bookmarks = [b for b in (_brief(i) for i in library.get_bookmarks(user_id)) if b]
    to_read = [b for b in (_brief(i) for i in library.get_to_read(user_id)) if b]

    history = []
    for entry in library.get_history(user_id, limit=40):
        brief = _brief(entry["book_id"])
        if not brief:
            continue
        brief.update(
            last_page=entry["last_page"],
            total_pages=entry["total_pages"],
            finished=entry["finished"],
        )
        history.append(brief)

    return {
        "stats": stats,
        "bookmarks": bookmarks,
        "to_read": to_read,
        "history": history,
        "folders": library.list_folders(user_id),
    }


class FolderNameBody(BaseModel):
    name: str
    section: str | None = None


@app.post("/api/library/{user_id}/folders")
def api_create_folder(user_id: int, body: FolderNameBody):
    try:
        return library.create_folder(user_id, body.name, body.section or "bookmarks")
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.patch("/api/library/{user_id}/folders/{folder_id}")
def api_rename_folder(user_id: int, folder_id: int, body: FolderNameBody):
    try:
        folder = library.rename_folder(user_id, folder_id, body.name)
    except ValueError as e:
        raise HTTPException(400, str(e))
    if folder is None:
        raise HTTPException(404, "Папка не найдена")
    return folder


@app.delete("/api/library/{user_id}/folders/{folder_id}")
def api_delete_folder(user_id: int, folder_id: int):
    if not library.delete_folder(user_id, folder_id):
        raise HTTPException(404, "Папка не найдена")
    return {"ok": True}


@app.get("/api/library/{user_id}/folders/{folder_id}")
def api_get_folder(user_id: int, folder_id: int):
    ids = library.get_folder_books(user_id, folder_id)
    if ids is None:
        raise HTTPException(404, "Папка не найдена")
    books = [b for b in (_brief(i) for i in ids) if b]
    folders = library.list_folders(user_id)
    meta = next((f for f in folders if f["id"] == folder_id), None)
    name = meta["name"] if meta else ""
    section = meta["section"] if meta else "bookmarks"
    return {"id": folder_id, "name": name, "section": section, "books": books}


@app.post("/api/library/{user_id}/folders/{folder_id}/books/{book_id}")
def api_add_book_to_folder(user_id: int, folder_id: int, book_id: int):
    if not library.add_book_to_folder(user_id, folder_id, book_id):
        raise HTTPException(404, "Папка не найдена")
    return {"ok": True}


@app.delete("/api/library/{user_id}/folders/{folder_id}/books/{book_id}")
def api_remove_book_from_folder(user_id: int, folder_id: int, book_id: int):
    if not library.remove_book_from_folder(user_id, folder_id, book_id):
        raise HTTPException(404, "Папка не найдена")
    return {"ok": True}


@app.get("/app/index.html")
async def api_webapp_index():
    with open("webapp/index.html", "rb") as f:
        content = f.read()
    return Response(
        content=content,
        media_type="text/html",
        headers={"Cache-Control": "no-store, no-cache, must-revalidate, max-age=0"},
    )


app.mount("/app", StaticFiles(directory="webapp", html=True), name="webapp")
