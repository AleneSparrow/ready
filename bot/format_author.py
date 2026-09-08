"""Форматирование поля AUTHOR из каталога: "Булгаков,Михаил,Афанасьевич:"
может содержать несколько авторов через ":" — приводим каждого
к виду "Михаил Афанасьевич Булгаков"."""


def format_authors(raw: str) -> str:
    if not raw:
        return ""
    names = []
    for chunk in raw.split(":"):
        chunk = chunk.strip(", ")
        if not chunk:
            continue
        parts = [p.strip() for p in chunk.split(",") if p.strip()]
        if not parts:
            continue
        last = parts[0]
        rest = parts[1:]
        names.append(" ".join(rest + [last]) if rest else last)
    return ", ".join(names)
