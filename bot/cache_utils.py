"""Простой LRU-кэш на диске с ограничением по размеру директории.

Архивы книг/обложек могут весить сотни МБ, а места на volume ограничено —
без очистки диск гарантированно забьётся. Перед каждой записью в кэш-папку
проверяем её суммарный размер и удаляем самые старые (по mtime) файлы,
пока не влезем в лимит.

ВАЖНО: несколько запросов (например, вся сетка обложек в поиске) идут
параллельно — без блокировки они все одновременно видят "место есть" и
все одновременно начинают качать, суммарно пробивая лимит. Поэтому проверка
и последующая запись должны идти под одним и тем же локом на директорию.
"""
import os
import threading
from collections import defaultdict

_locks: dict[str, threading.Lock] = defaultdict(threading.Lock)


def lock_for(directory: str) -> threading.Lock:
    return _locks[directory]


def ensure_space(directory: str, max_bytes: int, incoming_bytes: int = 0) -> None:
    if not os.path.isdir(directory):
        return
    entries = []
    total = 0
    for name in os.listdir(directory):
        path = os.path.join(directory, name)
        if not os.path.isfile(path):
            continue
        stat = os.stat(path)
        entries.append((stat.st_mtime, stat.st_size, path))
        total += stat.st_size

    entries.sort()  # старые (маленький mtime) — первыми
    i = 0
    while total + incoming_bytes > max_bytes and i < len(entries):
        _, size, path = entries[i]
        try:
            os.remove(path)
            total -= size
        except OSError:
            pass
        i += 1


def clear_dir(directory: str) -> int:
    """Удаляет все файлы в директории, возвращает освобождённые байты."""
    freed = 0
    if not os.path.isdir(directory):
        return 0
    with lock_for(directory):
        for name in os.listdir(directory):
            path = os.path.join(directory, name)
            if os.path.isfile(path):
                try:
                    freed += os.path.getsize(path)
                    os.remove(path)
                except OSError:
                    pass
    return freed
