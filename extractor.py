import subprocess
from pathlib import Path

from config import DJVUTXT_BIN, DDJVU_BIN, POPPLER_BIN_DIR, PDFTOTEXT_BIN, OCR_USE_GPU

TEXT_EXTRACT_CHARS = 5000

def _trim(text: str) -> str:
    return " ".join(text.split())

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



def _ocr_djvu(path):
    """DJVU скан -> ddjvu -> EasyOCR."""
    import tempfile, os
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
    import tempfile, os
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

def extract_text(path: Path) -> str:
    ext = path.suffix.lower()
    if ext == '.pdf':
        return _from_pdf(path)
    if ext in ('.djvu', '.djv'):
        return _from_djvu(path)
    return ""
