"""
litres_probe.py — ПРОБНЫЙ скрипт, не подключён к пайплайну.

Для каждого запроса (название + автор) ищет книгу на litres.ru, открывает
первую найденную страницу и печатает: название, автора, ISBN, жанры
(с пометкой главного) и теги. Ничего не пишет ни в БД, ни на диск.

Использование (из корня проекта, venv активирован):
  python tools/litres_probe.py "Высоконагруженные приложения Клеппман" "Чистый Agile Мартин"

Между запросами пауза 3 секунды. Вход в аккаунт не используется.
"""
import json
import re
import sys
import time
from urllib.parse import quote

import requests

BASE = "https://www.litres.ru"
HEADERS = {"User-Agent": "library-sorter/0.1 (personal use, low volume)"}
PAUSE_SEC = 3


# ---------------------------------------------------------------------------
# Разбор HTML (чистые функции — их можно проверять без сети)
# ---------------------------------------------------------------------------

def find_book_links(search_html: str, limit: int = 3) -> list[str]:
    """Первые несколько уникальных ссылок вида /book/<автор>/<slug>/."""
    links = []
    for m in re.finditer(r'href="(/book/[^"#?]+/)"', search_html):
        if m.group(1) not in links:
            links.append(m.group(1))
        if len(links) >= limit:
            break
    return links


def _ld_json_book(page: str) -> dict:
    """Блок JSON-LD с @type=Book (название, автор, ISBN, страницы, год)."""
    for m in re.finditer(
        r'<script type="application/ld\+json">(.*?)</script>', page, re.S
    ):
        try:
            data = json.loads(m.group(1))
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict) and data.get("@type") == "Book":
            return data
    return {}


def _unescape(name: str) -> str:
    try:
        return json.loads('"' + name + '"')
    except json.JSONDecodeError:
        return name


def parse_genres_and_tags(page: str) -> tuple[list[tuple[str, bool]], list[str]]:
    """
    Жанры (имя, is_main) и теги. Основной источник — данные страницы,
    вшитые в HTML (там есть флаг is_main). Запасной — ссылки /genre/ и /tags/
    внутри блока «Жанры и теги».
    """
    genres = [
        (_unescape(m.group(1)), m.group(2) == "true")
        for m in re.finditer(
            r'\\"name\\":\\"([^\\"]+)\\",\\"is_root\\":(?:true|false),'
            r'\\"url\\":\\"/genre/[^\\"]+\\",\\"is_main\\":(true|false)',
            page,
        )
    ]
    tags = [
        _unescape(m.group(1))
        for m in re.finditer(
            r'\\"name\\":\\"([^\\"]+)\\",\\"is_root\\":(?:true|false),'
            r'\\"url\\":\\"/tags/[^\\"]+\\"',
            page,
        )
    ]
    if genres or tags:
        return genres, tags

    # Запасной путь: ссылки в блоке «Жанры и теги»
    idx = page.find("book-genres-and-tags__wrapper")
    if idx < 0:
        return [], []
    segment = page[idx: idx + 6000]
    for m in re.finditer(r'href="/(genre|tags)/[^"]+">([^<]+)</a>', segment):
        if m.group(1) == "genre":
            genres.append((m.group(2), False))
        else:
            tags.append(m.group(2))
    return genres, tags


def parse_book_page(page: str) -> dict:
    ld = _ld_json_book(page)
    author = ld.get("author")
    if isinstance(author, dict):
        author = author.get("name")
    genres, tags = parse_genres_and_tags(page)
    return {
        "title": ld.get("name"),
        "author": author,
        "isbn": ld.get("isbn"),
        "pages": ld.get("numberOfPages"),
        "year": ld.get("datePublished"),
        "genres": genres,
        "tags": tags,
    }


# ---------------------------------------------------------------------------
# Сеть
# ---------------------------------------------------------------------------

def _get(url: str) -> requests.Response:
    return requests.get(url, headers=HEADERS, timeout=15)


def probe(query: str) -> None:
    print(f"\n=== Запрос: {query}")
    search_url = f"{BASE}/search/?q={quote(query)}"
    resp = _get(search_url)
    print(f"  [поиск] HTTP {resp.status_code}, {len(resp.text)} байт")
    if resp.status_code != 200:
        print(f"  [поиск] не 200 — дальше не идём. Начало ответа: "
              f"{resp.text[:200]!r}")
        return

    links = find_book_links(resp.text)
    if not links:
        print("  [поиск] в ответе нет ссылок /book/... — возможно, результаты "
              "рисуются скриптом на стороне браузера. Начало ответа:")
        print(f"  {resp.text[:300]!r}")
        return
    print(f"  [поиск] кандидаты: {links}")

    time.sleep(PAUSE_SEC)
    book_url = BASE + links[0]
    resp = _get(book_url)
    print(f"  [книга] {book_url} → HTTP {resp.status_code}")
    if resp.status_code != 200:
        return

    info = parse_book_page(resp.text)
    print(f"  Название: {info['title']}")
    print(f"  Автор:    {info['author']}")
    print(f"  ISBN:     {info['isbn']}   стр.: {info['pages']}   год: {info['year']}")
    if info["genres"]:
        print("  Жанры:    " + "; ".join(
            f"{name}{' [главный]' if main else ''}" for name, main in info["genres"]
        ))
    else:
        print("  Жанры:    (не найдены)")
    print("  Теги:     " + ("; ".join(info["tags"]) if info["tags"] else "(не найдены)"))


def main() -> None:
    queries = sys.argv[1:]
    if not queries:
        print(__doc__)
        return
    for i, q in enumerate(queries):
        if i:
            time.sleep(PAUSE_SEC)
        try:
            probe(q)
        except requests.RequestException as e:
            print(f"  [ОШИБКА сети] {e}")


if __name__ == "__main__":
    main()
