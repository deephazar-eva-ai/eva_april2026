import sys
from pathlib import Path

text = Path("sandbox/papers/attention.md").read_text(encoding="utf-8")
words = text.split()
chunks = []
start = 0
chunk_size = 400
overlap = 80
while start < len(words):
    end = start + chunk_size
    chunk_words = words[start:end]
    chunks.append(" ".join(chunk_words))
    if end >= len(words):
        break
    start += (chunk_size - overlap)

print(f"Total chunks: {len(chunks)}")
