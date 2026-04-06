"""
library_sorter/app.py  — v2.1

Двухпроходная стратегия:
  Проход 1 (--fast-only): только файлы с метаданными, confidence >= 0.85
                           остальные помечаются needs_deep
  Проход 2 (--deep):      только файлы needs_deep, полный LLM анализ

Использование:
  python app.py --fast-only          # быстрый проход
  python app.py --deep               # глубокий проход
  python app.py --execute --fast-only  # реальное перемещение, быстрый проход
  python app.py --stats              # статистика
  python app.py --scan-only          # только сканировать
  python app.py --limit 50           # ограничить количество файлов
"""
import argparse
import sys
from pathlib import Path

from config import (SOURCES, NEW_ROOT, BOOK_EXTENSIONS,
                    ARCHIVE_EXTENSIONS, ALLOWED_LANGUAGES,
                    CONFIDENCE_THRESHOLD, CATEGORIES)
from db import init_db, upsert_pending, get_pending, get_stats
from db import mark_processed, mark_skipped, mark_error, mark_needs_deep
from extractor import extract_text, extract_metadata
from llm import analyze_book, classify_by_metadata, build_filename, BookMetadata
from mover import move_file


# ---------------------------------------------------------------------------
# Вспомогательные функции
# ---------------------------------------------------------------------------

def _parse_last_name(author: str) -> str | None:
    if not author:
        return None
    parts = author.strip().split()
    return parts[0] if parts else None


def _parse_first_initial(author: str) -> str | None:
    if not author:
        return None
    parts = author.strip().split()
    if len(parts) >= 2:
        return parts[1][0] if parts[1] else None
    return None


def _save_result(source_path: Path, final_dest: Path, new_name: str,
                 meta: BookMetadata, llm_raw: str, dry_run: bool) -> None:
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
            if ext not in BOOK_EXTENSIONS and ext not in ARCHIVE_EXTENSIONS:
                continue
            if upsert_pending(str(path)):
                added += 1
    print(f"[SCAN] Добавлено в очередь: {added} файлов")
    return added


# ---------------------------------------------------------------------------
# Обработка одного файла
# ---------------------------------------------------------------------------

