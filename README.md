# Library Sorter

Инструмент для автоматической сортировки личной электронной библиотеки с использованием локального LLM.

## Возможности

- Сканирование книг в форматах PDF, DjVu, FB2, EPUB, DOC и др.
- Классификация по тематике через локальный LLM (Ollama)
- Переименование файлов в единый формат (транслит)
- Структурированное хранение в 98 папках по 13 разделам
- SQLite БД для отслеживания прогресса и возобновления
- Dry-run режим по умолчанию

## Стек

Python 3.11 · LangChain · Ollama (qwen2.5:7b) · Pydantic · SQLite

## Установка
```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
sudo apt install poppler-utils djvulibre-bin antiword unrtf
cp .env.example .env
# Отредактировать .env — указать пути
```

## Использование
```bash
# Сканировать файлы в БД
python app.py --scan-only

# Dry-run — показать план без перемещения
python app.py --limit 20

# Реальная обработка
python app.py --execute --limit 100

# Статистика
python app.py --stats
```

## Структура библиотеки

98 папок в 13 разделах: Техника, IT, Науки, Бизнес, Гуманитарные,
История/Политика, Военное дело, Художественная, Справочники,
Журналы, Языки, Искусство/Дизайн, Кулинария.
