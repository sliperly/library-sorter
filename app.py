"""
app.py — Library Sorter v3.0

Упрощённый pipeline:
1. Извлечение текста из файла
2. Поиск ISBN → Open Library API
3. Если не найдено → LLM анализ
4. Уверенность >= 0.70 → переместить
   Уверенность < 0.70 → _Unprocessed
"""
import argparse
import sys
from pathlib import Path

from config import (
    SOURCES, NEW_ROOT, BOOK_EXTENSIONS,
    ARCHIVE_EXTENSIONS, ALLOWED_LANGUAGES,
    CONFIDENCE_THRESHOLD, CATEGORIES
)
from db import (
    init_db, upsert_pending, get_pending, get_stats,
    mark_processed, mark_skipped, mark_error
)
from extractor import extract_text
from isbn_lookup import search_isbn_in_text, ISBNBookData
from llm import analyze_book, build_filename, BookMetadata
from mover import move_file


# ---------------------------------------------------------------------------
# Вспомогательные функции
# ---------------------------------------------------------------------------

def _parse_last_name(author: str) -> str | None:
    """Извлекает фамилию из полного имени."""
    if not author:
        return None
    parts = author.strip().split()
    return parts[0] if parts else None


def _parse_first_initial(author: str) -> str | None:
    """Извлекает первую букву имени."""
    if not author:
        return None
    parts = author.strip().split()
    if len(parts) >= 2:
        return parts[1][0] if parts[1] else None
    return None


def _isbn_to_metadata(isbn_data: ISBNBookData) -> BookMetadata:
    """
    Конвертирует данные из Open Library в BookMetadata.
    Категорию нужно определить через LLM.
    """
    # Для ISBN данных используем высокий confidence
    # но категорию всё равно определяем через LLM
    return BookMetadata(
        identified=True,
        author_last=_parse_last_name(isbn_data.author),
        author_first=_parse_first_initial(isbn_data.author),
        title=isbn_data.title,
        year=isbn_data.year,
        language=isbn_data.language,
        category="_Unprocessed",  # Будет определена позже
        confidence=0.95,  # ISBN = высокая достоверность
    )


def _classify_isbn_book(isbn_data: ISBNBookData, filename: str) -> str:
    """
    Определяет категорию для книги найденной по ISBN.
    Использует subjects из Open Library + LLM если нужно.
    """
    # Простая эвристика по subjects
    subjects_text = " ".join(isbn_data.subjects).lower()
    
    # Программирование
    if any(kw in subjects_text for kw in 
           ["programming", "python", "javascript", "computer science"]):
        if "python" in subjects_text:
            return "02_IT/01_Python"
        return "02_IT/13_Прочие_языки"
    
    # История
    if any(kw in subjects_text for kw in ["history", "war", "military"]):
        return "06_История_Политика/01_История_Общая"
    
    # Физика/Математика
    if "physics" in subjects_text:
        return "03_Науки/03_Физика"
    if "mathematics" in subjects_text:
        return "03_Науки/01_Математика"
    
    # Художественная литература
    if any(kw in subjects_text for kw in 
           ["fiction", "novel", "science fiction", "fantasy"]):
        if "science fiction" in subjects_text:
            return "08_Художественная/01_Фантастика"
        if "fantasy" in subjects_text:
            return "08_Художественная/02_Фэнтези"
        return "08_Художественная/06_Прочая_худлит"
    
    # Если не смогли определить — вернём _Unprocessed
    # В будущем можно добавить LLM для точной классификации
    return "_Unprocessed"


def _save_result(source_path: Path, final_dest: Path, new_name: str,
                 meta: BookMetadata, llm_raw: str, dry_run: bool) -> None:
    """Сохраняет результат обработки в БД."""
    mark_processed(
        source_path=str(source_path),
        dest_path=str(final_dest),
        new_name=new_name,
        author=f"{meta.author_last or ''} {meta.author_first or ''}".strip(),
        title=meta.title or "",
        year=meta.year or "",
        language=meta.language or "",
        category=meta.category,
        confidence=meta.confidence,
        llm_raw=llm_raw,
    )


