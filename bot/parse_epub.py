"""Парсинг .epub в структуру {title, author, chapters:[{title, html}]}.

Своя (не ebooklib) реализация: библиотека содержит сотни тысяч файлов
собранных из разных источников, где нередко отсутствуют отдельные ресурсы
(например, картинки) — ebooklib на этом падает целиком, а нам достаточно
устойчиво достать текст. Здесь просто читаем OPF (манифест + спайн) и рендерим
каждую HTML-главу, пропуская то, что не удалось прочитать.

Особенность этой библиотеки книг: часть .epub-файлов внутри архивов на самом
деле хранится как вложенный 7z с уже распакованными файлами эпаба (mimetype,
META-INF/, OEBPS/...) — так их когда-то упаковала программа FLibrary. Такие
файлы сначала перепаковываются в обычный zip-контейнер.
"""
import io
import os
import posixpath
import tempfile
import zipfile

import py7zr
from lxml import etree
from lxml import html as lxml_html

from .plain import plain

SEVEN_ZIP_MAGIC = b"7z\xbc\xaf\x27\x1c"

CONTAINER_NS = {"c": "urn:oasis:names:tc:opendocument:xmlns:container"}
OPF_NS = {"opf": "http://www.idpf.org/2007/opf"}
DC_NS = {"dc": "http://purl.org/dc/elements/1.1/"}


def _repack_nested_7z_as_epub_zip(data: bytes) -> bytes:
    with tempfile.TemporaryDirectory() as tmp_dir:
        nested_path = os.path.join(tmp_dir, "nested.7z")
        with open(nested_path, "wb") as f:
            f.write(data)

        extract_dir = os.path.join(tmp_dir, "extracted")
        with py7zr.SevenZipFile(nested_path, mode="r") as z:
            z.extractall(path=extract_dir)

        book_root = extract_dir
        for root, _dirs, files in os.walk(extract_dir):
            if "mimetype" in files:
                book_root = root
                break

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for root, _dirs, files in os.walk(book_root):
                for name in files:
                    full = os.path.join(root, name)
                    rel = os.path.relpath(full, book_root)
                    with open(full, "rb") as fh:
                        content = fh.read()
                    # у файлов внутри 7z встречаются даты до 1980 — zip их не
                    # поддерживает, подставляем фиксированную валидную дату
                    info = zipfile.ZipInfo(rel, date_time=(1980, 1, 1, 0, 0, 0))
                    info.compress_type = zipfile.ZIP_DEFLATED
                    zf.writestr(info, content)
        return buf.getvalue()


def _find_opf_path(zf: zipfile.ZipFile) -> str:
    container = zf.read("META-INF/container.xml")
    tree = etree.fromstring(container)
    rootfile = tree.find(".//c:rootfile", CONTAINER_NS)
    if rootfile is None:
        # запасной вариант — искать любой .opf в архиве
        for name in zf.namelist():
            if name.lower().endswith(".opf"):
                return name
        raise ValueError("OPF не найден")
    return rootfile.get("full-path")


def parse_epub(data: bytes) -> dict:
    if data[:6] == SEVEN_ZIP_MAGIC:
        data = _repack_nested_7z_as_epub_zip(data)

    zf = zipfile.ZipFile(io.BytesIO(data))
    opf_path = _find_opf_path(zf)
    opf_dir = posixpath.dirname(opf_path)
    opf_tree = etree.fromstring(zf.read(opf_path))

    def dc_text(tag: str) -> str:
        el = opf_tree.find(f".//dc:{tag}", DC_NS)
        return plain((el.text or "") if el is not None else "")

    title = dc_text("title")
    author = dc_text("creator")

    manifest = {}
    for item in opf_tree.findall(".//opf:manifest/opf:item", OPF_NS):
        item_id = item.get("id")
        href = item.get("href")
        media_type = item.get("media-type", "")
        if item_id and href:
            manifest[item_id] = (posixpath.normpath(posixpath.join(opf_dir, href)), media_type)

    spine_ids = [
        itemref.get("idref")
        for itemref in opf_tree.findall(".//opf:spine/opf:itemref", OPF_NS)
        if itemref.get("idref")
    ]

    chapters = []
    for item_id in spine_ids:
        entry = manifest.get(item_id)
        if entry is None:
            continue
        path, media_type = entry
        if "html" not in media_type and "xml" not in media_type:
            continue
        try:
            raw = zf.read(path)
        except KeyError:
            continue  # файл упомянут в манифесте, но отсутствует в архиве
        try:
            tree = lxml_html.fromstring(raw)
        except Exception:
            continue
        body = tree.find("body")
        if body is None:
            continue
        for bad in body.xpath(".//script | .//style | .//img"):
            bad.drop_tree()
        # берём только содержимое <body ...>...</body>, без самого тега
        # (у него бывают атрибуты вроде class/id, наивная замена строк не подходит)
        html = (body.text or "") + "".join(
            lxml_html.tostring(child, encoding="unicode") for child in body
        )
        if not html.strip():
            continue
        h1 = body.find(".//h1")
        chapter_title = plain(h1.text_content() if h1 is not None else "")
        chapters.append({"title": chapter_title, "html": html})

    return {"title": title, "author": author, "chapters": chapters}
