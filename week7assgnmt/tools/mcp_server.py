"""
MCP server for EAGV3 Session 6.

Nine tools, stdio transport:
    web_search, fetch_url, get_time, currency_convert,
    read_file, list_dir, create_file, update_file, edit_file

web_search:  Tavily primary, DuckDuckGo fallback. Hard-capped at 5 results.
fetch_url:   crawl4ai only — clean markdown via headless Chromium.
Usage for tavily and duckduckgo is logged to ./usage.json with monthly
rollover and a soft cap of 950/1000 on Tavily.

File tools are sandboxed under ./sandbox/. Run:  python mcp_server.py
"""

from __future__ import annotations

import json
import os
import sys
import threading
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

_project_root = str(Path(__file__).parent.parent.resolve())
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

import httpx
from ddgs import DDGS
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

MAX_SEARCH_RESULTS = 5  # hard cap — Tavily prices per result

load_dotenv(Path(__file__).parent.parent / ".env")

mcp = FastMCP("eagv3-s6-server")

SANDBOX = Path(__file__).parent.parent / "sandbox"
SANDBOX.mkdir(exist_ok=True)

USAGE_PATH = Path(__file__).parent / "usage.json"
MONTHLY_CAP = 950  # leave 50/mo headroom on Tavily
_usage_lock = threading.Lock()


def _safe(path: str) -> Path:
    if path.startswith("sandbox/"):
        path = path[len("sandbox/"):]
    elif path.startswith("./sandbox/"):
        path = path[len("./sandbox/"):]
    p = (SANDBOX / path).resolve()
    base = SANDBOX.resolve()
    if p != base and base not in p.parents:
        raise ValueError(f"Path '{path}' escapes the sandbox")
    return p


def _empty_usage(month: str) -> dict:
    return {
        "month": month,
        "tavily": {"count": 0, "errors": 0},
        "duckduckgo": {"count": 0, "errors": 0},
    }


