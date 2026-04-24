with open("extractor.py", "r", encoding="utf-8") as f:
    src = f.read()

djvu_ocr = '''
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
            ["ddjvu", "-format=ppm", "-page=1-3", "-scale=150", str(path), out_pattern],
            capture_output=True, timeout=60,
            executable="C:/Program Files (x86)/DjVuLibre/ddjvu.exe"
        )
        pages = sorted([os.path.join(tmpdir, f) for f in os.listdir(tmpdir) if f.endswith(".ppm")])
        if not pages:
            return ""
        reader = easyocr.Reader(["ru", "en"], gpu=True, verbose=False)
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
        return _trim("\\n".join(all_text))
    except Exception as e:
        print(f"  [WARN] DJVU OCR error: {e}")
        return ""

'''

src = src.replace(
    "def _from_djvu(path):",
    djvu_ocr + "def _from_djvu(path):"
)

# В _from_djvu добавить вызов OCR если текста нет
src = src.replace(
    '    return ""\n\ndef extract_text',
    '    return _ocr_djvu(path)\n\ndef extract_text'
)

with open("extractor.py", "w", encoding="utf-8") as f:
    f.write(src)

print("OK")
