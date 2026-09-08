"""Обложки книг: лежат в отдельных .zip-архивах на Drive (папка covers/),
имя файла внутри — LIBID книги, формат — JPEG XL (нужна конвертация для
показа в браузере/Telegram — они JXL не понимают)."""
import os
import subprocess
import zipfile

from . import cache_utils, config
from .gdrive import download_file

COVER_ARCHIVE_CACHE_DIR = os.path.join(config.CACHE_DIR, "cover_archives")
COVER_CACHE_DIR = os.path.join(config.CACHE_DIR, "covers")

COVER_ARCHIVE_CACHE_MAX_BYTES = int(1.2 * 1024**3)
COVER_CACHE_MAX_BYTES = 200 * 1024**2


def _cover_archive_name(source_inp: str) -> str:
    # 'f.fb2-258562-263213.inp' -> 'covers/f.fb2-258562-263213.zip'
    base = source_inp[:-4] if source_inp.endswith(".inp") else source_inp
    return f"covers/{base}.zip"


def _ensure_cover_archive(source_inp: str) -> str:
    archive_name = _cover_archive_name(source_inp)
    local_path = os.path.join(COVER_ARCHIVE_CACHE_DIR, os.path.basename(archive_name))
    if not os.path.exists(local_path):
        os.makedirs(COVER_ARCHIVE_CACHE_DIR, exist_ok=True)
        cache_utils.ensure_space(COVER_ARCHIVE_CACHE_DIR, COVER_ARCHIVE_CACHE_MAX_BYTES)
        download_file(archive_name, local_path, config.GDRIVE_LIBRARY_FOLDER_ID)
    return local_path


def get_cover_jpeg(book_id: int, libid: str, source_inp: str) -> bytes | None:
    """Возвращает JPEG-байты обложки, либо None если обложки нет."""
    os.makedirs(COVER_CACHE_DIR, exist_ok=True)
    cache_path = os.path.join(COVER_CACHE_DIR, f"{book_id}.jpg")
    if os.path.exists(cache_path):
        with open(cache_path, "rb") as f:
            return f.read()

    if not libid or not source_inp:
        return None

    try:
        archive_path = _ensure_cover_archive(source_inp)
    except Exception:
        return None

    try:
        with zipfile.ZipFile(archive_path) as z:
            if libid not in z.namelist():
                return None
            jxl_bytes = z.read(libid)
    except Exception:
        return None

    jpeg_bytes = _jxl_to_jpeg(jxl_bytes)
    if jpeg_bytes is None:
        return None

    cache_utils.ensure_space(COVER_CACHE_DIR, COVER_CACHE_MAX_BYTES, incoming_bytes=len(jpeg_bytes))
    with open(cache_path, "wb") as f:
        f.write(jpeg_bytes)
    return jpeg_bytes


def _jxl_to_jpeg(jxl_bytes: bytes) -> bytes | None:
    import tempfile

    with tempfile.NamedTemporaryFile(suffix=".jxl", delete=False) as src:
        src.write(jxl_bytes)
        src_path = src.name
    dst_path = src_path + ".jpg"
    try:
        result = subprocess.run(
            ["djxl", src_path, dst_path], capture_output=True, timeout=15
        )
        if result.returncode != 0 or not os.path.exists(dst_path):
            return None
        with open(dst_path, "rb") as f:
            return f.read()
    except Exception:
        return None
    finally:
        for p in (src_path, dst_path):
            if os.path.exists(p):
                os.unlink(p)
