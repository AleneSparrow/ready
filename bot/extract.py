"""Скачивание нужного .7z с Drive (с кэшем) и извлечение одного файла из него."""
import os

import py7zr

from . import cache_utils, config
from .gdrive import download_file

ARCHIVE_CACHE_DIR = os.path.join(config.CACHE_DIR, "archives")
BOOK_CACHE_DIR = os.path.join(config.CACHE_DIR, "books")

# архивы книг бывают под ~400 МБ — не даём кэшу архивов расти бесконечно.
# Лимиты держим с запасом: несколько загрузок могут идти параллельно.
ARCHIVE_CACHE_MAX_BYTES = 1024**3
BOOK_CACHE_MAX_BYTES = 300 * 1024**2


def _ensure_archive(archive_name: str) -> str:
    local_path = os.path.join(ARCHIVE_CACHE_DIR, archive_name)
    if os.path.exists(local_path):
        return local_path
    os.makedirs(ARCHIVE_CACHE_DIR, exist_ok=True)
    # лок на всю проверку+запись — иначе параллельные запросы одновременно
    # решат, что место есть, и суммарно пробьют лимit
    with cache_utils.lock_for(ARCHIVE_CACHE_DIR):
        if os.path.exists(local_path):
            return local_path
        cache_utils.ensure_space(ARCHIVE_CACHE_DIR, ARCHIVE_CACHE_MAX_BYTES)
        download_file(archive_name, local_path, config.GDRIVE_LIBRARY_FOLDER_ID, timeout=180)
    return local_path


def extract_book(archive: str, file_base: str, ext: str, download: bool = True) -> bytes:
    """Возвращает содержимое книги (сырые байты fb2/epub)."""
    target_name = f"{file_base}.{ext}"

    os.makedirs(BOOK_CACHE_DIR, exist_ok=True)
    cache_path = os.path.join(BOOK_CACHE_DIR, f"{archive}__{target_name}")
    if os.path.exists(cache_path):
        with open(cache_path, "rb") as f:
            return f.read()
    if not download:
        raise FileNotFoundError("not cached")

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

    cache_utils.ensure_space(BOOK_CACHE_DIR, BOOK_CACHE_MAX_BYTES, incoming_bytes=len(data))
    with open(cache_path, "wb") as f:
        f.write(data)
    return data