# ---------------------------------------------------------------------------
# Сканирование
# ---------------------------------------------------------------------------

def scan_sources(sources: list[Path]) -> int:
    """Сканирует источники и добавляет файлы в очередь."""
    added = 0
    for source_dir in sources:
        if not source_dir.exists():
            print(f"[WARN] Источник не найден: {source_dir}")
            continue
        
        print(f"[SCAN] {source_dir}")
        for path in source_dir.rglob("*"):
            if not path.is_file():
                continue
            
            ext = path.suffix.lower()
            
            # Пропускаем архивы и нежелательные форматы
            if ext in ARCHIVE_EXTENSIONS:
                continue
            
            # Только книжные форматы
            if ext not in BOOK_EXTENSIONS:
                continue
            
            if upsert_pending(str(path)):
                added += 1
    
    print(f"[SCAN] Добавлено в очередь: {added} файлов")
    return added


# ---------------------------------------------------------------------------
# Обработка одного файла
# ---------------------------------------------------------------------------

def process_file(row: dict, dry_run: bool) -> None:
    """
    Обрабатывает один файл по новому pipeline:
    1. Извлечь текст
    2. Поиск ISBN → Open Library
    3. Если не найдено → LLM
    4. Переместить или пропустить
    """
    source_path = Path(row["source_path"])
    ext = source_path.suffix.lower()

    # Проверка существования файла
    if not source_path.exists():
        mark_error(str(source_path), "file_not_found")
        print(f"  [ERROR/not_found] {source_path.name}")
        return

    print(f"\n[PROCESSING] {source_path.name}")

    # ШАГ 1: Извлечение текста
    print(f"  [1/4] Извлечение текста...")
    text = extract_text(source_path)
    
    if not text or len(text) < 100:
        mark_skipped(str(source_path), "no_text_extracted")
        print(f"  [SKIP/no_text] Не удалось извлечь текст")
        return

    print(f"  [OK] Извлечено {len(text)} символов")

    # ШАГ 2: Поиск ISBN → Open Library
    print(f"  [2/4] Поиск ISBN...")
    isbn_data = search_isbn_in_text(text)
    
    meta = None
    llm_raw = ""
    
    if isbn_data:
        # Найдено по ISBN
        print(f"  [ISBN] {isbn_data.title} — {isbn_data.author}")
        
        meta = _isbn_to_metadata(isbn_data)
        category = _classify_isbn_book(isbn_data, source_path.name)
        meta.category = category
        
        llm_raw = f"ISBN lookup: {isbn_data.title}"
        
    else:
        # ШАГ 3: LLM анализ
        print(f"  [3/4] Анализ через LLM...")
        
        try:
            meta = analyze_book(source_path.name, text)
            llm_raw = meta.model_dump_json()
            
            print(f"  [LLM] {meta.title or 'Unknown'} | "
                  f"conf={meta.confidence:.2f} | "
                  f"cat={meta.category}")
            
        except Exception as e:
            mark_error(str(source_path), f"llm_error: {e}")
            print(f"  [ERROR/llm] {e}")
            return

    # ШАГ 4: Проверка результата и перемещение
    print(f"  [4/4] Проверка и перемещение...")

    # Проверка языка
    if meta.language and meta.language not in ALLOWED_LANGUAGES:
        mark_skipped(
            str(source_path),
            f"unsupported_language:{meta.language}",
            llm_raw
        )
        print(f"  [SKIP/lang] Язык не поддерживается: {meta.language}")
        return

    # Проверка identified
    if not meta.identified:
        reason = meta.skip_reason or "not_identified"
        mark_skipped(str(source_path), reason, llm_raw)
        print(f"  [SKIP/{reason}]")
        return

    # Проверка confidence
    if meta.confidence < CONFIDENCE_THRESHOLD:
        # Низкая уверенность → в _Unprocessed
        meta.category = "_Unprocessed"
        print(f"  [LOW_CONF] {meta.confidence:.2f} < {CONFIDENCE_THRESHOLD} "
              f"→ _Unprocessed")

    # Проверка категории
    if meta.category not in CATEGORIES:
        mark_skipped(
            str(source_path),
            f"invalid_category:{meta.category}",
            llm_raw
        )
        print(f"  [SKIP/invalid_cat] {meta.category}")
        return

    # Перемещение файла
    dest_dir = NEW_ROOT / meta.category
    new_name = build_filename(meta, source_path)
    
    try:
        final_dest = move_file(source_path, dest_dir, new_name, dry_run=dry_run)
        _save_result(source_path, final_dest, new_name, meta, llm_raw, dry_run)
        
        status = "DRY" if dry_run else "OK"
        print(f"  [{status}] → {meta.category}/{new_name}")
        
    except Exception as e:
        mark_error(str(source_path), f"move_error: {e}")
        print(f"  [ERROR/move] {e}")


