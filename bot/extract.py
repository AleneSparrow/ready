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


def _cache_path(archive: str, file_base: str, ext: str) -> str:
    return os.path.join(BOOK_CACHE_DIR, f"{archive}__{file_base}.{ext}")


def _match_name(names: list[str], target_name: str) -> str | None:
    return next(
        (
            n
            for n in names
            if n == target_name or n.lower() == target_name.lower() or n.endswith("/" + target_name)
        ),
        None,
    )


def _store_book(cache_path: str, data: bytes) -> None:
    cache_utils.ensure_space(BOOK_CACHE_DIR, BOOK_CACHE_MAX_BYTES, incoming_bytes=len(data))
    with open(cache_path, "wb") as f:
        f.write(data)


def extract_many(archive: str, members: list[tuple[str, str]], download: bool = True) -> dict[tuple[str, str], bytes]:
    """Достаёт несколько файлов из одного .7z. Не бросает, если части нет в кэше."""
    os.makedirs(BOOK_CACHE_DIR, exist_ok=True)
    out: dict[tuple[str, str], bytes] = {}
    missing: list[tuple[str, str, str]] = []
    for file_base, ext in members:
        key = (file_base, ext)
        path = _cache_path(archive, file_base, ext)
        if os.path.exists(path):
            with open(path, "rb") as f:
                out[key] = f.read()
        else:
            missing.append((file_base, ext, f"{file_base}.{ext}"))
    if not missing or not download:
        return out
    local_archive = _ensure_archive(archive)
    with py7zr.SevenZipFile(local_archive, mode="r") as z:
        names = z.getnames()
        wanted = []
        mapping = []
        for file_base, ext, target_name in missing:
            match = _match_name(names, target_name)
            if match:
                wanted.append(match)
                mapping.append((file_base, ext, match))
        if not wanted:
            return out
        extracted = z.read(wanted)
    for file_base, ext, match in mapping:
        payload = extracted.get(match)
        if payload is None:
            continue
        data = payload.read()
        path = _cache_path(archive, file_base, ext)
        _store_book(path, data)
        out[(file_base, ext)] = data
    return out


def extract_book(archive: str, file_base: str, ext: str, download: bool = True) -> bytes:
    """Возвращает содержимое книги (сырые байты fb2/epub)."""
    got = extract_many(archive, [(file_base, ext)], download=download)
    data = got.get((file_base, ext))
    if data is None:
        raise FileNotFoundError("not cached" if not download else f"{file_base}.{ext!r} не найден внутри {archive}")
    return data
