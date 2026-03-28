"""
review_dupes.py — интерактивный просмотр и удаление дубликатов

Использование:
  python review_dupes.py rmlint_full.json
  python review_dupes.py rmlint_full.json --batch 10   # по 10 групп за раз
  python review_dupes.py rmlint_full.json --only-books  # только книжные форматы
  python review_dupes.py rmlint_full.json --stats       # только статистика
"""

import json
import os
import sys
import argparse
from pathlib import Path
from collections import defaultdict

BOOK_EXTENSIONS = {
    ".pdf", ".djvu", ".djv", ".fb2", ".epub", ".mobi",
    ".doc", ".docx", ".rtf", ".chm", ".txt"
}

def load_groups(json_path: str, only_books: bool) -> list[list[dict]]:
    """Загружает JSON и группирует дубликаты."""
    with open(json_path, encoding="utf-8") as f:
        data = json.load(f)

    # rmlint помечает оригинал type=duplicate_file is_original=true
    # остальные в группе — дубликаты для удаления
    raw_groups = defaultdict(list)
    for item in data:
        if item.get("type") != "duplicate_file":
            continue
        key = item.get("checksum", "")
        if not key:
            continue
        raw_groups[key].append(item)

    groups = []
    for key, items in raw_groups.items():
        if len(items) < 2:
            continue
        if only_books:
            has_book = any(
                Path(i["path"]).suffix.lower() in BOOK_EXTENSIONS
                for i in items
            )
            if not has_book:
                continue
        groups.append(items)

    # Сортируем: сначала группы с книжными файлами
    def sort_key(g):
        ext = Path(g[0]["path"]).suffix.lower()
        return (0 if ext in BOOK_EXTENSIONS else 1, ext)

    groups.sort(key=sort_key)
    return groups


def fmt_size(size: int) -> str:
    for unit in ("Б", "КБ", "МБ", "ГБ"):
        if size < 1024:
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} ТБ"


def show_group(idx: int, total: int, items: list[dict]) -> None:
    """Выводит одну группу дубликатов."""
    print(f"\n{'═'*60}")
    print(f"Группа {idx}/{total}  |  файлов в группе: {len(items)}")
    print(f"{'─'*60}")

    # Оригинал — тот у кого is_original=True, иначе первый
    original = next((i for i in items if i.get("is_original")), items[0])
    duplicates = [i for i in items if i is not original]

    print(f"  ОСТАВИТЬ (оригинал):")
    print(f"    {original['path']}")
    print(f"    Размер: {fmt_size(original['size'])}")
    print(f"  УДАЛИТЬ ({len(duplicates)} шт., освободит "
          f"{fmt_size(sum(d['size'] for d in duplicates))}):")
    for d in duplicates:
        print(f"    {d['path']}")
    print(f"{'─'*60}")


def prompt() -> str:
    """Запрашивает действие у пользователя."""
    print("  [y] удалить дубликаты  "
          "[n] пропустить  "
          "[s] поменять оригинал  "
          "[q] выйти")
    return input("  Выбор: ").strip().lower()


def pick_original(items: list[dict]) -> dict:
    """Позволяет выбрать другой файл как оригинал."""
    print("\n  Выберите оригинал (остальные будут удалены):")
    for i, item in enumerate(items):
        print(f"    [{i}] {item['path']}  ({fmt_size(item['size'])})")
    while True:
        try:
            choice = int(input("  Номер: ").strip())
            if 0 <= choice < len(items):
                return items[choice]
        except ValueError:
            pass
        print("  Неверный номер, попробуй ещё раз.")


