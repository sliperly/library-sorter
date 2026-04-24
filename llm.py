import re, unicodedata
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

ДОПУСТИМЫЕ КАТЕГОРИИ (выбери ОДНУ точно из этого списка):
{CATEGORIES_STR}

ПРАВИЛА:
1. identified=true только если уверенно определил автора, название и тему
2. confidence: 0.95+ абсолютно уверен, 0.80-0.94 уверен, 0.70-0.79 вероятно, <0.70 неуверен
3. author_last: только ФАМИЛИЯ транслитом. Примеры: Ivanov, Smith
4. author_first: только ПЕРВАЯ БУКВА имени. Примеры: A, J
5. year: только 4 цифры 1900-2030 или null
6. language: определи язык текста
7. Не книга (код, данные, логи) -> identified=false, skip_reason="not_a_book"
8. Неподдерживаемый язык -> identified=false, skip_reason="unsupported_language"
9. ГОСТ/стандарты -> category="09_Справочники/01_ГОСТы"
10. Журналы -> category="10_Журналы/..."

ВАЖНО: отвечай ТОЛЬКО валидным JSON без markdown-блоков."""

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
    if not meta.category:
        meta.category = "_Unprocessed"
    return meta

def _slugify(text: str, max_len: int = 60) -> str:
    text = unicodedata.normalize("NFC", text)
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
