"""
reset_db.py — Утилита для сброса статусов файлов в БД
"""
import sqlite3
from config import DB_PATH

def reset_to_pending():
    """Сбрасывает все обработанные файлы обратно в pending."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Статистика до сброса
    cursor.execute("SELECT status, COUNT(*) FROM files GROUP BY status")
    print("\n=== ДО СБРОСА ===")
    for status, count in cursor.fetchall():
        print(f"  {status}: {count}")
    
    # Сброс всех в pending
    cursor.execute("""
        UPDATE files 
        SET status = 'pending',
            dest_path = NULL,
            new_name = NULL,
            skip_reason = NULL,
            llm_raw = NULL,
            author = NULL,
            title = NULL,
            year = NULL,
            language = NULL,
            category = NULL,
            confidence = NULL,
            processed_at = NULL
        WHERE status IN ('processed', 'skipped', 'error', 'needs_deep')
    """)
    
    affected = cursor.rowcount
    conn.commit()
    
    # Статистика после
    cursor.execute("SELECT status, COUNT(*) FROM files GROUP BY status")
    print("\n=== ПОСЛЕ СБРОСА ===")
    for status, count in cursor.fetchall():
        print(f"  {status}: {count}")
    
    print(f"\nСброшено записей: {affected}")
    conn.close()

if __name__ == "__main__":
    import sys
    
    if len(sys.argv) < 2:
        print("Использование:")
        print("  python reset_db.py --reset    # Сбросить все в pending")
        sys.exit(1)
    
    action = sys.argv[1]
    
    if action == "--reset":
        reset_to_pending()
    else:
        print(f"Неизвестная команда: {action}")
        sys.exit(1)
