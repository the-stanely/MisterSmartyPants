from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
import json
import os
import re
import time
from html import unescape
from typing import Any
from urllib.parse import urlparse

import requests
from ddgs import DDGS
from mcp.server.fastmcp import FastMCP

try:
    import trafilatura
except Exception:
    trafilatura = None

SERVER_HOST = os.getenv("WS_MCP_HOST", "127.0.0.1")
SERVER_PORT = int(os.getenv("WS_MCP_PORT", "8099"))
SEARCH_LIMIT = int(os.getenv("WS_SEARCH_LIMIT", "12"))
FETCH_TOP_N = int(os.getenv("WS_FETCH_TOP_N", "5"))
FETCH_MAX_CHARS = int(os.getenv("WS_FETCH_MAX_CHARS", "3000"))
FETCH_SCAN_LIMIT = int(os.getenv("WS_FETCH_SCAN_LIMIT", "12"))
FETCH_CANDIDATE_N = int(os.getenv("WS_FETCH_CANDIDATE_N", "5"))
FETCH_WORKERS = int(os.getenv("WS_FETCH_WORKERS", "4"))
SEARCH_MODES = tuple(
    mode.strip().lower()
    for mode in os.getenv("WS_SEARCH_MODES", "news,text").split(",")
    if mode.strip()
)
REQUEST_TIMEOUT_SECONDS = int(os.getenv("WS_REQUEST_TIMEOUT_SECONDS", "20"))
DEBUG = os.getenv("WS_DEBUG", "0") == "1"
AD_URL_MARKERS = (
    "adclick",
    "adserver",
    "affiliate",
    "doubleclick",
    "googlead",
    "marketing",
    "outbrain",
    "promo",
    "sponsored",
    "taboola",
    "utm_",
)
PREFERRED_SOURCE_DOMAINS = tuple(
    domain.strip().lower()
    for domain in os.getenv("WS_PREFERRED_SOURCE_DOMAINS", "yahoo.com").split(",")
    if domain.strip()
)
CURRENT_NEWS_MARKERS = ("latest", "today", "yesterday", "current", "recent", "news", "what happened")
TEXT_SIMILARITY_THRESHOLD = float(os.getenv("WS_TEXT_SIMILARITY_THRESHOLD", "0.72"))
TITLE_SIMILARITY_THRESHOLD = float(os.getenv("WS_TITLE_SIMILARITY_THRESHOLD", "0.82"))
STOPWORDS = {
    "about",
    "after",
    "also",
    "from",
    "have",
    "into",
    "more",
    "news",
    "over",
    "said",
    "that",
    "the",
    "their",
    "there",
    "this",
    "through",
    "with",
    "would",
}

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
    return _compact_text(text, max_chars)


def _compact_text(text: str, max_chars: int) -> str:
    text = re.sub(r"\s+", " ", text or "").strip()
    if len(text) <= max_chars:
        compacted = text
    else:
        compacted = text[:max_chars].rstrip()
        sentence_end = max(compacted.rfind("."), compacted.rfind("!"), compacted.rfind("?"))
        if sentence_end >= max_chars * 0.65:
            compacted = compacted[:sentence_end + 1]
        if not compacted.endswith("[TRUNCATED]"):
            compacted = f"{compacted} [TRUNCATED]"

    if compacted and not re.search(r'(\.|\!|\?|\[TRUNCATED\]|[\"”\']\s*)$', compacted):
        compacted = f"{compacted} [TRUNCATED]"
    if compacted and not compacted.endswith("[END EXCERPT]"):
        compacted = f"{compacted} [END EXCERPT]"
    return compacted


def _compact_text_with_metadata(text: str, max_chars: int) -> tuple[str, int, bool]:
    normalized = re.sub(r"\s+", " ", text or "").strip()
    compacted = _compact_text(normalized, max_chars)
    return compacted, len(normalized), "[TRUNCATED]" in compacted


def _title_from_html(html: str, fallback: str) -> str:
    title_match = re.search(r"<title[^>]*>(.*?)</title>", html, flags=re.I | re.S)
    if not title_match:
        return fallback
    return re.sub(r"\s+", " ", unescape(title_match.group(1))).strip() or fallback


def _is_probable_ad_url(url: str) -> bool:
    parsed = urlparse(url)
    haystack = f"{parsed.netloc} {parsed.path} {parsed.query}".lower()
    return any(marker in haystack for marker in AD_URL_MARKERS)


def _is_preferred_source_url(url: str) -> bool:
    host = urlparse(url).netloc.lower()
    return any(host == domain or host.endswith(f".{domain}") for domain in PREFERRED_SOURCE_DOMAINS)


def _asks_for_current_info(query: str) -> bool:
    low = query.lower()
    return any(marker in low for marker in CURRENT_NEWS_MARKERS)


