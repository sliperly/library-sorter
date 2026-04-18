"""
isbn_lookup.py — Поиск книг по ISBN через Open Library API
"""
import re
import requests
from typing import Optional
from dataclasses import dataclass


@dataclass
class ISBNBookData:
    """Данные книги из Open Library."""
    title: str
    author: str
    year: Optional[str] = None
    language: Optional[str] = None
    subjects: list[str] = None
    
    def __post_init__(self):
        if self.subjects is None:
            self.subjects = []


def extract_isbn(text: str) -> Optional[str]:
    """
    Извлекает ISBN из текста (ISBN-10 или ISBN-13).
    Возвращает нормализованный ISBN без дефисов и пробелов.
    """
    # Ищем ISBN-13 (978/979 + 10 цифр) или ISBN-10 (9 цифр + X)
    patterns = [
        r"ISBN[:\s-]*(97[89][\d\s-]{10,17})",  # ISBN-13
        r"ISBN[:\s-]*(\d[\d\s-]{8,11}[\dX])",  # ISBN-10
    ]
    
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            # Нормализуем: убираем пробелы и дефисы
            isbn = re.sub(r"[\s-]", "", match.group(1))
            # Валидация длины
            if len(isbn) in (10, 13):
                return isbn
    
    return None


def lookup_isbn(isbn: str, timeout: int = 10) -> Optional[ISBNBookData]:
    """
    Ищет книгу по ISBN через Open Library API.
    Возвращает ISBNBookData или None если не найдено.
    
    API: https://openlibrary.org/dev/docs/api/books
    """
    try:
        url = f"https://openlibrary.org/api/books"
        params = {
            "bibkeys": f"ISBN:{isbn}",
            "format": "json",
            "jscmd": "data"
        }
        
        response = requests.get(url, params=params, timeout=timeout)
        
        if response.status_code != 200:
            return None
        
        data = response.json()
        key = f"ISBN:{isbn}"
        
        if key not in data:
            return None
        
        book = data[key]
        
        # Извлекаем данные
        title = book.get("title", "").strip()
        
        # Авторы (может быть список)
        authors = book.get("authors", [])
        author = authors[0].get("name", "") if authors else ""
        
        # Год публикации
        year = None
        publish_date = book.get("publish_date", "")
        year_match = re.search(r"(19|20)\d{2}", publish_date)
        if year_match:
            year = year_match.group()
        
        # Язык (может отсутствовать)
        languages = book.get("languages", [])
        language = None
        if languages:
            lang_code = languages[0].get("key", "")
            # Конвертируем /languages/eng → en
            if "/eng" in lang_code:
                language = "en"
            elif "/rus" in lang_code:
                language = "ru"
            elif "/ger" in lang_code or "/deu" in lang_code:
                language = "de"
        
        # Subjects (темы)
        subjects = []
        for subj in book.get("subjects", []):
            if isinstance(subj, dict):
                subjects.append(subj.get("name", ""))
            else:
                subjects.append(str(subj))
        
        if not title:
            return None
        
        return ISBNBookData(
            title=title,
            author=author,
            year=year,
            language=language,
            subjects=subjects[:10]  # Ограничим 10 темами
        )
        
    except Exception as e:
        print(f"  [WARN] ISBN lookup error: {e}")
        return None


def search_isbn_in_text(text: str) -> Optional[ISBNBookData]:
    """
    Главная функция: ищет ISBN в тексте и запрашивает Open Library.
    
    Использование:
        text = extract_text(filepath)
        book_data = search_isbn_in_text(text)
        if book_data:
            print(f"Найдено: {book_data.title} — {book_data.author}")
    """
    isbn = extract_isbn(text)
    if not isbn:
        return None
    
    print(f"  [ISBN] Найден: {isbn}")
    return lookup_isbn(isbn)
