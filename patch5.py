with open("llm.py", "r", encoding="utf-8") as f:
    src = f.read()

src = src.replace(
    'year: Optional[str] = Field(None, description="Год издания, 4 цифры")',
    'year: Optional[Union[str, int]] = Field(None, description="Год издания, 4 цифры")'
)
src = src.replace(
    'category: str = Field(default="_Unprocessed", description="Категория из списка допустимых")',
    'category: Optional[str] = Field(default="_Unprocessed", description="Категория из списка допустимых")'
)
src = src.replace(
    "from typing import Optional",
    "from typing import Optional, Union"
)

# Добавить нормализацию после model_validate_json
src = src.replace(
    "    return BookMetadata.model_validate_json(raw)",
    """    meta = BookMetadata.model_validate_json(raw)
    if meta.year is not None:
        meta.year = str(meta.year)
    if not meta.category:
        meta.category = "_Unprocessed"
    return meta"""
)

with open("llm.py", "w", encoding="utf-8") as f:
    f.write(src)

print("OK")
