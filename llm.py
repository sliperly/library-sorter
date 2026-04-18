"""
llm.py — Анализ книг через LLM (v3.0)

Упрощённая логика: только один метод analyze_book
"""
import re
import unicodedata
from pathlib import Path
from typing import Optional

from langchain_ollama import ChatOllama
from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel, Field

from config import OLLAMA_MODEL, OLLAMA_BASE_URL, CATEGORIES


# --- Pydantic-схема ответа LLM ---

class BookMetadata(BaseModel):
    """Метаданные книги от LLM."""
    identified: bool = Field(
        description="Удалось ли идентифицировать книгу"
    )
    author_last: Optional[str] = Field(
        None, 
        description="Фамилия автора (транслит если кириллица)"
    )
    author_first: Optional[str] = Field(
        None, 
        description="Инициал имени автора (одна буква)"
    )
    title: Optional[str] = Field(
        None, 
        description="Название книги"
    )
    year: Optional[str] = Field(
        None, 
        description="Год издания (только 4 цифры)"
    )
    language: Optional[str] = Field(
        None, 
        description="Язык книги: ru/en/de/zh/ja/other"
    )
    category: str = Field(
        description="Категория из списка допустимых"
    )
    confidence: float = Field(
        description="Уверенность от 0.0 до 1.0"
    )
    skip_reason: Optional[str] = Field(
        None, 
        description="Причина пропуска если identified=False"
    )


# --- Промпт ---

SYSTEM_PROMPT = """Ты — библиотекарь-эксперт. Анализируешь текст из начала книги и возвращаешь структурированные метаданные.

ДОПУСТИМЫЕ КАТЕГОРИИ (выбери ОДНУ точно из этого списка):
{categories}

ПРАВИЛА АНАЛИЗА:
1. identified=true только если уверенно определил автора, название И тему
2. confidence: 
   - 0.95-1.0 = абсолютно уверен (есть титульный лист, ISBN, чёткие данные)
   - 0.80-0.94 = уверен (тема понятна, автор/название определены)
   - 0.70-0.79 = вероятно правильно (есть сомнения)
   - <0.70 = неуверен (лучше пропустить)

3. language: определи язык текста (ru/en/de/zh/ja/other)
   - Если язык не ru/en/de/zh/ja → identified=false, skip_reason="unsupported_language"

4. author_last: только ФАМИЛИЯ, транслит если кириллица
   - Примеры: "Ivanov", "Smith", "Mueller"
   - НЕ включай инициалы в фамилию

5. author_first: только ПЕРВАЯ БУКВА имени
   - Примеры: "A", "J", "I"

6. year: только 4 цифры (1900-2030) или null

7. category: 
   - Выбирай СТРОГО из списка выше
   - Если сомневаешься → используй "_Unprocessed"
   - НЕ придумывай новые категории

8. Особые случаи:
   - Не книга (код, данные, лог-файлы) → identified=false, skip_reason="not_a_book"
   - Невозможно определить тему → category="_Unprocessed", confidence=0.5
   - ГОСТы, стандарты → "09_Справочники/01_ГОСТы"
   - Журналы → "10_Журналы/*" (подбери подкатегорию)
   - Художественная литература → "08_Художественная/*"

9. Транслитерация кириллицы:
   - Используй стандартную транслитерацию (я→ya, ю→yu, ё→yo, х→kh, ц→ts, ч→ch, ш→sh, щ→shch)
   - Пример: Иванов → Ivanov, Чернышевский → Chernyshevsky

ВАЖНО: Лучше честно признать неуверенность (низкий confidence) чем угадывать!
"""

USER_PROMPT = """Имя файла: {filename}

Текст из начала файла:
---
{text}
---

Проанализируй и верни метаданные книги."""


def _build_categories_str() -> str:
    """Формирует список категорий для промпта."""
    return "\n".join(sorted(CATEGORIES))


def _get_llm() -> ChatOllama:
    """Создаёт экземпляр LLM."""
    return ChatOllama(
        model=OLLAMA_MODEL,
        base_url=OLLAMA_BASE_URL,
        temperature=0,
        timeout=180,  # 3 минуты на ответ (для первого запроса)
    )


def analyze_book(filename: str, text: str) -> BookMetadata:
    """
    Анализирует книгу через LLM.
    
    Args:
        filename: имя файла для контекста
        text: извлечённый текст из книги (~4000 символов)
    
    Returns:
        BookMetadata с результатами анализа
    
    Raises:
        Exception: если LLM не ответил или ответ невалиден
    """
    llm = _get_llm()
    structured_llm = llm.with_structured_output(BookMetadata)

    prompt = ChatPromptTemplate.from_messages([
        ("system", SYSTEM_PROMPT),
        ("human", USER_PROMPT),
    ])

    chain = prompt | structured_llm

    # Ограничиваем текст для LLM
    text_for_llm = text[:4000] if text else "(текст не извлечён)"

    result: BookMetadata = chain.invoke({
        "categories": _build_categories_str(),
        "filename": filename,
        "text": text_for_llm,
    })

    return result


# --- Утилиты именования файлов ---

def _slugify(text: str, max_len: int = 60) -> str:
    """
    Превращает произвольный текст в безопасное имя файла.
    Убирает запрещённые символы, заменяет пробелы на _.
    """
    # Нормализация unicode
    text = unicodedata.normalize("NFC", text)
    
    # Запрещённые символы для файловой системы
    text = re.sub(r'[/\\:*?"<>|]', "", text)
    
    # Пробелы и дефисы → подчёркивание
    text = re.sub(r"[\s\-]+", "_", text)
    
    # Убрать повторные подчёркивания
    text = re.sub(r"_+", "_", text)
    
    # Убрать _ в начале/конце
    text = text.strip("_")
    
    return text[:max_len]


def build_filename(meta: BookMetadata, original_path: Path) -> str:
    """
    Строит имя файла по схеме: Фамилия_И-Название-Год.ext
    
    Примеры:
        Ivanov_A-Osnovy_programmirovania-2020.pdf
        GOST_12345-2018.pdf
        Neizvestnyi_avtor-Nazvanie_knigi.djvu
    
    Args:
        meta: метаданные от LLM
        original_path: исходный путь к файлу (для расширения)
    
    Returns:
        Новое имя файла (без пути)
    """
    ext = original_path.suffix.lower()
    parts = []

    # Автор (Фамилия_И)
    if meta.author_last:
        author_part = _slugify(meta.author_last, 30)
        if meta.author_first:
            first = _slugify(meta.author_first, 2)
            author_part = f"{author_part}_{first}"
        parts.append(author_part)

    # Название
    if meta.title:
        parts.append(_slugify(meta.title, 80))

    # Год
    if meta.year:
        parts.append(meta.year)

    # Fallback если нет данных
    if not parts:
        parts.append(_slugify(original_path.stem, 100))

    # Объединяем через дефис
    name = "-".join(parts)
    
    # Ограничение длины (150 символов + расширение)
    if len(name) > 150:
        name = name[:150]

    return name + ext
