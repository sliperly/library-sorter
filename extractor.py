import re
import subprocess
import zipfile
import shutil
import tempfile
from pathlib import Path

from config import DJVUTXT_BIN, DDJVU_BIN, POPPLER_BIN_DIR, PDFTOTEXT_BIN, OCR_USE_GPU

TEXT_EXTRACT_CHARS = 5000

def _trim(text: str) -> str:
    return " ".join(text.split())

# ---------------------------------------------------------------------------
# PDF
# ---------------------------------------------------------------------------

def _ocr_pdf(path: Path) -> str:
    """Распознаёт текст из сканированного PDF через EasyOCR."""
    try:
        import easyocr
        import numpy as np
        from pdf2image import convert_from_path

        images = convert_from_path(
            str(path), first_page=1, last_page=3, dpi=200,
            poppler_path=POPPLER_BIN_DIR or None
        )
        if not images:
            return ""

        reader = easyocr.Reader(['ru', 'en'], gpu=OCR_USE_GPU, verbose=False)

        all_text = []
        for img in images:
            img_array = np.array(img)
            result = reader.readtext(img_array, detail=0, paragraph=True)
            all_text.extend(result)

            combined = "\n".join(all_text)
            if len(combined) >= TEXT_EXTRACT_CHARS:
                break

        text = "\n".join(all_text)
        return _trim(text)
    except Exception as e:
        print(f"  [WARN] OCR error: {e}")
        return ""

def _from_pdf(path: Path) -> str:
    """Извлекает текст из PDF (слой или OCR).

    Глубина 15 страниц (было 3) — на практике у многих книг первые 2-4
    страницы это обложка/УДК-ББК/выходные данные/пустые листы, а не текст
    книги. При -l 3 текстовый слой часто оказывался пустым не потому что
    книга — скан, а потому что смотрели не туда: PDF с реальным текстовым
    слоем ошибочно уходил в OCR, и OCR-мусор смешивался с осмысленным
    текстом (если тот всё же был), путая LLM. Проверено на конкретном
    случае: страницы 1-3 — обложка/аннотация в одну строку, содержательный
    текст начинается с 5-й страницы.
    """
    try:
        result = subprocess.run(
            [PDFTOTEXT_BIN, "-l", "15", str(path), "-"],
            capture_output=True, timeout=30, encoding="utf-8", errors="ignore"
        )
        text = result.stdout
        if len(text.strip()) < 100:
            return _ocr_pdf(path)
        return _trim(text)
    except Exception as e:
        print(f"  [WARN] pdftotext error: {e}")
        return _ocr_pdf(path)


# ---------------------------------------------------------------------------
# DJVU
# ---------------------------------------------------------------------------

def _ocr_djvu(path):
    """DJVU скан -> ddjvu -> EasyOCR."""
    import os
    try:
        import easyocr
        import numpy as np
        from PIL import Image
    except ImportError as e:
        print(f"  [WARN] DJVU OCR import error: {e}")
        return ""
    try:
        tmpdir = tempfile.mkdtemp()
        out_pattern = os.path.join(tmpdir, "page-%d.ppm")
        subprocess.run(
            [DDJVU_BIN, "-format=ppm", "-page=1-3", "-scale=150", str(path), out_pattern],
            capture_output=True, timeout=60
        )
        pages = sorted([os.path.join(tmpdir, f) for f in os.listdir(tmpdir) if f.endswith(".ppm")])
        if not pages:
            return ""
        reader = easyocr.Reader(["ru", "en"], gpu=OCR_USE_GPU, verbose=False)
        all_text = []
        for page_path in pages[:3]:
            img = np.array(Image.open(page_path))
            result = reader.readtext(img, detail=0, paragraph=True)
            all_text.extend(result)
            if len(" ".join(all_text)) >= 4000:
                break
        for f in pages:
            os.unlink(f)
        os.rmdir(tmpdir)
        return _trim("\n".join(all_text))
    except Exception as e:
        print(f"  [WARN] DJVU OCR error: {e}")
        return ""

