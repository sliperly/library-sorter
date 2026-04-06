"""
Извлечение текста и метаданных из книжных файлов для передачи в LLM.
"""
import subprocess
import zipfile
import re
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional
from config import TEXT_EXTRACT_CHARS, BOOK_EXTENSIONS


@dataclass
class FileMetadata:
    """Метаданные файла извлечённые без LLM."""
    title: Optional[str] = None
    author: Optional[str] = None
    subject: Optional[str] = None
    isbn: Optional[str] = None
    year: Optional[str] = None
    source: str = "none"  # откуда: pdf_meta / fb2_meta / filename / none


def extract_metadata(path: Path) -> FileMetadata:
    """
    Уровень 1 и 2: извлечь метаданные без LLM.
    Сначала из встроенных тегов файла, потом из имени файла.
    """
    ext = path.suffix.lower()
    meta = FileMetadata()

    # Уровень 1: встроенные метаданные
    if ext == ".pdf":
        meta = _meta_from_pdf(path)
    elif ext in (".fb2",):
        meta = _meta_from_fb2(path)
    elif ext == ".epub":
        meta = _meta_from_epub(path)

    # Уровень 2: имя файла (если уровень 1 не дал результата)
    if not meta.title and not meta.author:
        meta = _meta_from_filename(path)

    # ISBN из имени файла если ещё нет
    if not meta.isbn:
        isbn = _extract_isbn(path.stem)
        if isbn:
            meta.isbn = isbn

    return meta


def _is_junk_metadata(value: str) -> bool:
    """Проверить что значение metadata не является мусором."""
    if not value:
        return True
    v = value.lower().strip()
    # Временные файлы
    if re.search(r'\.(tmp|temp|bak|pdf|doc|docx)$', v):
        return True
    # Слишком короткое
    if len(v) < 4:
        return True
    # Hex строки
    if re.match(r'^[0-9a-f]{8,}$', v):
        return True
    # Типичный мусор
    junk = {'unknown', 'user', 'administrator', 'admin', 'root',
            'vip', 'author', 'title', 'document', 'untitled'}
    if v in junk:
        return True
    return False


def _meta_from_pdf(path: Path) -> FileMetadata:
    """Читает Title/Author/Subject из PDF метаданных через pdfinfo."""
    try:
        result = subprocess.run(
            ["pdfinfo", str(path)],
            capture_output=True, text=True, timeout=15
        )
        if result.returncode != 0:
            return FileMetadata()

        data = {}
        for line in result.stdout.splitlines():
            if ":" in line:
                key, _, value = line.partition(":")
                data[key.strip().lower()] = value.strip()

        title = data.get("title", "").strip()
        author = data.get("author", "").strip()
        subject = data.get("subject", "").strip()

        # Фильтруем мусорные значения
        if _is_junk_metadata(title):
            title = ""
        if _is_junk_metadata(author):
            author = ""
        if title and len(title) < 5:
            title = ""
        if author and author.lower() in ("unknown", "user", "administrator",
                                          "admin", "root", "vip", ""):
            author = ""
        # Фильтр hex-мусора типа <6976616E5F6E6577312E7670...>
        if title and title.startswith("<") and title.endswith(">"):
            title = ""

        if not title and not author:
            return FileMetadata()

        # Год из CreationDate
        year = None
        creation = data.get("creationdate", "")
        year_match = re.search(r"(19|20)\d{2}", creation)
        if year_match:
            year = year_match.group()

        return FileMetadata(
            title=title or None,
            author=author or None,
            subject=subject or None,
            year=year,
            source="pdf_meta"
        )
    except Exception:
        return FileMetadata()


def _meta_from_fb2(path: Path) -> FileMetadata:
    """Читает метаданные из FB2 (XML)."""
    try:
        import xml.etree.ElementTree as ET
        tree = ET.parse(path)
        root = tree.getroot()
        ns = {"fb": "http://www.gribuser.ru/xml/fictionbook/2.0"}
        title_info = root.find(".//fb:title-info", ns)
        if title_info is None:
            return FileMetadata()

        title_el = title_info.find("fb:book-title", ns)
        title = "".join(title_el.itertext()).strip() if title_el is not None else None

        author_parts = []
        for author_el in title_info.findall("fb:author", ns):
            for tag in ("fb:last-name", "fb:first-name"):
                el = author_el.find(tag, ns)
                if el is not None and el.text:
                    author_parts.append(el.text.strip())
        author = " ".join(author_parts) if author_parts else None

        return FileMetadata(title=title, author=author, source="fb2_meta")
    except Exception:
        return FileMetadata()


def _meta_from_epub(path: Path) -> FileMetadata:
    """Читает метаданные из EPUB (Dublin Core в OPF)."""
    try:
        with zipfile.ZipFile(path) as z:
            opf_files = [n for n in z.namelist() if n.endswith(".opf")]
            if not opf_files:
                return FileMetadata()
            content = z.read(opf_files[0]).decode("utf-8", errors="ignore")

        title_match = re.search(r"<dc:title[^>]*>([^<]+)</dc:title>", content)
        author_match = re.search(r"<dc:creator[^>]*>([^<]+)</dc:creator>", content)

        title = title_match.group(1).strip() if title_match else None
        author = author_match.group(1).strip() if author_match else None

        return FileMetadata(title=title, author=author, source="epub_meta")
    except Exception:
        return FileMetadata()


def _meta_from_filename(path: Path) -> FileMetadata:
    """
    Пытается извлечь автора и название из имени файла.
    Паттерны: Фамилия_И-Название, Фамилия_Название, Author_-_Title
    """
    stem = path.stem
    # Убираем типичные префиксы в скобках: [язык], [военное], (ebook) и т.д.
    stem = re.sub(r"^\[.*?\]\s*", "", stem)
    stem = re.sub(r"^\(.*?\)\s*", "", stem)

    author = None
    title = None

    # Паттерн: Фамилия_И.О.-Название или Фамилия И - Название
    m = re.match(r"^([А-ЯA-Z][а-яёa-z]+(?:_[А-ЯA-Z][а-яёa-z]*)*)\s*[-_]\s*(.+)$", stem)
    if m:
        author = m.group(1).replace("_", " ").strip()
        title = m.group(2).replace("_", " ").strip()
        # Убираем год из конца названия
        title = re.sub(r"\s*[\(\[_-]?(19|20)\d{2}[\)\]_]?\s*$", "", title).strip()
        if len(title) > 5:
            return FileMetadata(author=author, title=title, source="filename")

    # Просто название — заменяем _ и - на пробелы
    title = stem.replace("_", " ").replace("-", " ").strip()
    if len(title) > 5:
        return FileMetadata(title=title, source="filename")

    return FileMetadata()


def _extract_isbn(text: str) -> Optional[str]:
    """Ищет ISBN в строке."""
    m = re.search(
        r"ISBN[:\s-]*(97[89][\d\s-]{10,17}|\d[\d\s-]{8,11}[\dX])",
        text, re.IGNORECASE
    )
    if m:
        # Нормализуем: убираем пробелы и дефисы
        isbn = re.sub(r"[\s-]", "", m.group(1))
        return isbn
    return None


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
