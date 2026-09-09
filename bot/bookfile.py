"""Сырой файл книги (fb2/epub) для скачивания в чат или по ссылке."""
import re

from . import catalog, extract
from .format_author import format_authors

TELEGRAM_DOC_MAX = 49 * 1024 * 1024


class BookFileError(Exception):
    pass


def _safe_name(title: str, author: str, ext: str) -> str:
    base = f"{author} — {title}" if author else title
    base = re.sub(r'[\\/:*?"<>|\n\r]+', " ", base)
    base = re.sub(r"\s+", " ", base).strip(" .") or "book"
    return f"{base[:80]}.{ext}"


def get_book_file(book_id: int, download: bool = True) -> tuple[bytes, str]:
    meta = catalog.get_book(book_id)
    if meta is None:
        raise BookFileError("Книга не найдена")
    if meta.ext not in ("fb2", "epub"):
        raise BookFileError(f"Формат {meta.ext} скачать пока нельзя")
    try:
        data = extract.extract_book(meta.archive, meta.file, meta.ext, download=download)
    except FileNotFoundError as e:
        raise BookFileError("Не нашла файл внутри архива") from e
    except Exception as e:
        raise BookFileError("Не удалось скачать архив") from e
    author = format_authors(meta.author)
    name = _safe_name(meta.title or "book", author, meta.ext)
    return data, name
