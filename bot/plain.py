"""Текст из fb2/epub/каталога иногда приходит как &#1052;&#1085;&#1077; вместо букв."""
import html
import re

_SPACE = re.compile(r"\s+")


def plain(s: str) -> str:
    if not s:
        return ""
    text = str(s)
    for _ in range(4):
        nxt = html.unescape(text)
        if nxt == text:
            break
        text = nxt
    return _SPACE.sub(" ", text.replace("\xa0", " ")).strip()