def _from_djvu(path):
    """Извлекает текст из DJVU через djvutxt."""
    import os
    try:
        result = subprocess.run(
            [DJVUTXT_BIN, str(path), "-"],
            capture_output=True, timeout=30, encoding="utf-8", errors="ignore"
        )
        text = result.stdout.strip()
        if len(text) > 100:
            return _trim(text)
    except Exception:
        pass
    try:
        with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as tmp:
            tmp_path = tmp.name
        subprocess.run(
            [DJVUTXT_BIN, str(path), tmp_path],
            capture_output=True, timeout=30
        )
        with open(tmp_path, encoding="utf-8", errors="ignore") as f:
            text = f.read().strip()
        os.unlink(tmp_path)
        if len(text) > 100:
            return _trim(text)
    except Exception:
        pass
    return _ocr_djvu(path)


# ---------------------------------------------------------------------------
# FB2
# ---------------------------------------------------------------------------

def _local_tag(tag: str) -> str:
    return tag.split('}')[-1] if '}' in tag else tag

def _from_fb2(path: Path) -> str:
    """
    Название/автор/аннотация подписаны явными метками (как для mobi/epub) —
    иначе модель на некоторых файлах (особенно с рваной, полной опечаток
    аннотацией) сваливает все три поля в одну кучу и вместо названия
    возвращает "ФИО автора + название + жанр + вся аннотация" одной строкой.
    """
    import xml.etree.ElementTree as ET
    try:
        tree = ET.parse(path)
        root = tree.getroot()

        book_title = None
        author = None
        annotation = None

        for el in root.iter():
            name = _local_tag(el.tag)
            if name == "book-title" and not book_title:
                text = "".join(el.itertext()).strip()
                if text:
                    book_title = text
            elif name == "author" and not author:
                text = "".join(el.itertext()).strip()
                if text:
                    author = text
            elif name == "annotation" and not annotation:
                text = "".join(el.itertext()).strip()
                if text:
                    annotation = text

        header_lines = []
        if book_title:
            header_lines.append(f"Название: {book_title}")
        if author:
            header_lines.append(f"Автор: {author}")
        header = ("[Метаданные файла]\n" + "\n".join(header_lines) + "\n\n") if header_lines else ""

        sections = []
        if annotation:
            sections.append(f"[Аннотация]\n{annotation}")

        p_count = 0
        body_parts = []
        for el in root.iter():
            if _local_tag(el.tag) == "p":
                text = "".join(el.itertext()).strip()
                if text:
                    body_parts.append(text)
                    p_count += 1
                if p_count >= 20:
                    break
        if body_parts:
            sections.append("[Текст начала книги]\n" + "\n".join(body_parts))

        return _trim(header + "\n\n".join(sections))
    except ET.ParseError as e:
        print(f"  [WARN] FB2 parse error: {e}")
        return ""
    except Exception as e:
        print(f"  [WARN] FB2 error: {e}")
        return ""


# ---------------------------------------------------------------------------
# Метаданные из content.opf (общие для EPUB и распакованного MOBI) —
# стандартный XML-контейнер с dc:title/dc:creator/dc:identifier, который
# несёт сам файл, в отличие от "текста на первых страницах", где вместо
# названия книги нередко оказывается водяной знак сайта-источника,
# благодарности донорам и т.п. "обложечный" шум перед реальным текстом.
# ---------------------------------------------------------------------------

