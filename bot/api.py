from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles

from . import catalog, extract
from .format_author import format_authors

app = FastAPI(title="Flibusta Reader")


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


app.mount("/app", StaticFiles(directory="webapp", html=True), name="webapp")