def _load_usage() -> dict:
    month = datetime.now().strftime("%Y-%m")
    if not USAGE_PATH.exists():
        return _empty_usage(month)
    try:
        data = json.loads(USAGE_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return _empty_usage(month)
    if data.get("month") != month:
        return _empty_usage(month)
    for k in ("tavily", "duckduckgo"):
        data.setdefault(k, {"count": 0, "errors": 0})
    return data


def _save_usage(data: dict) -> None:
    USAGE_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _bump(provider: str, field: str = "count") -> None:
    with _usage_lock:
        data = _load_usage()
        data[provider][field] = data[provider].get(field, 0) + 1
        _save_usage(data)


def _under_cap(provider: str) -> bool:
    return _load_usage()[provider]["count"] < MONTHLY_CAP


def _tavily_search(query: str, max_results: int) -> list[dict]:
    from tavily import TavilyClient

    client = TavilyClient(os.environ["TAVILY_API_KEY"])
    resp = client.search(query=query, max_results=max_results, search_depth="advanced")
    return [
        {
            "title": r.get("title", ""),
            "url": r.get("url", ""),
            "snippet": r.get("content", ""),
        }
        for r in resp.get("results", [])
    ]


def _ddg_search(query: str, max_results: int) -> list[dict]:
    hits: list[dict] = []
    with DDGS() as ddgs:
        for backend in ("auto", "html", "lite"):
            try:
                hits = list(ddgs.text(query, max_results=max_results, backend=backend))
            except Exception:
                hits = []
            if hits:
                break
    return [
        {
            "title": h.get("title", ""),
            "url": h.get("href", ""),
            "snippet": h.get("body", ""),
        }
        for h in hits
    ]


def _sync_crawl_fetch(url: str) -> dict:
    import asyncio
    import os
    saved_fd = os.dup(1)
    os.dup2(2, 1)
    try:
        from crawl4ai import AsyncWebCrawler
        async def _do_crawl():
            async with AsyncWebCrawler(verbose=False) as crawler:
                r = await crawler.arun(url=url)
            md = r.markdown
            raw = (
                getattr(md, "raw_markdown", None)
                or getattr(md, "fit_markdown", None)
                or md
                or r.cleaned_html
                or r.html
                or ""
            )
            text = str(raw)
            return {
                "status": int(getattr(r, "status_code", None) or 200),
                "content_type": "text/markdown",
                "length_bytes": len(text.encode("utf-8")),
                "text": text,
            }
        return asyncio.run(_do_crawl())
    finally:
        os.dup2(saved_fd, 1)
        os.close(saved_fd)

_crawl_pool = None

async def _crawl4ai_fetch(url: str) -> dict:
    global _crawl_pool
    if _crawl_pool is None:
        import multiprocessing
        from concurrent.futures import ProcessPoolExecutor
        ctx = multiprocessing.get_context("spawn")
        _crawl_pool = ProcessPoolExecutor(max_workers=3, mp_context=ctx)

    import asyncio
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(_crawl_pool, _sync_crawl_fetch, url)


@mcp.tool()
def web_search(query: str, max_results: int = 5) -> list[dict]:
    """Search the live web (Tavily primary, DDG fallback). Hard-capped at 5 results. USE THIS ONLY IF THE USER EXPLICITLY ASKS TO SEARCH THE WEB. Otherwise, use search_knowledge to query the local FAISS index. Example: web_search("python asyncio tutorial", 3)."""
    max_results = max(1, min(max_results, MAX_SEARCH_RESULTS))
    if os.environ.get("TAVILY_API_KEY") and _under_cap("tavily"):
        try:
            results = _tavily_search(query, max_results)
            if results:
                _bump("tavily")
                return results
        except Exception:
            _bump("tavily", "errors")
    results = _ddg_search(query, max_results)
    _bump("duckduckgo")
    return results


@mcp.tool()
async def fetch_url(url: str, timeout: int = 20) -> dict:
    """Fetch clean markdown from a URL via crawl4ai (headless Chromium). Example: fetch_url("https://example.com")."""
    return await _crawl4ai_fetch(url)


@mcp.tool()
def get_time(timezone: str = "UTC") -> dict:
    """Current time in a named IANA timezone. Example: get_time("Asia/Kolkata")."""
    tz = ZoneInfo(timezone)
    now = datetime.now(tz)
    offset = now.utcoffset()
    offset_hours = offset.total_seconds() / 3600 if offset else 0.0
    return {
        "iso": now.isoformat(),
        "human": now.strftime("%A, %d %B %Y %H:%M:%S %Z"),
        "timezone": timezone,
        "offset_hours": offset_hours,
    }


@mcp.tool()
def currency_convert(amount: float, from_currency: str, to_currency: str) -> dict:
    """Convert money between ISO-3 currencies via frankfurter.dev. Example: currency_convert(100, "USD", "INR")."""
    f = from_currency.upper()
    t = to_currency.upper()
    url = f"https://api.frankfurter.dev/v1/latest?amount={amount}&base={f}&symbols={t}"
    with httpx.Client(timeout=20, follow_redirects=True) as client:
        r = client.get(url)
        r.raise_for_status()
        data = r.json()
    converted = data["rates"][t]
    return {
        "amount": amount,
        "from": f,
        "to": t,
        "rate": converted / amount if amount else 0.0,
        "converted": converted,
        "date": data["date"],
        "source": "frankfurter.dev",
    }


@mcp.tool()
def read_file(path: str) -> dict:
    """Read a UTF-8 text file from the sandbox. Example: read_file("notes.txt")."""
    p = _safe(path)
    text = p.read_text(encoding="utf-8")
    return {
        "path": path,
        "size_bytes": p.stat().st_size,
        "content": text,
        "encoding": "utf-8",
    }


@mcp.tool()
def list_dir(path: str = ".") -> list[dict]:
    """List a directory inside the sandbox. Example: list_dir(".")."""
    p = _safe(path)
    out = []
    for child in sorted(p.iterdir()):
        is_dir = child.is_dir()
        out.append({
            "name": child.name,
            "type": "dir" if is_dir else "file",
            "size_bytes": 0 if is_dir else child.stat().st_size,
        })
    return out


@mcp.tool()
def create_file(path: str, content: str) -> dict:
    """Create a new file in the sandbox; errors if it exists. Example: create_file("hello.txt", "hi")."""
    p = _safe(path)
    if p.exists():
        raise ValueError(f"File '{path}' already exists")
    if not p.parent.exists():
        raise ValueError(f"Parent directory of '{path}' does not exist")
    p.write_text(content, encoding="utf-8")
    return {"ok": True, "path": path, "size_bytes": p.stat().st_size}


@mcp.tool()
def update_file(path: str, content: str) -> dict:
    """Overwrite an existing sandbox file. Example: update_file("hello.txt", "new body")."""
    p = _safe(path)
    if not p.exists():
        raise ValueError(f"File '{path}' does not exist")
    p.write_text(content, encoding="utf-8")
    return {"ok": True, "path": path, "size_bytes": p.stat().st_size}


@mcp.tool()
def edit_file(path: str, find: str, replace: str, replace_all: bool = False) -> dict:
    """Find-and-replace inside a sandbox file. Example: edit_file("hello.txt", "foo", "bar")."""
    p = _safe(path)
    text = p.read_text(encoding="utf-8")
    count = text.count(find)
    if count == 0:
        raise ValueError(f"'{find}' not found in '{path}'")
    if count > 1 and not replace_all:
        raise ValueError(
            f"'{find}' occurs {count} times in '{path}'; pass replace_all=True"
        )
    new_text = text.replace(find, replace) if replace_all else text.replace(find, replace, 1)
    p.write_text(new_text, encoding="utf-8")
    replacements = count if replace_all else 1
    return {
        "ok": True,
        "path": path,
        "replacements": replacements,
        "size_bytes": p.stat().st_size,
    }


@mcp.tool()
def index_document(path: str, chunk_size: int = 400, overlap: int = 80) -> dict:
    """Chunk a sandbox file, directory, or artifact and write the chunks into Memory as
    fact records, where they become FAISS-searchable for later queries.
    Use this when the content must be searchable across later turns or runs.
    For one-shot inspection of a file's contents, use read_file."""
    from core.memory import MemoryService
    from core.artifacts import ArtifactStore
    import uuid

    if path.startswith("sandbox/"):
        path = path[len("sandbox/"):]
    elif path.startswith("./sandbox/"):
        path = path[len("./sandbox/"):]

    mem = MemoryService(storage_path=str(Path(__file__).parent.parent / "state" / "memory.json"))
    run_id = str(uuid.uuid4())

    files_to_process = []

    if path.startswith("art:"):
        store = ArtifactStore(storage_dir=str(Path(__file__).parent.parent / "state" / "artifacts"))
        if not store.exists(path):
            raise ValueError(f"Artifact '{path}' does not exist")
        blob = store.get_bytes(path)
        try:
            text = blob.decode("utf-8")
            files_to_process.append((f"artifact:{path}", path, text))
        except UnicodeDecodeError:
            raise ValueError(f"Artifact '{path}' is binary and cannot be indexed.")
    else:
        p = _safe(path)
        if not p.exists():
            raise ValueError(f"Path '{path}' does not exist")

        if p.is_dir():
            if p.resolve() == SANDBOX.resolve():
                raise ValueError("Indexing the entire sandbox root directory is not allowed. Please specify a specific subdirectory.")
            
            for child in p.rglob("*"):
                if child.is_file() and child.suffix.lower() in (".md", ".txt"):
                    try:
                        text = child.read_text(encoding="utf-8")
                        rel_path = str(child.relative_to(SANDBOX))
                        files_to_process.append((f"sandbox:{rel_path}", rel_path, text))
                    except Exception:
                        pass
        else:
            text = p.read_text(encoding="utf-8")
            files_to_process.append((f"sandbox:{path}", path, text))

    all_facts = []

    for prefix, source_path, text in files_to_process:
        words = text.split()
        chunks = []
        start = 0
        while start < len(words):
            end = start + chunk_size
            chunk_words = words[start:end]
            chunks.append(" ".join(chunk_words))
            if end >= len(words):
                break
            start += (chunk_size - overlap)

        total = len(chunks)
        for i, chunk in enumerate(chunks):
            tag = f"[{prefix} chunk {i+1}/{total}]"
            descriptor = f"{tag} {chunk[:60]}".strip()

            all_facts.append({
                "descriptor": descriptor,
                "raw_text": chunk,
                "keywords": list(mem._tokenize(chunk)),
                "structured_value": {},
                "source": source_path,
                "run_id": run_id
            })

    if all_facts:
        mem.add_facts_batch(all_facts)

    return {"ok": True, "path": path, "files_processed": len(files_to_process), "chunks_indexed": len(all_facts)}


@mcp.tool()
def search_knowledge(query: str, k: int = 5) -> list[dict]:
    """Vector search over previously indexed fact chunks. Use this rather
    than re-fetching or re-reading source files when Memory already
    contains indexed chunks for the topic."""
    from core.memory import MemoryService
    from tools.supportingsearch import MemorySearch
    mem = MemoryService(storage_path=str(Path(__file__).parent.parent / "state" / "memory.json"))
    
    embedding = mem._try_embed(query)
    if not embedding:
        results = mem.read(query=query, kinds=["fact"], top_k=k)
        return [
            {
                "memory_id": r.memory_id,
                "source": r.source,
                "preview": r.descriptor,
                "text": r.raw_text,
                "metadata": r.structured_value,
                "score": getattr(r, "score", 0.0)
            }
            for r in results
        ]
        
    memory_store = {item.memory_id: item for item in mem._load()}
    searcher = MemorySearch(dimension=768, memory_store=memory_store)
    
    try:
        candidates = searcher.search(
            query_embedding=embedding,
            k=k,
            metadata_filter=lambda x: x.kind == "fact"
        )
    except Exception:
        candidates = []
        
    return [
        {
            "memory_id": c["memory_id"],
            "source": c["metadata"].source,
            "preview": c["metadata"].descriptor,
            "text": c["metadata"].raw_text,
            "metadata": c["metadata"].structured_value,
            "score": c["score"]
        }
        for c in candidates
    ]


if __name__ == "__main__":
    mcp.run(transport="stdio")