with open("llm.py", "r", encoding="utf-8") as f:
    src = f.read()

src = src.replace(
    'category: str = Field(description="Категория из списка допустимых")',
    'category: str = Field(default="_Unprocessed", description="Категория из списка допустимых")'
)

with open("llm.py", "w", encoding="utf-8") as f:
    f.write(src)

print("OK")