def _parse_opf_metadata(opf_content: str) -> dict:
    import xml.etree.ElementTree as ET
    meta = {"title": None, "author": None, "isbn": None}
    try:
        root = ET.fromstring(opf_content)
        for el in root.iter():
            name = _local_tag(el.tag)
            text = (el.text or "").strip()
            if not text:
                continue
            if name == "title" and not meta["title"]:
                meta["title"] = text
            elif name == "creator" and not meta["author"]:
                meta["author"] = text
            elif name == "identifier" and not meta["isbn"]:
                digits = re.sub(r"[^0-9Xx]", "", text)
                if len(digits) in (10, 13):
                    meta["isbn"] = digits
    except Exception:
        pass
    return meta

def _format_metadata_header(meta: dict) -> str:
    lines = []
    if meta.get("title"):
        lines.append(f"Название: {meta['title']}")
    if meta.get("author"):
        lines.append(f"Автор: {meta['author']}")
    if meta.get("isbn"):
        lines.append(f"ISBN: {meta['isbn']}")
    if not lines:
        return ""
    return "[Метаданные файла]\n" + "\n".join(lines) + "\n\n[Текст начала книги]\n"


# ---------------------------------------------------------------------------
# EPUB — zip с HTML/XHTML внутри + свои метаданные из *.opf.
# ---------------------------------------------------------------------------

def _from_epub(path: Path) -> str:
    try:
        with zipfile.ZipFile(path) as z:
            names = z.namelist()

            header = ""
            opf_names = [n for n in names if n.lower().endswith(".opf")]
            if opf_names:
                try:
                    opf_content = z.read(opf_names[0]).decode("utf-8", errors="ignore")
                    header = _format_metadata_header(_parse_opf_metadata(opf_content))
                except Exception:
                    pass

            html_files = [n for n in names if n.lower().endswith((".html", ".xhtml", ".htm"))]
            if not html_files and not header:
                return ""

            chunks = []
            for name in html_files[:3]:
                content = z.read(name).decode("utf-8", errors="ignore")
                text = re.sub(r"<[^>]+>", " ", content)
                text = re.sub(r"\s+", " ", text)
                chunks.append(text)

            return _trim(header + " ".join(chunks))
    except Exception as e:
        print(f"  [WARN] EPUB error: {e}")
        return ""


# ---------------------------------------------------------------------------
# MOBI — через пакет `mobi`. Распаковка кладёт рядом с book.html файл
# content.opf с теми же метаданными, что видит Calibre — читаем его,
# прежде чем брать текст.
# ---------------------------------------------------------------------------

def _from_mobi(path: Path) -> str:
    try:
        import mobi
    except ImportError:
        print("  [WARN] пакет mobi не установлен — pip install mobi")
        return ""
    try:
        tempdir, filepath = mobi.extract(str(path))
    except Exception as e:
        print(f"  [WARN] MOBI extract error: {e}")
        return ""
    try:
        extracted = Path(filepath)

        if extracted.suffix.lower() == ".epub":
            return _from_epub(extracted)

        header = ""
        opf_path = extracted.parent / "content.opf"
        if opf_path.exists():
            try:
                opf_content = opf_path.read_text(encoding="utf-8", errors="ignore")
                header = _format_metadata_header(_parse_opf_metadata(opf_content))
            except Exception:
                pass

        content = extracted.read_text(encoding="utf-8", errors="ignore")
        body = re.sub(r"<[^>]+>", " ", content)
        body = re.sub(r"\s+", " ", body).strip()

        return _trim(header + body)
    except Exception as e:
        print(f"  [WARN] MOBI read error: {e}")
        return ""
    finally:
        shutil.rmtree(tempdir, ignore_errors=True)


# ---------------------------------------------------------------------------
# Диспетчер
# ---------------------------------------------------------------------------

def extract_text(path: Path) -> str:
    ext = path.suffix.lower()
    if ext == '.pdf':
        return _from_pdf(path)
    if ext in ('.djvu', '.djv'):
        return _from_djvu(path)
    if ext == '.fb2':
        return _from_fb2(path)
    if ext == '.epub':
        return _from_epub(path)
    if ext == '.mobi':
        return _from_mobi(path)
    return ""
