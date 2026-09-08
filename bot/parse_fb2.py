"""Парсинг .fb2 (XML) в структуру {title, author, chapters:[{title, html}]}."""
from lxml import etree

FB2_NS = "http://www.gribuser.ru/xml/fictionbook/2.0"


def _text(el) -> str:
    return "".join(el.itertext()).strip() if el is not None else ""


def _escape(s: str) -> str:
    return (
        s.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def _render_section(section, ns: dict, level: int = 1) -> tuple[str, str]:
    title_el = section.find("fb:title", ns)
    chapter_title = _text(title_el)
    parts = []
    h = min(level + 1, 6)
    if chapter_title:
        parts.append(f"<h{h}>{_escape(chapter_title)}</h{h}>")

    for child in section:
        tag = etree.QName(child).localname
        if tag == "p":
            parts.append(f"<p>{_escape(_text(child))}</p>")
        elif tag == "subtitle":
            parts.append(f"<h4>{_escape(_text(child))}</h4>")
        elif tag == "empty-line":
            parts.append("<br/>")
        elif tag == "section":
            _, sub_html = _render_section(child, ns, level + 1)
            parts.append(sub_html)
        elif tag == "poem":
            for stanza in child.findall("fb:stanza", ns):
                lines = [f"<span>{_escape(_text(v))}</span><br/>" for v in stanza.findall("fb:v", ns)]
                parts.append(f"<p style='font-style:italic'>{''.join(lines)}</p>")

    return chapter_title, "".join(parts)


def parse_fb2(data: bytes) -> dict:
    root = etree.fromstring(data)
    ns_uri = root.nsmap.get(None, FB2_NS)
    ns = {"fb": ns_uri}

    title_info = root.find(".//fb:description/fb:title-info", ns)
    title = _text(title_info.find("fb:book-title", ns)) if title_info is not None else ""

    author = ""
    if title_info is not None:
        author_el = title_info.find("fb:author", ns)
        if author_el is not None:
            first = _text(author_el.find("fb:first-name", ns))
            last = _text(author_el.find("fb:last-name", ns))
            author = f"{first} {last}".strip()

    chapters = []
    body = root.find("fb:body", ns)
    if body is not None:
        sections = body.findall("fb:section", ns)
        for section in sections:
            ch_title, ch_html = _render_section(section, ns)
            if ch_html:
                chapters.append({"title": ch_title or title, "html": ch_html})
        if not chapters:
            ps = body.findall(".//fb:p", ns)
            html = "".join(f"<p>{_escape(_text(p))}</p>" for p in ps)
            chapters.append({"title": title, "html": html})

    return {"title": title, "author": author, "chapters": chapters}