def process_groups(groups: list[list[dict]], batch: int) -> None:
    total = len(groups)
    deleted_files = 0
    deleted_bytes = 0
    skipped = 0

    i = 0
    while i < total:
        batch_groups = groups[i:i+batch]

        for items in batch_groups:
            i += 1
            original = next((x for x in items if x.get("is_original")), items[0])
            duplicates = [x for x in items if x is not original]

            show_group(i, total, items)

            while True:
                action = prompt()

                if action == "q":
                    print(f"\n[СТОП] Удалено: {deleted_files} файлов "
                          f"({fmt_size(deleted_bytes)}), "
                          f"пропущено групп: {skipped}")
                    return

                elif action == "n":
                    skipped += 1
                    break

                elif action == "s":
                    original = pick_original(items)
                    duplicates = [x for x in items if x is not original]
                    show_group(i, total, items)
                    # После смены — снова показываем и спрашиваем

                elif action == "y":
                    for d in duplicates:
                        path = Path(d["path"])
                        if path.exists():
                            size = path.stat().st_size
                            path.unlink()
                            deleted_files += 1
                            deleted_bytes += size
                            print(f"  [УДАЛЁН] {path.name}")
                        else:
                            print(f"  [НЕ НАЙДЕН] {d['path']}")
                    break

                else:
                    print("  Неизвестная команда.")

        # После каждого батча — промежуточная статистика
        if i < total:
            print(f"\n{'━'*60}")
            print(f"  Прогресс: {i}/{total} групп  |  "
                  f"Удалено: {deleted_files} файлов ({fmt_size(deleted_bytes)})")
            cont = input("  Продолжить следующий батч? [Enter/q]: ").strip().lower()
            if cont == "q":
                break

    print(f"\n{'━'*60}")
    print(f"[ГОТОВО] Обработано групп: {i}/{total}")
    print(f"         Удалено файлов:   {deleted_files}")
    print(f"         Освобождено:      {fmt_size(deleted_bytes)}")
    print(f"         Пропущено групп:  {skipped}")


def print_stats(groups: list[list[dict]]) -> None:
    total_groups = len(groups)
    total_dupes = sum(len(g) - 1 for g in groups)
    total_bytes = sum(
        item["size"]
        for g in groups
        for item in g
        if not item.get("is_original")
    )
    by_ext = defaultdict(lambda: [0, 0])  # ext → [count, bytes]
    for g in groups:
        for item in g:
            if not item.get("is_original"):
                ext = Path(item["path"]).suffix.lower() or "(нет)"
                by_ext[ext][0] += 1
                by_ext[ext][1] += item["size"]

    print(f"\n{'═'*60}")
    print(f"  Групп дубликатов:  {total_groups}")
    print(f"  Файлов к удалению: {total_dupes}")
    print(f"  Можно освободить:  {fmt_size(total_bytes)}")
    print(f"\n  По расширениям (топ-15):")
    for ext, (cnt, size) in sorted(
            by_ext.items(), key=lambda x: -x[1][1])[:15]:
        print(f"    {ext:10s}  {cnt:5d} файлов  {fmt_size(size)}")
    print(f"{'═'*60}")


def main():
    parser = argparse.ArgumentParser(description="Интерактивное удаление дубликатов")
    parser.add_argument("json_file", help="Путь к rmlint JSON файлу")
    parser.add_argument("--batch", type=int, default=20,
                        help="Групп за один показ (default: 20)")
    parser.add_argument("--only-books", action="store_true",
                        help="Показывать только группы с книжными файлами")
    parser.add_argument("--stats", action="store_true",
                        help="Только статистика, без интерактива")
    args = parser.parse_args()

    if not Path(args.json_file).exists():
        print(f"[ERROR] Файл не найден: {args.json_file}")
        sys.exit(1)

    print(f"[ЗАГРУЗКА] {args.json_file} ...")
    groups = load_groups(args.json_file, args.only_books)
    print(f"[OK] Загружено групп: {len(groups)}")

    print_stats(groups)

    if args.stats:
        return

    if not groups:
        print("Дубликатов не найдено.")
        return

    print(f"\nНачинаем просмотр. Батч по {args.batch} групп.")
    input("  [Enter] для старта, Ctrl+C для отмены...")

    process_groups(groups, args.batch)


if __name__ == "__main__":
    main()
