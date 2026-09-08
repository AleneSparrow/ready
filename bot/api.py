import os

from fastapi import FastAPI, HTTPException, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import catalog, config, cover, extract, library
from .format_author import format_authors

app = FastAPI(title="Flibusta Reader")


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


@app.get("/api/popular")
def api_popular():
    ids = library.popular_book_ids(24)
    items = [b for b in (_brief(i) for i in ids) if b]
    if len(items) < 16:
        have = {b["id"] for b in items}
        for row in catalog.popular(24):
            if row.id in have:
                continue
            brief = _brief(row.id)
            if brief:
                items.append(brief)
                have.add(row.id)
            if len(items) >= 24:
                break
    return items[:24]


@app.get("/api/recommendations/{user_id}")
def api_recommendations(user_id: int):
    """Подборка по названиям своих папок; если папок нет — популярное."""
    items = []
    have: set[int] = set()
    for folder in library.list_folders(user_id):
        for row in catalog.search(folder["name"], limit=5):
            if row.id in have:
                continue
            brief = _brief(row.id)
            if not brief:
                continue
            items.append(brief)
            have.add(row.id)
            if len(items) >= 12:
                return items
    if len(items) < 8:
        for row in catalog.popular(12):
            if row.id in have:
                continue
            brief = _brief(row.id)
            if not brief:
                continue
            items.append(brief)
            have.add(row.id)
            if len(items) >= 12:
                break
    return items


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
    for entry in library.get_history(user_id):
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
def api_webapp_index():
    with open("webapp/index.html", "rb") as f:
        content = f.read()
    return Response(
        content=content,
        media_type="text/html",
        headers={"Cache-Control": "no-store, no-cache, must-revalidate, max-age=0"},
    )


app.mount("/app", StaticFiles(directory="webapp", html=True), name="webapp")
