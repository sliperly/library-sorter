"""
extractor.py — Извлечение текста из книжных файлов (v3.0)

Новая логика:
- Только извлечение текста (без метаданных)
- PDF с текстом → pdftotext
- PDF без текста (скан) → EasyOCR
- DJVU → djvutxt
- FB2/EPUB → парсинг
- MOBI → calibre
"""
import subprocess
import zipfile
import re
from pathlib import Path
from typing import Optional
from config import TEXT_EXTRACT_CHARS


def extract_text(path: Path) -> str:
    """
    Главная функция извлечения текста.
    Возвращает первые TEXT_EXTRACT_CHARS символов или '' при неудаче.
    """
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
        elif ext == ".mobi":
            return _from_mobi(path)
        else:
            return ""
    except Exception as e:
        print(f"  [WARN] Extract error {path.name}: {e}")
        return ""


def _trim(text: str) -> str:
    """Обрезает текст до нужной длины."""
    return text[:TEXT_EXTRACT_CHARS].strip()


def _is_scanned_pdf(path: Path) -> bool:
    """
    Проверяет, является ли PDF отсканированным (без текстового слоя).
    Считаем PDF сканом, если pdftotext извлёк меньше 200 символов.
    """
    try:
        result = subprocess.run(
            ["pdftotext", "-l", "1", str(path), "-"],
            capture_output=True, text=True, timeout=15
        )
        text = result.stdout.strip()
        # Если меньше 200 символов с первой страницы — вероятно скан
        return len(text) < 200
    except Exception:
        return False


def _ocr_pdf(path: Path) -> str:
    """
    Распознаёт текст из сканированного PDF через EasyOCR.
    Обрабатывает первые 2-3 страницы.
    """
    try:
        import easyocr
        from pdf2image import convert_from_path
        
        # Конвертируем первые 3 страницы в изображения
        images = convert_from_path(str(path), first_page=1, last_page=3)
        
        if not images:
            return ""
        
        # Инициализируем EasyOCR (русский + английский)
        reader = easyocr.Reader(['ru', 'en'], gpu=True)
        
        all_text = []
        for img in images:
            # Распознаём текст
            result = reader.readtext(img, detail=0, paragraph=True)
            all_text.extend(result)
            
            # Если уже набрали достаточно текста — прерываем
            combined = "\n".join(all_text)
            if len(combined) >= TEXT_EXTRACT_CHARS:
                break
        
        text = "\n".join(all_text)
        print(f"  [OCR] Распознано {len(text)} символов")
        return _trim(text)
        
    except Exception as e:
        print(f"  [WARN] OCR error: {e}")
        return ""


def _from_pdf(path: Path) -> str:
    """
    Извлекает текст из PDF.
    Если PDF отсканирован → использует OCR.
    """
    # Сначала пробуем обычное извлечение
    try:
        result = subprocess.run(
            ["pdftotext", "-l", "3", str(path), "-"],
            capture_output=True, text=True, timeout=30
        )
        text = result.stdout.strip()
        
        # Если получили достаточно текста — возвращаем
        if len(text) >= 500:
            return _trim(text)
        
        # Если мало текста — проверяем, скан ли это
        if _is_scanned_pdf(path):
            print(f"  [SCAN] Detected scanned PDF, using OCR...")
            return _ocr_pdf(path)
        
        return _trim(text)
        
    except Exception as e:
        print(f"  [WARN] PDF extract error: {e}")
        return ""


def _from_djvu(path: Path) -> str:
    """Извлекает текст из DJVU через djvutxt."""
    try:
        result = subprocess.run(
            ["djvutxt", "--page=1-3", str(path)],
            capture_output=True, text=True, timeout=30
        )
        return _trim(result.stdout)
    except Exception as e:
        print(f"  [WARN] DJVU extract error: {e}")
        return ""


def _from_fb2(path: Path) -> str:
    """Извлекает текст из FB2 (XML)."""
    try:
        import xml.etree.ElementTree as ET
        tree = ET.parse(path)
        root = tree.getroot()
        ns = {"fb": "http://www.gribuser.ru/xml/fictionbook/2.0"}
        
        parts = []
        
        # Заголовок и аннотация
        title_info = root.find(".//fb:title-info", ns)
        if title_info is not None:
            for tag in ("book-title", "annotation"):
                el = title_info.find(f"fb:{tag}", ns)
                if el is not None:
                    parts.append("".join(el.itertext()))
        
        # Первые абзацы тела
        for p in root.findall(".//fb:p", ns)[:20]:
            parts.append("".join(p.itertext()))
        
        return _trim("\n".join(parts))
        
    except Exception as e:
        print(f"  [WARN] FB2 extract error: {e}")
        return ""


def _from_epub(path: Path) -> str:
    """Извлекает текст из EPUB (ZIP с HTML)."""
    try:
        with zipfile.ZipFile(path) as z:
            # Ищем HTML файлы
            html_files = [n for n in z.namelist()
                          if n.endswith((".html", ".xhtml", ".htm"))]
            if not html_files:
                return ""
            
            content = z.read(html_files[0]).decode("utf-8", errors="ignore")
            
            # Убираем HTML теги
            text = re.sub(r"<[^>]+>", " ", content)
            text = re.sub(r"\s+", " ", text)
            return _trim(text)
            
    except Exception as e:
        print(f"  [WARN] EPUB extract error: {e}")
        return ""


def _from_mobi(path: Path) -> str:
    """
    Извлекает текст из MOBI через calibre (ebook-convert).
    Конвертирует MOBI → TXT во временный файл.
    """
    try:
        import tempfile
        
        with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as tmp:
            tmp_path = Path(tmp.name)
        
        # Конвертируем MOBI → TXT
        result = subprocess.run(
            ["ebook-convert", str(path), str(tmp_path)],
            capture_output=True, text=True, timeout=60
        )
        
        if result.returncode != 0:
            print(f"  [WARN] MOBI convert failed: {result.stderr}")
            return ""
        
        # Читаем результат
        text = tmp_path.read_text(encoding="utf-8", errors="ignore")
        tmp_path.unlink()  # Удаляем временный файл
        
        return _trim(text)
        
    except Exception as e:
        print(f"  [WARN] MOBI extract error: {e}")
        return ""
