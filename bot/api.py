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
    meta = catalog.get_book(book_id)
    if meta is None:
        raise HTTPException(404, "Книга не найдена в каталоге")

    if meta.ext not in ("fb2", "epub"):
        raise HTTPException(415, f"Формат {meta.ext} пока не поддерживается")

    try:
        raw = extract.extract_book(meta.archive, meta.file, meta.ext)
    except FileNotFoundError as e:
        raise HTTPException(404, str(e))
    except Exception as e:
        raise HTTPException(502, f"Не удалось получить книгу с Google Drive: {e}")

    if meta.ext == "fb2":
        from .parse_fb2 import parse_fb2

        parsed = parse_fb2(raw)
    else:
        from .parse_epub import parse_epub

        parsed = parse_epub(raw)

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

    return {"stats": stats, "bookmarks": bookmarks, "to_read": to_read, "history": history}


app.mount("/app", StaticFiles(directory="webapp", html=True), name="webapp")
