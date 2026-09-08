"""Простой LRU-кэш на диске с ограничением по размеру директории.

Архивы книг/обложек могут весить сотни МБ, а места на volume ограничено —
без очистки диск гарантированно забьётся. Перед каждой записью в кэш-папку
проверяем её суммарный размер и удаляем самые старые (по mtime) файлы,
пока не влезем в лимит.
"""
import os


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
