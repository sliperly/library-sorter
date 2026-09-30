"""
identify.py — шаг 2 нового пайплайна: дешёвый вызов LLM, который извлекает
ТОЛЬКО title/author/language и решает "это вообще книга?".
Категорию НЕ определяет — это отдельный (более дорогой) шаг позже.

Пока НЕ подключён к app.py. Проверка на реальных файлах:
  python identify.py "D:\\путь\\к\\файлу1.pdf" "D:\\путь\\к\\файлу2.fb2"
"""
import os
os.environ["NO_PROXY"] = "localhost,127.0.0.1"

import re
import sys
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field

from config import OLLAMA_MODEL, OLLAMA_BASE_URL
from llm import _normalize_language, _normalize_title


class BookIdentity(BaseModel):
    is_book: bool = Field(description="Это книга/учебник/справочник/журнал, "
                          "а не код, лог или повреждённые данные")
    # title обязателен по той же причине, что и в BookMetadata: иначе модель
    # молча пропускает поле.
    title: str = Field(description="Название книги, точно как в тексте. Если "
                       "is_book=false — короткое описание содержимого.")
    author_last: Optional[str] = Field(None, description="Фамилия автора как в тексте (не транслит)")
    author_first: Optional[str] = Field(None, description="Имя автора как в тексте, если есть")
    language: Optional[str] = Field(None, description="ru/en/de/zh/ja/other")
    skip_reason: Optional[str] = Field(None, description="not_a_book, если is_book=false")


IDENTIFY_PROMPT = """Ты - библиотекарь. По тексту из начала файла определи ТОЛЬКО:
название, автора, язык и является ли файл книгой.

ПРАВИЛА:
1. is_book=false только для исходного кода, случайных логов, повреждённых
   нечитаемых данных -> skip_reason="not_a_book".
   Учебники, справочники, ГОСТы, инструкции, журналы, документация — это
   is_book=true.
2. title копируй ТОЧНО из текста (метаданные файла, титульный лист,
   заголовок). Не придумывай и не переводи.
3. Автор — как написан в тексте. Если автора нет или их много (сборник) —
   author_last=null.
4. language: строго ru/en/de/zh/ja/other, двумя буквами.
5. Категорию НЕ определяй.

Отвечай ТОЛЬКО валидным JSON."""


def identify_book(filename: str, text: str) -> BookIdentity:
    import ollama
    client = ollama.Client(host=OLLAMA_BASE_URL)
    text_for_llm = text[:3000] if text else "(текст не извлечён)"
    user = (f"Имя файла: {filename}\n\nТекст из начала файла:\n---\n"
            f"{text_for_llm}\n---\n\nВерни JSON.")
    response = client.chat(
        model=OLLAMA_MODEL,
        messages=[
            {"role": "system", "content": IDENTIFY_PROMPT},
            {"role": "user", "content": user},
        ],
        think=False,
        format=BookIdentity.model_json_schema(),
        options={"temperature": 0},
    )
    raw = response.message.content.strip()
    raw = re.sub(r"^```json\s*", "", raw)
    raw = re.sub(r"```\s*$", "", raw).strip()
    ident = BookIdentity.model_validate_json(raw)
    ident.language = _normalize_language(ident.language)
    ident.title = _normalize_title(ident.title)
    return ident


if __name__ == "__main__":
    from extractor import extract_text

    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(0)

    for arg in sys.argv[1:]:
        path = Path(arg)
        print(f"\n{'=' * 60}\n{path.name}")
        if not path.exists():
            print("  [НЕ НАЙДЕН]")
            continue
        text = extract_text(path)
        print(f"  Извлечено символов: {len(text)}")
        if not text:
            print("  (пусто)")
            continue
        try:
            r = identify_book(path.name, text)
            print(f"  is_book={r.is_book} | title={r.title!r} | "
                  f"author={r.author_last!r} {r.author_first!r} | "
                  f"lang={r.language} | skip={r.skip_reason}")
        except Exception as e:
            print(f"  [ERROR] {e}")
