import re

# Патч 1: транслитерация в llm.py
TRANSLIT = str.maketrans({
    "а":"a","б":"b","в":"v","г":"g","д":"d","е":"e","ё":"yo",
    "ж":"zh","з":"z","и":"i","й":"j","к":"k","л":"l","м":"m",
    "н":"n","о":"o","п":"p","р":"r","с":"s","т":"t","у":"u",
    "ф":"f","х":"kh","ц":"ts","ч":"ch","ш":"sh","щ":"shch",
    "ъ":"","ы":"y","ь":"","э":"e","ю":"yu","я":"ya",
    "А":"A","Б":"B","В":"V","Г":"G","Д":"D","Е":"E","Ё":"Yo",
    "Ж":"Zh","З":"Z","И":"I","Й":"J","К":"K","Л":"L","М":"M",
    "Н":"N","О":"O","П":"P","Р":"R","С":"S","Т":"T","У":"U",
    "Ф":"F","Х":"Kh","Ц":"Ts","Ч":"Ch","Ш":"Sh","Щ":"Shch",
    "Ъ":"","Ы":"Y","Ь":"","Э":"E","Ю":"Yu","Я":"Ya",
})

with open("llm.py", "r", encoding="utf-8") as f:
    src = f.read()

old = '''def _slugify(text: str, max_len: int = 60) -> str:
    text = unicodedata.normalize("NFC", text)
    text = re.sub(r\'[/\\\\:*?"<>|]\', "", text)
    text = re.sub(r"[\\s\\-]+", "_", text)
    text = re.sub(r"_+", "_", text)
    return text.strip("_")[:max_len]'''

new = '''TRANSLIT_TABLE = str.maketrans({
    "а":"a","б":"b","в":"v","г":"g","д":"d","е":"e","ё":"yo",
    "ж":"zh","з":"z","и":"i","й":"j","к":"k","л":"l","м":"m",
    "н":"n","о":"o","п":"p","р":"r","с":"s","т":"t","у":"u",
    "ф":"f","х":"kh","ц":"ts","ч":"ch","ш":"sh","щ":"shch",
    "ъ":"","ы":"y","ь":"","э":"e","ю":"yu","я":"ya",
    "А":"A","Б":"B","В":"V","Г":"G","Д":"D","Е":"E","Ё":"Yo",
    "Ж":"Zh","З":"Z","И":"I","Й":"J","К":"K","Л":"L","М":"M",
    "Н":"N","О":"O","П":"P","Р":"R","С":"S","Т":"T","У":"U",
    "Ф":"F","Х":"Kh","Ц":"Ts","Ч":"Ch","Ш":"Sh","Щ":"Shch",
    "Ъ":"","Ы":"Y","Ь":"","Э":"E","Ю":"Yu","Я":"Ya",
})

def _slugify(text: str, max_len: int = 60) -> str:
    text = unicodedata.normalize("NFC", text)
    text = text.translate(TRANSLIT_TABLE)
    text = re.sub(r\'[/\\\\:*?"<>|]\', "", text)
    text = re.sub(r"[\\s\\-]+", "_", text)
    text = re.sub(r"_+", "_", text)
    return text.strip("_")[:max_len]'''

src = src.replace(old, new)
with open("llm.py", "w", encoding="utf-8") as f:
    f.write(src)
print("llm.py OK")

# Патч 2: subjects в app.py — передаём в LLM при ISBN
with open("app.py", "r", encoding="utf-8") as f:
    src = f.read()

old2 = '''    if isbn_data:
        # РќР°Р№РґРµРЅРѕ РїРѕ ISBN
        print(f"  [ISBN] {isbn_data.title} вЂ" {isbn_data.author}")

        meta = _isbn_to_metadata(isbn_data)
        category = _classify_isbn_book(isbn_data, source_path.name)
        meta.category = category

        llm_raw = f"ISBN lookup: {isbn_data.title}"'''

new2 = '''    if isbn_data:
        print(f"  [ISBN] {isbn_data.title} -- {isbn_data.author}")
        meta = _isbn_to_metadata(isbn_data)
        # Определяем категорию через LLM с subjects
        subjects_hint = ""
        if isbn_data.subjects:
            subjects_hint = "Темы из каталога: " + ", ".join(isbn_data.subjects[:5])
        hint_text = f"Название: {isbn_data.title}\\nАвтор: {isbn_data.author}\\n{subjects_hint}"
        try:
            meta_llm = analyze_book(source_path.name, hint_text)
            meta.category = meta_llm.category
            meta.confidence = meta_llm.confidence
        except Exception:
            meta.category = "_Unprocessed"
        llm_raw = f"ISBN lookup: {isbn_data.title}"'''

src = src.replace(old2, new2)
with open("app.py", "w", encoding="utf-8") as f:
    f.write(src)
print("app.py OK")
