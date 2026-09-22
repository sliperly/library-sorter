#!/usr/bin/env python3
"""
scan_library.py — обзорное сканирование книжного хранилища.
Только читает файловую систему, ничего не создаёт, не двигает, не удаляет.
Не требует установки пакетов — только стандартная библиотека Python.

Использование:
  python scan_library.py "D:\Books"
  python scan_library.py "D:\Books" --out report.txt

Может занять несколько минут на десятках тысяч файлов — это нормально.
"""
import sys
from pathlib import Path
from collections import Counter, defaultdict


def is_cryptic_name(name: str) -> bool:
    """Эвристика: короткое имя без пробелов и почти без гласных — похоже на
    техническое/игровое имя (BITWA, NANOTECH), а не на название книги/темы."""
    if len(name) > 10 or " " in name:
        return False
    if any(ch.isalpha() and ch.lower() not in "abcdefghijklmnopqrstuvwxyz" for ch in name):
        return False  # не-латинские буквы — не похоже на игровой техноним
    letters = [c for c in name if c.isalpha()]
    if not letters:
        return False
    vowels = sum(1 for c in letters if c.lower() in "aeiou")
    return vowels / len(letters) < 0.25


def main():
    if len(sys.argv) < 2:
        print("Использование: python scan_library.py <путь> [--out файл.txt]")
        sys.exit(1)

    root = Path(sys.argv[1]).resolve()
    out_path = None
    if "--out" in sys.argv:
        out_path = Path(sys.argv[sys.argv.index("--out") + 1])

    ext_count = Counter()
    ext_size = Counter()
    depth_count = Counter()
    top_level = defaultdict(lambda: [0, 0])
    cryptic_dirs = []
    dir_child_sample = defaultdict(list)
    total_files = 0
    total_bytes = 0
    max_depth_seen = 0

    root_depth = len(root.parts)
    print(f"Сканирую {root} ...")

    for dirpath, dirnames, filenames in __import__("os").walk(root):
        dirpath_p = Path(dirpath)
        depth = len(dirpath_p.parts) - root_depth

        try:
            rel = dirpath_p.relative_to(root)
            top = rel.parts[0] if rel.parts else None
        except ValueError:
            top = None

        if len(dirnames) >= 15:
            cryptic_ratio = sum(1 for d in dirnames if is_cryptic_name(d)) / len(dirnames)
            if cryptic_ratio > 0.6:
                cryptic_dirs.append((str(rel) if rel.parts else ".", len(dirnames), f"{cryptic_ratio:.0%}"))

        if depth in (1, 2):
            sample = dir_child_sample[depth]
            if len(sample) < 40:
                sample.extend(dirnames[: 40 - len(sample)])

        for fname in filenames:
            total_files += 1
            ext = Path(fname).suffix.lower() or "(без расширения)"
            ext_count[ext] += 1
            try:
                size = (dirpath_p / fname).stat().st_size
            except OSError:
                size = 0
            ext_size[ext] += size
            total_bytes += size
            depth_count[depth] += 1
            if top:
                top_level[top][0] += 1
                top_level[top][1] += size

        max_depth_seen = max(max_depth_seen, depth)

    lines = []
    lines.append(f"=== Обзор {root} ===\n")
    lines.append(f"Всего файлов: {total_files:,}".replace(",", " "))
    lines.append(f"Общий размер: {total_bytes / (1024**3):.1f} ГБ")
    lines.append(f"Максимальная глубина вложенности: {max_depth_seen}\n")

    lines.append("--- По расширениям (топ-30 по количеству) ---")
    for ext, cnt in ext_count.most_common(30):
        gb = ext_size[ext] / (1024**3)
        lines.append(f"  {ext:20s} {cnt:8,d} файлов   {gb:8.2f} ГБ".replace(",", " "))

    lines.append("\n--- По папкам верхнего уровня (по размеру) ---")
    for top, (cnt, size) in sorted(top_level.items(), key=lambda x: -x[1][1]):
        gb = size / (1024**3)
        lines.append(f"  {top:50s} {cnt:8,d} файлов   {gb:8.2f} ГБ".replace(",", " "))

    lines.append("\n--- Примеры подпапок 1-го уровня (до 40) ---")
    lines.extend(f"  {n}" for n in dir_child_sample.get(1, []))

    lines.append("\n--- Примеры подпапок 2-го уровня (до 40) ---")
    lines.extend(f"  {n}" for n in dir_child_sample.get(2, []))

    if cryptic_dirs:
        lines.append("\n--- Папки, ПОХОЖИЕ на технические/игровые архивы (не книги) ---")
        lines.append("  (много коротких подпапок без гласных/пробелов — вероятно не книги;")
        lines.append("   это эвристика, не факт — стоит проверить глазами)")
        for path, n, ratio in cryptic_dirs[:30]:
            lines.append(f"  {path}  ({n} подпапок, {ratio} похожи на техноимена)")

    report = "\n".join(lines)
    print("\n" + report)
    if out_path:
        out_path.write_text(report, encoding="utf-8")
        print(f"\n[Сохранено в {out_path}]")


if __name__ == "__main__":
    main()