# ---------------------------------------------------------------------------
# Статистика
# ---------------------------------------------------------------------------

def print_stats() -> None:
    """Выводит статистику по базе данных."""
    stats = get_stats()
    total = sum(stats.values())
    
    print("\n=== Статистика библиотеки ===")
    for status, count in sorted(stats.items()):
        print(f"  {status:12s}: {count:6d}")
    print(f"  {'ИТОГО':12s}: {total:6d}")
    print()


# ---------------------------------------------------------------------------
# Точка входа
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Library Sorter v3.0 — Упрощённая версия с ISBN lookup"
    )
    parser.add_argument(
        "--execute", 
        action="store_true",
        help="Реальное перемещение файлов (по умолчанию dry-run)"
    )
    parser.add_argument(
        "--stats", 
        action="store_true",
        help="Показать статистику и выйти"
    )
    parser.add_argument(
        "--scan-only", 
        action="store_true",
        help="Только сканировать файлы (не обрабатывать)"
    )
    parser.add_argument(
        "--limit", 
        type=int, 
        default=0,
        help="Максимум файлов за запуск (0 = без ограничений)"
    )
    parser.add_argument(
        "--source", 
        type=str, 
        default="",
        help="Обработать только указанный источник"
    )
    
    args = parser.parse_args()

    # Инициализация БД
    init_db()

    # Только статистика
    if args.stats:
        print_stats()
        return

    # Режим работы
    dry_run = not args.execute
    if dry_run:
        print("[MODE] DRY-RUN — файлы НЕ перемещаются")
        print("       Используй --execute для реального запуска\n")
    else:
        print("[MODE] EXECUTE — файлы БУДУТ перемещены!\n")

    # Фильтр источников
    sources = SOURCES
    if args.source:
        sources = [s for s in SOURCES if args.source in s.name]
        if not sources:
            print(f"[ERROR] Источник '{args.source}' не найден")
            sys.exit(1)

    # Сканирование
    scan_sources(sources)

    if args.scan_only:
        print_stats()
        return

    # Обработка файлов
    limit = args.limit if args.limit > 0 else 10_000_000
    processed = 0
    batch_size = 50

    print(f"[START] Обработка до {limit if limit < 10_000_000 else '∞'} файлов\n")

    while processed < limit:
        fetch = min(batch_size, limit - processed)
        rows = get_pending(limit=fetch)
        
        if not rows:
            break

        for row in rows:
            process_file(row, dry_run=dry_run)
            processed += 1
            
            # Прогресс каждые 10 файлов
            if processed % 10 == 0:
                stats = get_stats()
                print(f"\n{'='*60}")
                print(f"[PROGRESS] {processed} обработано | "
                      f"pending: {stats.get('pending', 0)} | "
                      f"processed: {stats.get('processed', 0)} | "
                      f"skipped: {stats.get('skipped', 0)}")
                print(f"{'='*60}\n")

    print("\n[DONE] Обработка завершена")
    print_stats()


if __name__ == "__main__":
    main()
