"""Скачивание нужного .7z с Drive (с кэшем) и извлечение одного файла из него."""
import os

import py7zr

from . import config
from .gdrive import download_file

ARCHIVE_CACHE_DIR = os.path.join(config.CACHE_DIR, "archives")
BOOK_CACHE_DIR = os.path.join(config.CACHE_DIR, "books")


def _ensure_archive(archive_name: str) -> str:
    local_path = os.path.join(ARCHIVE_CACHE_DIR, archive_name)
    if not os.path.exists(local_path):
        download_file(archive_name, local_path, config.GDRIVE_LIBRARY_FOLDER_ID)
    return local_path


def extract_book(archive: str, file_base: str, ext: str) -> bytes:
    """Возвращает содержимое книги (сырые байты fb2/epub)."""
    target_name = f"{file_base}.{ext}"

    os.makedirs(BOOK_CACHE_DIR, exist_ok=True)
    cache_path = os.path.join(BOOK_CACHE_DIR, f"{archive}__{target_name}")
    if os.path.exists(cache_path):
        with open(cache_path, "rb") as f:
            return f.read()

    local_archive = _ensure_archive(archive)
    with py7zr.SevenZipFile(local_archive, mode="r") as z:
        names = z.getnames()
        match = next(
            (
                n
                for n in names
                if n == target_name or n.lower() == target_name.lower() or n.endswith("/" + target_name)
            ),
            None,
        )
        if match is None:
            raise FileNotFoundError(f"{target_name!r} не найден внутри {archive}")
        extracted = z.read([match])
        data = extracted[match].read()

    with open(cache_path, "wb") as f:
        f.write(data)
    return data
