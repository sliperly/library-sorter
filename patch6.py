with open("extractor.py", "r", encoding="utf-8") as f:
    src = f.read()

djvu_func = '''
def _from_djvu(path):
    """Извлекает текст из DJVU через djvutxt."""
    import tempfile, os
    try:
        # Вариант 1: вывод в stdout
        result = subprocess.run(
            ["djvutxt", str(path), "-"],
            capture_output=True, timeout=30, encoding="utf-8", errors="ignore"
        )
        text = result.stdout.strip()
        if len(text) > 100:
            return _trim(text)
    except Exception:
        pass
    try:
        # Вариант 2: через временный файл
        with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as tmp:
            tmp_path = tmp.name
        subprocess.run(
            ["djvutxt", str(path), tmp_path],
            capture_output=True, timeout=30
        )
        with open(tmp_path, encoding="utf-8", errors="ignore") as f:
            text = f.read().strip()
        os.unlink(tmp_path)
        if len(text) > 100:
            return _trim(text)
    except Exception:
        pass
    return ""

'''

src = src.replace(
    "def extract_text(path: Path) -> str:\n    ext = path.suffix.lower()\n    if ext == '.pdf':\n        return _from_pdf(path)\n    # Здесь добавьте обработку других форматов (epub, fb2 и т.д.)\n    return \"\"",
    djvu_func + "def extract_text(path: Path) -> str:\n    ext = path.suffix.lower()\n    if ext == '.pdf':\n        return _from_pdf(path)\n    if ext in ('.djvu', '.djv'):\n        return _from_djvu(path)\n    return \"\""
)

with open("extractor.py", "w", encoding="utf-8") as f:
    f.write(src)

print("OK")
