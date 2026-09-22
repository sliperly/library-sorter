"""
reset_returned_files.py — для случая, когда вы вручную вернули уже
обработанные (или помеченные как error/skipped) файлы обратно во входную
папку "Книги на обработку" для повторного тестирования.

Находит в БД записи со статусом НЕ pending, чей source_path совпадает
с файлом, который сейчас реально лежит во входной папке — и только их
сбрасывает в pending. Всё остальное в БД не трогает.

Использование:
  python reset_returned_files.py             # dry-run — только показать
  python reset_returned_files.py --execute   # реально сбросить
"""
import argparse
import sqlite3
from config import DB_PATH, SOURCES


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()

    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row

    current_files = set()
    for source_dir in SOURCES:
        if source_dir.exists():
            for p in source_dir.rglob("*"):
                if p.is_file():
                    current_files.add(str(p))

    rows = conn.execute(
        "SELECT source_path, status FROM files WHERE status != 'pending'"
    ).fetchall()

    to_reset = [r for r in rows if r["source_path"] in current_files]

    print(f"Файлов сейчас во входной папке: {len(current_files)}")
    print(f"Из них найдено в БД со статусом НЕ pending: {len(to_reset)}\n")
    for r in to_reset:
        print(f"  [{r['status']:10s}] {r['source_path']}")

    if not to_reset:
        print("\nНечего сбрасывать — либо все эти файлы уже pending, "
              "либо в БД их вообще нет (тогда --scan-only подхватит "
              "их как новые сам, ничего чинить не нужно).")
        return

    if not args.execute:
        print(f"\n[DRY-RUN] Запустите с --execute, чтобы реально "
              f"сбросить {len(to_reset)} записей в pending.")
        return

    for r in to_reset:
        conn.execute("""
            UPDATE files SET
                status='pending', dest_path=NULL, new_name=NULL,
                author=NULL, title=NULL, year=NULL, language=NULL,
                category=NULL, confidence=NULL, skip_reason=NULL,
                llm_raw=NULL, processed_at=NULL
            WHERE source_path=?
        """, (r["source_path"],))
    conn.commit()
    print(f"\nСброшено записей: {len(to_reset)}")


if __name__ == "__main__":
    main()
