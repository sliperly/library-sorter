import re

patch = """
def analyze_book(filename: str, text: str) -> BookMetadata:
    import ollama as ollama_sdk
    client = ollama_sdk.Client(host=OLLAMA_BASE_URL)
    text_for_llm = text[:4000] if text else "(no text)"
    categories_str = _build_categories_str()
    system = SYSTEM_PROMPT.format(categories=categories_str)
    user = USER_PROMPT.format(filename=filename, text=text_for_llm)
    response = client.chat(
        model=OLLAMA_MODEL,
        messages=[
            {"role": "system", "content": system},
            {"role": "user",   "content": user},
        ],
        think=False,
        format=BookMetadata.model_json_schema(),
        options={"temperature": 0},
    )
    return BookMetadata.model_validate_json(response.message.content)
"""

with open("llm.py", "r", encoding="utf-8", errors="replace") as f:
    src = f.read()

new_src = re.sub(r"def analyze_book\(.*?return BookMetadata.*?\n", patch, src, flags=re.DOTALL)

with open("llm.py", "w", encoding="utf-8") as f:
    f.write(new_src)

print("OK")
