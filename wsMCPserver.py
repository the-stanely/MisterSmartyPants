from __future__ import annotations

import json
import os
import re
from html import unescape
from typing import Any

import requests
from ddgs import DDGS
from mcp.server.fastmcp import FastMCP

SERVER_HOST = os.getenv("WS_MCP_HOST", "127.0.0.1")
SERVER_PORT = int(os.getenv("WS_MCP_PORT", "8099"))
SEARCH_LIMIT = int(os.getenv("WS_SEARCH_LIMIT", "12"))
FETCH_TOP_N = int(os.getenv("WS_FETCH_TOP_N", "3"))
FETCH_MAX_CHARS = int(os.getenv("WS_FETCH_MAX_CHARS", "12000"))
FETCH_SCAN_LIMIT = int(os.getenv("WS_FETCH_SCAN_LIMIT", "12"))
REQUEST_TIMEOUT_SECONDS = int(os.getenv("WS_REQUEST_TIMEOUT_SECONDS", "20"))
DEBUG = os.getenv("WS_DEBUG", "0") == "1"

mcp = FastMCP(name="wsMCPserver", host=SERVER_HOST, port=SERVER_PORT)


def _fetched_page_quality(page_obj: dict[str, Any]) -> tuple[bool, str]:
    content = page_obj.get("content")
    if not isinstance(content, str):
        return False, "no content string"
    text = content.strip()
    if len(text) < 300:
        return False, f"too short ({len(text)} chars)"
    low = text.lower()
    for marker in ["enable javascript", "access denied", "captcha"]:
        if marker in low:
            return False, f"boilerplate marker: {marker}"
    return True, "ok"


def _html_to_text(html: str, max_chars: int) -> str:
    no_script = re.sub(r"<script\b[^<]*(?:(?!</script>)<[^<]*)*</script>", " ", html, flags=re.I | re.S)
    no_style = re.sub(r"<style\b[^<]*(?:(?!</style>)<[^<]*)*</style>", " ", no_script, flags=re.I | re.S)
    body = re.sub(r"<[^>]+>", " ", no_style)
    text = unescape(body)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:max_chars]


def _fetch_url_content(url: str, max_chars: int) -> dict[str, str]:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
        )
    }
    try:
        resp = requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT_SECONDS, allow_redirects=True)
        ctype = (resp.headers.get("content-type") or "").lower()
        if resp.status_code >= 400:
            return {"url": url, "title": url, "content": f"Fetch error: HTTP {resp.status_code}"}
        if resp.status_code != 200 and not resp.text:
            return {"url": url, "title": url, "content": f"Fetch error: HTTP {resp.status_code} with empty body"}
        if "text/html" not in ctype and "application/xhtml+xml" not in ctype:
            return {"url": url, "title": url, "content": f"Fetch error: Unsupported content-type {ctype or 'unknown'}"}

        html = resp.text
        title_match = re.search(r"<title[^>]*>(.*?)</title>", html, flags=re.I | re.S)
        title = re.sub(r"\s+", " ", unescape(title_match.group(1))).strip() if title_match else url
        content = _html_to_text(html, max_chars=max_chars)
        return {"url": resp.url or url, "title": title or url, "content": content}
    except Exception as exc:
        return {"url": url, "title": url, "content": f"Fetch error: {exc}"}


@mcp.tool(name="web_search", description="Search web and fetch top pages")
def web_search(query: str) -> str:
    query = (query or "").strip()
    if not query:
        return json.dumps({"error": "No query provided."}, ensure_ascii=False)

    try:
        with DDGS() as ddgs:
            raw = list(ddgs.text(query, max_results=SEARCH_LIMIT))
    except Exception as exc:
        return json.dumps({"error": f"Search failed: {exc}"}, ensure_ascii=False)

    search_items: list[dict[str, str]] = []
    for row in raw:
        if not isinstance(row, dict):
            continue
        url = row.get("href") or row.get("url")
        title = row.get("title") or url or ""
        snippet = row.get("body") or row.get("snippet") or ""
        if isinstance(url, str) and url.startswith("http"):
            search_items.append({"title": str(title), "url": url, "snippet": str(snippet)})

    fetched_good: list[dict[str, str]] = []
    fetched_fallback: list[dict[str, str]] = []
    fetch_debug: list[dict[str, str]] = []

    for item in search_items[:FETCH_SCAN_LIMIT]:
        if len(fetched_good) >= FETCH_TOP_N:
            break
        page = _fetch_url_content(item["url"], FETCH_MAX_CHARS)
        content = page.get("content", "")
        if content.startswith("Fetch error:"):
            fetch_debug.append({"url": item["url"], "status": "skip", "reason": content})
            continue

        ok, reason = _fetched_page_quality(page)
        if ok:
            fetched_good.append(page)
            fetch_debug.append({"url": item["url"], "status": "keep", "reason": reason})
        else:
            fetched_fallback.append(page)
            fetch_debug.append({"url": item["url"], "status": "fallback", "reason": reason})

    fetched_pages = list(fetched_good)
    if len(fetched_pages) < FETCH_TOP_N:
        fetched_pages.extend(fetched_fallback[: FETCH_TOP_N - len(fetched_pages)])

    payload = {"search_results": search_items, "fetched_pages": fetched_pages, "fetch_debug": fetch_debug}

    if DEBUG:
        print(f"[wsMCPserver] query={query}")
        print(f"[wsMCPserver] payload_chars={len(json.dumps(payload, ensure_ascii=False))}")

    return json.dumps(payload, ensure_ascii=False, indent=2)


@mcp.tool(name="fetch_url", description="Fetch a URL and return extracted text content")
def fetch_url(url: str, maxChars: int = FETCH_MAX_CHARS) -> str:
    if not isinstance(url, str) or not url.startswith("http"):
        return json.dumps({"error": "Invalid URL."}, ensure_ascii=False)
    page = _fetch_url_content(url, max(500, min(int(maxChars), 50000)))
    return json.dumps(page, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    mcp.run(transport="streamable-http")