def _has_stale_year_marker(query: str, item: dict[str, str]) -> bool:
    current_year = datetime.now().year
    requested_years = {int(year) for year in re.findall(r"\b(20\d{2})\b", query)}
    haystack = " ".join([item.get("title", ""), item.get("snippet", ""), item.get("url", "")])
    for year_text in re.findall(r"\b(20\d{2})\b", haystack):
        year = int(year_text)
        if year in requested_years:
            continue
        if year < current_year - 1:
            return True
    return False


def _parse_page_date(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    match = re.search(r"\b(20\d{2})-(\d{2})-(\d{2})\b", text)
    if match:
        try:
            return datetime.fromisoformat(match.group(0))
        except ValueError:
            return None
    match = re.search(r"\b(20\d{2})(\d{2})(\d{2})\b", text)
    if match:
        try:
            return datetime(int(match.group(1)), int(match.group(2)), int(match.group(3)))
        except ValueError:
            return None
    match = re.search(r"\b(Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\.?\s+(\d{1,2}),\s*(20\d{2})\b", text, flags=re.I)
    if match:
        month_names = {
            "jan": 1,
            "feb": 2,
            "mar": 3,
            "apr": 4,
            "may": 5,
            "jun": 6,
            "jul": 7,
            "aug": 8,
            "sep": 9,
            "sept": 9,
            "oct": 10,
            "nov": 11,
            "dec": 12,
        }
        month_key = match.group(1).lower().rstrip(".")
        month_key = "sept" if month_key.startswith("sept") else month_key[:3]
        try:
            return datetime(int(match.group(3)), month_names[month_key], int(match.group(2)))
        except ValueError:
            return None
    return None


def _first_date_from_text(*values: Any) -> str:
    for value in values:
        parsed = _parse_page_date(value)
        if parsed:
            return parsed.date().isoformat()
    return ""


def _token_set(text: str, max_tokens: int = 180) -> set[str]:
    tokens = []
    for token in re.findall(r"[a-z0-9]{3,}", (text or "").lower()):
        if token not in STOPWORDS:
            tokens.append(token)
        if len(tokens) >= max_tokens:
            break
    return set(tokens)


def _jaccard_similarity(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


def _duplicate_reason(page: dict[str, str], kept_pages: list[dict[str, str]]) -> str | None:
    title_tokens = _token_set(page.get("title", ""), max_tokens=40)
    content_tokens = _token_set(page.get("content", ""), max_tokens=220)
    for kept in kept_pages:
        kept_title_tokens = _token_set(kept.get("title", ""), max_tokens=40)
        kept_content_tokens = _token_set(kept.get("content", ""), max_tokens=220)
        title_score = _jaccard_similarity(title_tokens, kept_title_tokens)
        content_score = _jaccard_similarity(content_tokens, kept_content_tokens)
        if title_score >= TITLE_SIMILARITY_THRESHOLD:
            return f"near-duplicate title ({title_score:.2f}) of {kept.get('url', '')}"
        if content_score >= TEXT_SIMILARITY_THRESHOLD:
            return f"near-duplicate content ({content_score:.2f}) of {kept.get('url', '')}"
    return None


def _extract_article_content(html: str, url: str, max_chars: int) -> dict[str, str]:
    fallback_title = _title_from_html(html, url)
    if trafilatura is not None:
        try:
            extracted = trafilatura.extract(
                html,
                url=url,
                output_format="json",
                with_metadata=True,
                include_comments=False,
                include_tables=False,
                deduplicate=True,
                favor_precision=True,
            )
            if extracted:
                obj = json.loads(extracted)
                text, extracted_chars, was_truncated = _compact_text_with_metadata(
                    str(obj.get("text") or obj.get("raw_text") or ""),
                    max_chars,
                )
                if text:
                    return {
                        "url": url,
                        "title": str(obj.get("title") or fallback_title),
                        "author": str(obj.get("author") or ""),
                        "published": str(obj.get("date") or ""),
                        "content": text,
                        "extractor": "trafilatura",
                        "extracted_chars": str(extracted_chars),
                        "content_chars": str(len(text)),
                        "truncated": str(was_truncated).lower(),
                    }
        except Exception:
            pass

    fallback_content, fallback_chars, fallback_truncated = _compact_text_with_metadata(
        _html_to_text(html, max_chars=10_000_000),
        max_chars,
    )
    return {
        "url": url,
        "title": fallback_title,
        "author": "",
        "published": "",
        "content": fallback_content,
        "extractor": "html_to_text",
        "extracted_chars": str(fallback_chars),
        "content_chars": str(len(fallback_content)),
        "truncated": str(fallback_truncated).lower(),
    }


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

        return _extract_article_content(resp.text, resp.url or url, max_chars)
    except Exception as exc:
        return {"url": url, "title": url, "content": f"Fetch error: {exc}"}


@mcp.tool(name="web_search", description="Search web and fetch top pages")
def web_search(query: str) -> str:
    query = (query or "").strip()
    if not query:
        return json.dumps({"error": "No query provided."}, ensure_ascii=False)

    try:
        with DDGS() as ddgs:
            raw_with_modes: list[tuple[str, dict[str, Any]]] = []
            if "news" in SEARCH_MODES:
                raw_with_modes.extend(("news", row) for row in ddgs.news(query, max_results=SEARCH_LIMIT))
            if "text" in SEARCH_MODES:
                raw_with_modes.extend(("text", row) for row in ddgs.text(query, max_results=SEARCH_LIMIT))
    except Exception as exc:
        return json.dumps({"error": f"Search failed: {exc}"}, ensure_ascii=False)

    search_items: list[dict[str, str]] = []
    seen_urls: set[str] = set()
    for search_mode, row in raw_with_modes:
        if not isinstance(row, dict):
            continue
        url = row.get("href") or row.get("url")
        title = row.get("title") or url or ""
        snippet = row.get("body") or row.get("snippet") or ""
        if isinstance(url, str) and url.startswith("http"):
            normalized_url = url.split("#", 1)[0]
            if normalized_url in seen_urls:
                continue
            seen_urls.add(normalized_url)
            published = _first_date_from_text(
                row.get("date"),
                row.get("published"),
                row.get("published_date"),
                row.get("source_date"),
                title,
                snippet,
                url,
            )
            item = {
                "title": str(title),
                "url": url,
                "snippet": str(snippet),
                "published": published,
                "search_mode": search_mode,
            }
            if _is_probable_ad_url(url):
                continue
            if _asks_for_current_info(query) and _has_stale_year_marker(query, item):
                continue
            if _asks_for_current_info(query) and "youtube.com" in url.lower():
                continue
            search_items.append(item)

    search_items.sort(key=lambda item: 0 if _is_preferred_source_url(item["url"]) else 1)

    fetched_good: list[dict[str, str]] = []
    fetched_fallback: list[dict[str, str]] = []
    fetch_debug: list[dict[str, str]] = []
    candidate_limit = max(FETCH_TOP_N, FETCH_CANDIDATE_N)
    scan_items = search_items[:FETCH_SCAN_LIMIT]
    workers = max(1, FETCH_WORKERS)

    for batch_start in range(0, len(scan_items), workers):
        if len(fetched_good) >= candidate_limit:
            break
        batch = scan_items[batch_start:batch_start + workers]

        def fetch_item(item: dict[str, str]) -> tuple[dict[str, str], dict[str, str], float]:
            fetch_start = time.perf_counter()
            page = _fetch_url_content(item["url"], FETCH_MAX_CHARS)
            fetch_ms = (time.perf_counter() - fetch_start) * 1000
            return item, page, fetch_ms

        with ThreadPoolExecutor(max_workers=min(workers, len(batch))) as executor:
            batch_results = list(executor.map(fetch_item, batch))

        for item, page, fetch_ms in batch_results:
            content = page.get("content", "")
            if content.startswith("Fetch error:"):
                fetch_debug.append({"url": item["url"], "status": "skip", "reason": content, "ms": f"{fetch_ms:.0f}"})
                continue

            ok, reason = _fetched_page_quality(page)
            if page.get("extractor") != "trafilatura":
                fetch_debug.append(
                    {
                        "url": item["url"],
                        "status": "skip",
                        "reason": f"non-trafilatura extractor: {page.get('extractor', 'unknown')}",
                        "ms": f"{fetch_ms:.0f}",
                    }
                )
                continue
            if not page.get("published") and item.get("published"):
                page["published"] = item["published"]
                page["date_source"] = "search_result"
            elif page.get("published"):
                page["date_source"] = page.get("date_source", "extractor")
            else:
                inferred_date = _first_date_from_text(page.get("title", ""), page.get("url", ""), page.get("content", ""))
                if inferred_date:
                    page["published"] = inferred_date
                    page["date_source"] = "content_inferred"
            page["search_mode"] = item.get("search_mode", "")
            duplicate = _duplicate_reason(page, fetched_good + fetched_fallback)
            if duplicate:
                fetch_debug.append({"url": item["url"], "status": "skip", "reason": duplicate, "ms": f"{fetch_ms:.0f}"})
                continue
            if ok:
                fetched_good.append(page)
                fetch_debug.append({"url": item["url"], "status": "keep", "reason": reason, "ms": f"{fetch_ms:.0f}"})
            else:
                fetched_fallback.append(page)
                fetch_debug.append({"url": item["url"], "status": "fallback", "reason": reason, "ms": f"{fetch_ms:.0f}"})

    fetched_pages = list(fetched_good[:FETCH_TOP_N])

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
