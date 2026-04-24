with open("config.py", "r", encoding="utf-8", errors="replace") as f:
    src = f.read()

if "NO_PROXY" not in src:
    with open("config.py", "w", encoding="utf-8") as f:
        f.write("import os\nos.environ['NO_PROXY'] = 'localhost,127.0.0.1'\n\n" + src)
    print("OK - добавлено")
else:
    print("OK - уже есть")
