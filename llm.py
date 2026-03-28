"""
LLM-модуль: анализ книги и возврат структурированных метаданных.
"""
import re
import unicodedata
from pathlib import Path
from typing import Optional

from langchain_ollama import ChatOllama
from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel, Field

from config import (OLLAMA_MODEL, OLLAMA_BASE_URL,
                    CONFIDENCE_THRESHOLD, CATEGORIES)


# --- Pydantic-схема ответа LLM ---

class BookMetadata(BaseModel):
    identified: bool = Field(description="Удалось ли идентифицировать книгу")
    author_last: Optional[str] = Field(None, description="Фамилия автора (транслит или оригинал)")
    author_first: Optional[str] = Field(None, description="Инициал имени автора")
    title: Optional[str] = Field(None, description="Название книги")
    year: Optional[str] = Field(None, description="Год издания, только цифры")
    language: Optional[str] = Field(None, description="Язык: ru/en/de/zh/ja/other")
    category: str = Field(description="Категория из списка допустимых")
    confidence: float = Field(description="Уверенность от 0.0 до 1.0")
    skip_reason: Optional[str] = Field(None, description="Причина пропуска если identified=False")


# --- Промпт ---

SYSTEM_PROMPT = """Ты — библиотекарь. Анализируешь текст из начала книги и возвращаешь метаданные.

ДОПУСТИМЫЕ КАТЕГОРИИ (выбери одну точно из списка):
{categories}

ПРАВИЛА:
- identified=true только если уверен в названии/авторе/теме
- confidence: 1.0=абсолютно уверен, 0.5=угадываю
- language: ru/en/de/zh/ja/other
- author_last: только фамилия, без инициалов
- author_first: только первая буква имени
- year: только 4 цифры или null
- Если книга не на ru/en/de/zh/ja — identified=false, skip_reason="unsupported_language"
- Если это не книга (код, данные, изображения) — identified=false, skip_reason="not_a_book"
- Если невозможно определить тему — category="_Unprocessed"
"""

USER_PROMPT = """Имя файла: {filename}
Текст из начала файла:
---
{text}
---
Верни метаданные книги."""


def _build_categories_str() -> str:
    return "\n".join(sorted(CATEGORIES))


def _get_llm() -> ChatOllama:
    return ChatOllama(
        model=OLLAMA_MODEL,
        base_url=OLLAMA_BASE_URL,
        temperature=0,
    )


def analyze_book(filename: str, text: str) -> BookMetadata:
    """Анализирует книгу через LLM. Возвращает BookMetadata."""
    llm = _get_llm()
    structured_llm = llm.with_structured_output(BookMetadata)

    prompt = ChatPromptTemplate.from_messages([
        ("system", SYSTEM_PROMPT),
        ("human", USER_PROMPT),
    ])

    chain = prompt | structured_llm

    result: BookMetadata = chain.invoke({
        "categories": _build_categories_str(),
        "filename": filename,
        "text": text[:3000] if text else "(текст недоступен)",
    })

    return result


# --- Утилиты именования файлов ---

def _slugify(text: str, max_len: int = 60) -> str:
    """Превращает произвольный текст в безопасное имя для файловой системы."""
    # Нормализация unicode
    text = unicodedata.normalize("NFC", text)
    # Запрещённые символы → убрать
    text = re.sub(r'[/\\:*?"<>|]', "", text)
    # Пробелы и дефисы → _
    text = re.sub(r"[\s\-]+", "_", text)
    # Убрать повторные _
    text = re.sub(r"_+", "_", text)
    text = text.strip("_")
    return text[:max_len]


def build_filename(meta: BookMetadata, original_path: Path) -> str:
    """
    Строит имя файла по схеме:
    Фамилия_И-Название-Год.ext
    или для стандартов/без автора:
    Название-Год.ext
    """
    ext = original_path.suffix.lower()
    parts = []

    if meta.author_last:
        author_part = _slugify(meta.author_last, 30)
        if meta.author_first:
            first = _slugify(meta.author_first, 2)
            author_part = f"{author_part}_{first}"
        parts.append(author_part)

    if meta.title:
        parts.append(_slugify(meta.title, 80))

    if meta.year:
        parts.append(meta.year)

    if not parts:
        # Fallback — оригинальное имя без расширения
        parts.append(_slugify(original_path.stem, 100))

    name = "-".join(parts)
    # Итоговая длина не более 150 символов + расширение
    if len(name) > 150:
        name = name[:150]

    return name + ext
