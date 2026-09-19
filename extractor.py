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
    """Извлекает текст из PDF (слой или OCR)."""
    try:
        result = subprocess.run(
            [PDFTOTEXT_BIN, "-l", "3", str(path), "-"],
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
# FB2 — прямой разбор XML, без внешних зависимостей.
# Не полагаемся на конкретную версию namespace (2.0/2.1/3.0 и т.п.) — ищем
# элементы по "локальному" имени тега, игнорируя namespace целиком, потому
# что fb2-файлы из разных источников часто используют разные версии.
# ---------------------------------------------------------------------------

def _local_tag(tag: str) -> str:
    return tag.split('}')[-1] if '}' in tag else tag

def _from_fb2(path: Path) -> str:
    import xml.etree.ElementTree as ET
    try:
        tree = ET.parse(path)
        root = tree.getroot()
        parts = []

        # Заголовок, автор, аннотация — откуда угодно в title-info
        for el in root.iter():
            name = _local_tag(el.tag)
            if name in ("book-title", "author", "annotation"):
                text = "".join(el.itertext()).strip()
                if text:
                    parts.append(text)

        # Первые ~20 абзацев тела книги
        p_count = 0
        for el in root.iter():
            if _local_tag(el.tag) == "p":
                text = "".join(el.itertext()).strip()
                if text:
                    parts.append(text)
                    p_count += 1
                if p_count >= 20:
                    break

        return _trim("\n".join(parts))
    except ET.ParseError as e:
        print(f"  [WARN] FB2 parse error: {e}")
        return ""
    except Exception as e:
        print(f"  [WARN] FB2 error: {e}")
        return ""


# ---------------------------------------------------------------------------
# EPUB — zip с HTML/XHTML внутри, без ebooklib.
# ---------------------------------------------------------------------------

def _from_epub(path: Path) -> str:
    try:
        with zipfile.ZipFile(path) as z:
            html_files = [n for n in z.namelist()
                          if n.lower().endswith((".html", ".xhtml", ".htm"))]
            if not html_files:
                return ""
            # Берём первые несколько файлов — обычно титул + начало текста
            chunks = []
            for name in html_files[:3]:
                content = z.read(name).decode("utf-8", errors="ignore")
                text = re.sub(r"<[^>]+>", " ", content)
                text = re.sub(r"\s+", " ", text)
                chunks.append(text)
            return _trim(" ".join(chunks))
    except Exception as e:
        print(f"  [WARN] EPUB error: {e}")
        return ""


# ---------------------------------------------------------------------------
# MOBI — через пакет `mobi` (pip install mobi), без Calibre.
# Известное ограничение: сильно защищённые/нестандартные .azw/.mobi файлы
# этот пакет может не осилить — тогда вернётся "" и файл уйдёт в
# no_text_extracted, как и любой другой нечитаемый файл.
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
        content = extracted.read_text(encoding="utf-8", errors="ignore")
        text = re.sub(r"<[^>]+>", " ", content)
        text = re.sub(r"\s+", " ", text)
        return _trim(text)
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
