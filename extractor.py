"""
Извлечение текста из первых страниц книги для передачи в LLM.
Возвращает не более TEXT_EXTRACT_CHARS символов.
"""
import subprocess
import zipfile
from pathlib import Path
from config import TEXT_EXTRACT_CHARS, BOOK_EXTENSIONS


def extract_text(path: Path) -> str:
    """Главная точка входа. Возвращает строку или '' при неудаче."""
    ext = path.suffix.lower()
    try:
        if ext == ".pdf":
            return _from_pdf(path)
        elif ext in (".djvu", ".djv"):
            return _from_djvu(path)
        elif ext == ".fb2":
            return _from_fb2(path)
        elif ext == ".epub":
            return _from_epub(path)
        elif ext in (".doc", ".docx"):
            return _from_doc(path)
        elif ext == ".rtf":
            return _from_rtf(path)
        elif ext == ".chm":
            return _from_chm(path)
        elif ext == ".txt":
            return _from_txt(path)
        else:
            return ""
    except Exception:
        return ""


def _trim(text: str) -> str:
    return text[:TEXT_EXTRACT_CHARS].strip()


def _from_pdf(path: Path) -> str:
    # pdftotext из poppler-utils
    result = subprocess.run(
        ["pdftotext", "-l", "3", str(path), "-"],
        capture_output=True, text=True, timeout=30
    )
    return _trim(result.stdout)


def _from_djvu(path: Path) -> str:
    # djvutxt из djvulibre
    result = subprocess.run(
        ["djvutxt", "--page=1-3", str(path)],
        capture_output=True, text=True, timeout=30
    )
    return _trim(result.stdout)


def _from_fb2(path: Path) -> str:
    # FB2 — XML, читаем напрямую
    import xml.etree.ElementTree as ET
    try:
        tree = ET.parse(path)
        root = tree.getroot()
        ns = {"fb": "http://www.gribuser.ru/xml/fictionbook/2.0"}
        # Заголовок и первые абзацы
        parts = []
        title_info = root.find(".//fb:title-info", ns)
        if title_info is not None:
            for tag in ("book-title", "author", "annotation"):
                el = title_info.find(f"fb:{tag}", ns)
                if el is not None:
                    parts.append("".join(el.itertext()))
        # Первые абзацы тела
        for p in root.findall(".//fb:p", ns)[:20]:
            parts.append("".join(p.itertext()))
        return _trim("\n".join(parts))
    except ET.ParseError:
        return ""


def _from_epub(path: Path) -> str:
    # EPUB — zip с HTML внутри
    try:
        with zipfile.ZipFile(path) as z:
            # Ищем первый .html/.xhtml файл
            html_files = [n for n in z.namelist()
                          if n.endswith((".html", ".xhtml", ".htm"))]
            if not html_files:
                return ""
            content = z.read(html_files[0]).decode("utf-8", errors="ignore")
            # Убираем теги
            import re
            text = re.sub(r"<[^>]+>", " ", content)
            text = re.sub(r"\s+", " ", text)
            return _trim(text)
    except Exception:
        return ""


def _from_doc(path: Path) -> str:
    # antiword для .doc, python-docx для .docx
    if path.suffix.lower() == ".docx":
        try:
            from docx import Document
            doc = Document(path)
            text = "\n".join(p.text for p in doc.paragraphs[:50])
            return _trim(text)
        except Exception:
            pass
    # Fallback: antiword
    result = subprocess.run(
        ["antiword", str(path)],
        capture_output=True, text=True, timeout=30
    )
    if result.returncode == 0:
        return _trim(result.stdout)
    # Fallback: catdoc
    result = subprocess.run(
        ["catdoc", str(path)],
        capture_output=True, text=True, timeout=30
    )
    return _trim(result.stdout)


def _from_rtf(path: Path) -> str:
    result = subprocess.run(
        ["unrtf", "--text", str(path)],
        capture_output=True, text=True, timeout=30
    )
    return _trim(result.stdout)


def _from_chm(path: Path) -> str:
    # extract_chmLib или archmage
    result = subprocess.run(
        ["archmage", "-x", str(path), "/tmp/chm_extract"],
        capture_output=True, text=True, timeout=30
    )
    # Читаем первый html
    chm_dir = Path("/tmp/chm_extract")
    if chm_dir.exists():
        html_files = list(chm_dir.rglob("*.html"))
        if html_files:
            import re
            content = html_files[0].read_text(errors="ignore")
            text = re.sub(r"<[^>]+>", " ", content)
            return _trim(text)
    return ""


def _from_txt(path: Path) -> str:
    for enc in ("utf-8", "cp1251", "latin-1"):
        try:
            text = path.read_text(encoding=enc)
            return _trim(text)
        except UnicodeDecodeError:
            continue
    return ""
