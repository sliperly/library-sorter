import re, unicodedata, difflib
from pathlib import Path
from typing import Optional, Union
import os
os.environ["NO_PROXY"] = "localhost,127.0.0.1"

from pydantic import BaseModel, Field
from config import OLLAMA_MODEL, OLLAMA_BASE_URL, CATEGORIES

class BookMetadata(BaseModel):
    identified: bool = Field(description="Удалось ли идентифицировать книгу")
    author_last: Optional[str] = Field(None, description="Фамилия автора транслитом")
    author_first: Optional[str] = Field(None, description="Инициал имени, одна буква")
    title: Optional[str] = Field(None, description="Название книги")
    year: Optional[Union[str, int]] = Field(None, description="Год издания, 4 цифры")
    language: Optional[str] = Field(None, description="Язык: ru/en/de/zh/ja/other")
    category: Optional[str] = Field(default="_Unprocessed", description="Категория из списка допустимых")
    confidence: float = Field(description="Уверенность от 0.0 до 1.0")
    skip_reason: Optional[str] = Field(None, description="Причина пропуска")

CATEGORIES_STR = "\n".join(sorted(CATEGORIES))

SYSTEM_PROMPT = f"""Ты - библиотекарь-эксперт. Анализируешь текст из начала книги и возвращаешь метаданные в JSON.

ДОПУСТИМЫЕ КАТЕГОРИИ (выбери ОДНУ точно из этого списка, включая символы подчёркивания):
{CATEGORIES_STR}

ПРАВИЛА:
1. identified=true только если уверенно определил автора, название и тему
2. confidence: 0.95+ абсолютно уверен, 0.80-0.94 уверен, 0.70-0.79 вероятно, <0.70 неуверен
3. author_last: только ФАМИЛИЯ транслитом. Примеры: Ivanov, Smith
4. author_first: только ПЕРВАЯ БУКВА имени. Примеры: A, J
5. year: только 4 цифры 1900-2030 или null
6. language: строго двухбуквенный код ru/en/de/zh/ja/other — НИКОГДА полным словом
   (не "Russian", не "русский" — только "ru")
7. Не документ вовсе (исходный код программы, случайный лог, повреждённые
   нечитаемые данные) -> identified=false, skip_reason="not_a_book"
8. Неподдерживаемый язык -> identified=false, skip_reason="unsupported_language"
9. ГОСТ/ОСТ/ТУ/стандарты -> identified=true, category="09_Справочники/01_ГОСТы"
10. Типовой проект, техническая документация, чертёж, инструкция, руководство,
    нормативный документ -> identified=true, категория по теме (обычно
    01_Техника/... или 09_Справочники/...), НЕ not_a_book — это справочный
    материал, который тоже нужно систематизировать, а не пропускать
11. Журналы -> category="10_Журналы/..."
12. Раздел "07_Военное_дело" — только уставы, наставления, тактика конкретного
    боя, вооружение и техника. Политическая аналитика, публицистика,
    геополитика, история войн как общественного явления (не боевые действия
    как таковые) -> "06_История_Политика/..." (обычно 04_Политика или
    05_Геополитика), а НЕ "07_Военное_дело"

ВАЖНО: отвечай ТОЛЬКО валидным JSON без markdown-блоков."""

LANGUAGE_ALIASES = {
    "russian": "ru", "русский": "ru", "rus": "ru",
    "english": "en", "английский": "en", "eng": "en",
    "german": "de", "deutsch": "de", "немецкий": "de", "ger": "de",
    "chinese": "zh", "китайский": "zh", "chi": "zh",
    "japanese": "ja", "японский": "ja", "jap": "ja",
}

def _normalize_language(lang: Optional[str]) -> Optional[str]:
    """Модель иногда возвращает язык полным словом вместо кода — приводим
    к ожидаемому формату, чтобы не терять нормальные книги на SKIP/lang."""
    if not lang:
        return lang
    key = lang.strip().lower()
    return LANGUAGE_ALIASES.get(key, key)

def _normalize_category(cat: Optional[str]) -> Optional[str]:
    """Модель иногда промахивается мимо точного формата категории
    (пробел вместо подчёркивания и т.п.) — пытаемся исправить автоматически
    вместо того, чтобы терять файл на SKIP/invalid_cat."""
    if not cat:
        return cat
    if cat in CATEGORIES:
        return cat
    fixed = cat.replace(" ", "_")
    if fixed in CATEGORIES:
        return fixed
    close = difflib.get_close_matches(cat, CATEGORIES, n=1, cutoff=0.6)
    return close[0] if close else cat

def analyze_book(filename: str, text: str) -> BookMetadata:
    import ollama
    client = ollama.Client(host=OLLAMA_BASE_URL)
    text_for_llm = text[:4000] if text else "(текст не извлечён)"
    user = f"Имя файла: {filename}\n\nТекст из начала файла:\n---\n{text_for_llm}\n---\n\nВерни JSON с метаданными книги."
    response = client.chat(
        model=OLLAMA_MODEL,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user",   "content": user},
        ],
        think=False,
        format=BookMetadata.model_json_schema(),
        options={"temperature": 0},
    )
    raw = response.message.content.strip()
    raw = re.sub(r"^```json\s*", "", raw)
    raw = re.sub(r"```\s*$", "", raw).strip()
    meta = BookMetadata.model_validate_json(raw)
    if meta.year is not None:
        meta.year = str(meta.year)
    meta.language = _normalize_language(meta.language)
    meta.category = _normalize_category(meta.category) or "_Unprocessed"
    return meta

TRANSLIT_TABLE = str.maketrans({
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
    text = re.sub(r'[/\\:*?"<>|]', "", text)
    text = re.sub(r"[\s\-]+", "_", text)
    text = re.sub(r"_+", "_", text)
    return text.strip("_")[:max_len]

def build_filename(meta: "BookMetadata", original_path: Path) -> str:
    ext = original_path.suffix.lower()
    parts = []
    if meta.author_last:
        a = _slugify(meta.author_last, 30)
        if meta.author_first:
            a += "_" + _slugify(meta.author_first, 2)
        parts.append(a)
    if meta.title:
        parts.append(_slugify(meta.title, 80))
    if meta.year:
        parts.append(meta.year)
    if not parts:
        parts.append(_slugify(original_path.stem, 100))
    name = "-".join(parts)
    return name[:150] + ext