def process_file(row: dict, dry_run: bool, fast_only: bool = False) -> None:
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

    # -------------------------------------------------------------------
    # УРОВЕНЬ 1+2: Метаданные файла / имя файла → быстрая классификация
    # -------------------------------------------------------------------
    file_meta = extract_metadata(source_path)

    if file_meta.title and len(file_meta.title) > 5:
        try:
            cat = classify_by_metadata(
                author=file_meta.author or "",
                title=file_meta.title,
                filename=source_path.name,
            )
            llm_raw = cat.model_dump_json()

            # Проверка языка
            if cat.language and cat.language not in ALLOWED_LANGUAGES:
                mark_skipped(str(source_path),
                             f"unsupported_language:{cat.language}", llm_raw)
                print(f"  [SKIP/lang={cat.language}] {source_path.name}")
                return

            if (cat.category in CATEGORIES
                    and cat.confidence >= CONFIDENCE_THRESHOLD):
                # Успех быстрой классификации
                meta = BookMetadata(
                    identified=True,
                    author_last=_parse_last_name(file_meta.author or ""),
                    author_first=_parse_first_initial(file_meta.author or ""),
                    title=file_meta.title,
                    year=file_meta.year or None,
                    language=cat.language,
                    category=cat.category,
                    confidence=cat.confidence,
                )
                new_name = build_filename(meta, source_path)
                dest_dir = NEW_ROOT / meta.category
                final_dest = move_file(source_path, dest_dir, new_name,
                                       dry_run=dry_run)
                _save_result(source_path, final_dest, new_name,
                             meta, llm_raw, dry_run)
                print(f"  [FAST {'DRY' if dry_run else 'OK'}] "
                      f"{source_path.name} → {meta.category}")
                return
            else:
                # Низкий confidence — нужен глубокий анализ
                if fast_only:
                    mark_needs_deep(str(source_path))
                    print(f"  [→DEEP] {source_path.name} "
                          f"(conf={cat.confidence:.2f})")
                    return
        except Exception as e:
            if fast_only:
                mark_needs_deep(str(source_path))
                print(f"  [→DEEP/err] {source_path.name}: {e}")
                return
            print(f"  [WARN] {source_path.name}: {e} → LLM")

    elif fast_only:
        # Нет метаданных — нужен глубокий анализ
        mark_needs_deep(str(source_path))
        print(f"  [→DEEP] {source_path.name} (нет метаданных)")
        return

    # -------------------------------------------------------------------
    # УРОВЕНЬ 3: Полный анализ текста через LLM
    # -------------------------------------------------------------------
    text = extract_text(source_path)

    try:
        meta: BookMetadata = analyze_book(source_path.name, text)
    except Exception as e:
        mark_error(str(source_path), f"llm_error: {e}")
        print(f"  [ERROR/llm] {source_path.name}: {e}")
        return

    llm_raw = meta.model_dump_json()

    if meta.language and meta.language not in ALLOWED_LANGUAGES:
        mark_skipped(str(source_path),
                     f"unsupported_language:{meta.language}", llm_raw)
        print(f"  [SKIP/lang={meta.language}] {source_path.name}")
        return

    if not meta.identified or meta.confidence < CONFIDENCE_THRESHOLD:
        reason = meta.skip_reason or f"low_confidence:{meta.confidence:.2f}"
        mark_skipped(str(source_path), reason, llm_raw)
        print(f"  [SKIP/{reason}] {source_path.name}")
        return

    if meta.category not in CATEGORIES:
        mark_skipped(str(source_path),
                     f"invalid_category:{meta.category}", llm_raw)
        print(f"  [SKIP/invalid_category] {source_path.name}: {meta.category}")
        return

    dest_dir = NEW_ROOT / meta.category
    new_name = build_filename(meta, source_path)
    final_dest = move_file(source_path, dest_dir, new_name, dry_run=dry_run)
    _save_result(source_path, final_dest, new_name, meta, llm_raw, dry_run)


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
    parser = argparse.ArgumentParser(description="Сортировщик библиотеки NetMind v2.1")
    parser.add_argument("--execute", action="store_true",
                        help="Реальное перемещение файлов")
    parser.add_argument("--stats", action="store_true",
                        help="Показать статистику и выйти")
    parser.add_argument("--scan-only", action="store_true",
                        help="Только сканировать файлы")
    parser.add_argument("--fast-only", action="store_true",
                        help="Только быстрые файлы (с метаданными), "
                             "остальные → needs_deep")
    parser.add_argument("--deep", action="store_true",
                        help="Только глубокий анализ (needs_deep файлы)")
    parser.add_argument("--limit", type=int, default=0,
                        help="Максимум файлов за запуск (0 = без ограничений)")
    parser.add_argument("--source", type=str, default="",
                        help="Обработать только указанный источник")
    args = parser.parse_args()

    init_db()

    if args.stats:
        print_stats()
        return

    dry_run = not args.execute
    if dry_run:
        print("[MODE] DRY-RUN — файлы не перемещаются. "
              "Используй --execute для реального запуска.")
    else:
        print("[MODE] EXECUTE — файлы будут перемещены!")

    if args.fast_only:
        print("[PASS] БЫСТРЫЙ — только файлы с метаданными, "
              "остальные → needs_deep")
    elif args.deep:
        print("[PASS] ГЛУБОКИЙ — только needs_deep файлы")

    sources = SOURCES
    if args.source:
        sources = [s for s in SOURCES if args.source in s.name]
        if not sources:
            print(f"[ERROR] Источник '{args.source}' не найден")
            sys.exit(1)

    scan_sources(sources)

    if args.scan_only:
        print_stats()
        return

    limit = args.limit if args.limit > 0 else 10_000_000
    processed = 0
    batch_size = 50

    while processed < limit:
        fetch = min(batch_size, limit - processed)
        rows = get_pending(limit=fetch, include_deep=args.deep)
        if not rows:
            break

        for row in rows:
            process_file(row, dry_run=dry_run, fast_only=args.fast_only)
            processed += 1
            if processed % 100 == 0:
                stats = get_stats()
                print(f"\n[PROGRESS] {processed} | "
                      f"pending: {stats.get('pending', 0)} | "
                      f"needs_deep: {stats.get('needs_deep', 0)} | "
                      f"processed: {stats.get('processed', 0)} | "
                      f"skipped: {stats.get('skipped', 0)}\n")

    print("\n[DONE]")
    print_stats()


if __name__ == "__main__":
    main()
