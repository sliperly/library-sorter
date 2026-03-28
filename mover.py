"""
Перемещение файла из source в destination.
В dry-run режиме только логирует, ничего не делает.
"""
import shutil
from pathlib import Path


def move_file(source: Path, dest_dir: Path, new_name: str,
              dry_run: bool = True) -> Path:
    """
    Перемещает source → dest_dir / new_name.
    Если файл с таким именем уже существует — добавляет суффикс _2, _3 и т.д.
    Возвращает финальный путь назначения.
    """
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / new_name

    # Разрешение конфликта имён
    if dest.exists() and dest != source:
        stem = dest.stem
        ext = dest.suffix
        counter = 2
        while dest.exists():
            dest = dest_dir / f"{stem}_{counter}{ext}"
            counter += 1

    if dry_run:
        print(f"  [DRY-RUN] {source} → {dest}")
    else:
        shutil.move(str(source), str(dest))
        print(f"  [MOVED]   {source.name} → {dest}")

    return dest
