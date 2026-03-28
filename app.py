"""
library_sorter/app.py

Использование:
  python app.py                  # dry-run, показывает план
  python app.py --execute        # реальное перемещение файлов
  python app.py --stats          # статистика из БД
  python app.py --scan-only      # только сканировать файлы в БД, не обрабатывать
  python app.py --limit 50       # обработать не более N файлов за запуск
  python app.py --source "Книги" # обработать только один источник
"""
import argparse
import sys
from pathlib import Path

from config import (SOURCES, NEW_ROOT, BOOK_EXTENSIONS,
                    ARCHIVE_EXTENSIONS, ALLOWED_LANGUAGES,
                    CONFIDENCE_THRESHOLD)
from db import init_db, upsert_pending, get_pending, get_stats
from db import mark_processed, mark_skipped, mark_error
from extractor import extract_text
from llm import analyze_book, build_filename, BookMetadata
from mover import move_file


# ---------------------------------------------------------------------------
# Сканирование: добавить все файлы из источников в БД со статусом pending
# ---------------------------------------------------------------------------

def scan_sources(sources: list[Path]) -> int:
    """Сканирует источники и добавляет новые файлы в БД. Возвращает кол-во добавленных."""
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
            # Пропускаем нечитаемые форматы — но логируем архивы
            if ext not in BOOK_EXTENSIONS and ext not in ARCHIVE_EXTENSIONS:
                continue
            if upsert_pending(str(path)):
                added += 1
    print(f"[SCAN] Добавлено в очередь: {added} файлов")
    return added


# ---------------------------------------------------------------------------
# Обработка одного файла
# ---------------------------------------------------------------------------

def process_file(row: dict, dry_run: bool) -> None:
    source_path = Path(row["source_path"])
    ext = source_path.suffix.lower()

    # Архивы — пропускаем
    if ext in ARCHIVE_EXTENSIONS:
        mark_skipped(str(source_path), "archive")
        print(f"  [SKIP/archive] {source_path.name}")
        return

    # Файл исчез
    if not source_path.exists():
        mark_error(str(source_path), "file_not_found")
        print(f"  [ERROR/not_found] {source_path.name}")
        return

    # Извлекаем текст
    text = extract_text(source_path)

    # Анализируем через LLM
    try:
        meta: BookMetadata = analyze_book(source_path.name, text)
    except Exception as e:
        mark_error(str(source_path), f"llm_error: {e}")
        print(f"  [ERROR/llm] {source_path.name}: {e}")
        return

    llm_raw = meta.model_dump_json()

    # Проверка языка
    if meta.language and meta.language not in ALLOWED_LANGUAGES:
        mark_skipped(str(source_path), f"unsupported_language:{meta.language}", llm_raw)
        print(f"  [SKIP/lang={meta.language}] {source_path.name}")
        return

    # Не идентифицирован или низкий confidence
    if not meta.identified or meta.confidence < CONFIDENCE_THRESHOLD:
        reason = meta.skip_reason or f"low_confidence:{meta.confidence:.2f}"
        mark_skipped(str(source_path), reason, llm_raw)
        print(f"  [SKIP/{reason}] {source_path.name}")
        return

    # Строим путь назначения
    dest_dir = NEW_ROOT / meta.category
    new_name = build_filename(meta, source_path)
    dest_path = dest_dir / new_name

    # Перемещаем (или dry-run)
    final_dest = move_file(source_path, dest_dir, new_name, dry_run=dry_run)

    if not dry_run:
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
    else:
        # В dry-run тоже обновляем БД — помечаем что план составлен
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
# Статистика
# ---------------------------------------------------------------------------

def print_stats() -> None:
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
    parser = argparse.ArgumentParser(description="Сортировщик библиотеки NetMind")
    parser.add_argument("--execute", action="store_true",
                        help="Реальное перемещение файлов (без флага — dry-run)")
    parser.add_argument("--stats", action="store_true",
                        help="Показать статистику и выйти")
    parser.add_argument("--scan-only", action="store_true",
                        help="Только сканировать файлы, не обрабатывать")
    parser.add_argument("--limit", type=int, default=0,
                        help="Максимум файлов за запуск (0 = без ограничений)")
    parser.add_argument("--source", type=str, default="",
                        help="Обработать только указанный источник (имя папки)")
    args = parser.parse_args()

    init_db()

    if args.stats:
        print_stats()
        return

    dry_run = not args.execute
    if dry_run:
        print("[MODE] DRY-RUN — файлы не перемещаются. Используй --execute для реального запуска.")
    else:
        print("[MODE] EXECUTE — файлы будут перемещены!")

    # Выбор источников
    sources = SOURCES
    if args.source:
        sources = [s for s in SOURCES if args.source in s.name]
        if not sources:
            print(f"[ERROR] Источник '{args.source}' не найден в SOURCES")
            sys.exit(1)

    # Сканирование
    scan_sources(sources)

    if args.scan_only:
        print_stats()
        return

    # Обработка
    limit = args.limit if args.limit > 0 else 10_000_000
    processed = 0
    batch_size = 50

    while processed < limit:
        fetch = min(batch_size, limit - processed)
        rows = get_pending(limit=fetch)
        if not rows:
            break

        for row in rows:
            process_file(row, dry_run=dry_run)
            processed += 1
            if processed % 100 == 0:
                stats = get_stats()
                print(f"\n[PROGRESS] Обработано: {processed} | "
                      f"pending: {stats.get('pending', 0)} | "
                      f"processed: {stats.get('processed', 0)} | "
                      f"skipped: {stats.get('skipped', 0)} | "
                      f"error: {stats.get('error', 0)}\n")

    print("\n[DONE]")
    print_stats()


if __name__ == "__main__":
    main()
