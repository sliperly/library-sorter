import re
from pathlib import Path

with open('extractor.py', 'r', encoding='utf-8') as f:
    content = f.read()

# Найти и заменить _from_djvu
old_pattern = r'def _from_djvu\(path: Path\) -> str:.*?(?=\ndef |\Z)'

new_func = '''def _from_djvu(path: Path) -> str:
    ""\"Извлекает текст из DJVU через djvutxt (Windows).""\"
    try:
        import tempfile
        fd, tmp_path = tempfile.mkstemp(suffix='.txt', text=True)
        import os
        os.close(fd)
        
        result = subprocess.run(
            ["djvutxt", str(path), tmp_path],
            capture_output=True, timeout=30
        )
        
        if Path(tmp_path).exists():
            text = Path(tmp_path).read_text(encoding='utf-8', errors='ignore')
            Path(tmp_path).unlink()
            return _trim(text)
        
        return ""
    except Exception as e:
        print(f"  [WARN] DJVU error: {e}")
        return ""


'''

content = re.sub(old_pattern, new_func, content, flags=re.DOTALL)

with open('extractor.py', 'w', encoding='utf-8') as f:
    f.write(content)

print('✓ _from_djvu исправлена')
