from __future__ import annotations

import argparse
from contextvars import ContextVar
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
import hashlib
import json
import os
import re
import sys
import time
from typing import Any
from urllib.parse import urlparse

import requests
from ddgs import DDGS
from rich.console import Console
from rich.markdown import Markdown
import trafilatura

try:
    from dotenv import load_dotenv
    load_dotenv(override=True)
except Exception:
    pass


def read_positive_int_env(name: str, default: str) -> int:
    value = int(os.getenv(name, default))
    if value < 1:
        raise ValueError(f"{name} must be 1 or greater; got {value}")
    return value
OLLAMA_API = os.getenv("OLLAMA_API", "http://localhost:11434/api/chat")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "cow/gemma2_tools")
OLLAMA_DECIDER_MODEL = os.getenv("OLLAMA_DECIDER_MODEL", "llama3.2:1b")
OLLAMA_TIMEOUT_SECONDS = int(os.getenv("OLLAMA_TIMEOUT_SECONDS", "300"))
OLLAMA_NUM_CTX = int(os.getenv("OLLAMA_NUM_CTX", "32768"))
OLLAMA_TEMPERATURE = float(os.getenv("OLLAMA_TEMPERATURE", "0.2"))
OLLAMA_TOP_P = float(os.getenv("OLLAMA_TOP_P", "0.9"))
OLLAMA_NUM_PREDICT = int(os.getenv("OLLAMA_NUM_PREDICT", "512"))
OLLAMA_NUM_THREAD_RAW = os.getenv("OLLAMA_NUM_THREAD", "").strip()
OLLAMA_NUM_THREAD = int(OLLAMA_NUM_THREAD_RAW) if OLLAMA_NUM_THREAD_RAW else None
QUESTION = os.getenv("QUESTION", "Wall street biggest movers.")
SEARCH_LIMIT = 12
FETCH_TOP_N = read_positive_int_env("FETCH_TOP_N", "5")
FETCH_MAX_CHARS = int(os.getenv("FETCH_MAX_CHARS", "3000"))
FETCH_SCAN_LIMIT = read_positive_int_env("FETCH_SCAN_LIMIT", "20")
FETCH_CANDIDATE_N = read_positive_int_env("FETCH_CANDIDATE_N", "5")
FETCH_WORKERS = read_positive_int_env("FETCH_WORKERS", "4")
SEARCH_MODES = tuple(
    mode.strip().lower()
    for mode in os.getenv("SEARCH_MODES", "news,text").split(",")
    if mode.strip()
)
SUMMARIZE_EXCERPTS_WITH_DECIDER = os.getenv("SUMMARIZE_EXCERPTS_WITH_DECIDER", "1") == "1"
DECIDER_SUMMARY_MAX_TOKENS = int(os.getenv("DECIDER_SUMMARY_MAX_TOKENS", "180"))
DECIDER_SUMMARY_PROMPT = os.getenv(
    "DECIDER_SUMMARY_PROMPT",
    "Write a very brief summary of the following article:\n\n{excerpt_text}",
)
PYTHON_GENERATION_NO_THINK = os.getenv("PYTHON_GENERATION_NO_THINK", "1") == "1"
PYTHON_GENERATION_NO_THINK_INSTRUCTION = os.getenv("PYTHON_GENERATION_NO_THINK_INSTRUCTION", "/no_think")
DECIDER_RELEVANCE_ENABLED = os.getenv("DECIDER_RELEVANCE_ENABLED", "1") == "1"
DECIDER_RELEVANCE_EXCERPT_CHARS = int(os.getenv("DECIDER_RELEVANCE_EXCERPT_CHARS", "1200"))
RELEVANCY_MODEL = os.getenv("RELEVANCY_MODEL", "cross-encoder/ms-marco-MiniLM-L-6-v2")
RELEVANCY_THRESHOLD = float(os.getenv("RELEVANCY_THRESHOLD", "0.0"))
REQUEST_TIMEOUT_SECONDS = int(os.getenv("REQUEST_TIMEOUT_SECONDS", "20"))
DDGS_TIMEOUT_SECONDS = int(os.getenv("DDGS_TIMEOUT_SECONDS", "20"))
DEBUG = False

PROMPT_DEBUG = os.getenv("PROMPT_DEBUG", "0") == "1"
LLM_ENABLED = os.getenv("LLM_ENABLED", "1") == "1"
SEARCH_ENABLED = os.getenv("SEARCH_ENABLED", "1") == "1"
PROMPT_DEBUG_CONTEXT: ContextVar[bool] = ContextVar("PROMPT_DEBUG_CONTEXT", default=PROMPT_DEBUG)
LLM_ENABLED_CONTEXT: ContextVar[bool] = ContextVar("LLM_ENABLED_CONTEXT", default=LLM_ENABLED)
SEARCH_DECIDER = os.getenv("SEARCH_DECIDER", "python").strip().lower()
DECIDER_MODEL = os.getenv(
    "DECIDER_MODEL",
    os.getenv("QWEN_DECIDER_MODEL", "Qwen/Qwen2.5-0.5B-Instruct"),
)
SUMMARY_MODEL = os.getenv("SUMMARY_MODEL", DECIDER_MODEL)
DECIDER_LOCAL_ONLY = os.getenv("DECIDER_LOCAL_ONLY", os.getenv("QWEN_DECIDER_LOCAL_ONLY", "0")) == "1"
DEFAULT_ANSWER_FROM_RESULTS_PROMPT = (
    "Today is {date-time}. Use web search data as the source of truth for current facts. "
    "Use general knowledge only for background, historical context, and explanation. "
    "Do not override or contradict current facts from web search data with memory. "
    "When web sources conflict, prefer the most recent dated credible web source. "
    "Do not dismiss newer web facts solely because older sources or memory say otherwise. "
    "For status-changing events such as deaths, injuries, signings, or departures, newer dated reports can supersede older active-status articles. "
    "The source list contains Trafilatura-extracted article text; use each source's title, URL, and published date when present. "
    "Use prior chat context if relevant. "
    "If web data is thin or conflicting, say that clearly and mention source links. "
    "Be concise."
)
ANSWER_FROM_RESULTS_PROMPT = os.getenv("ANSWER_FROM_RESULTS_PROMPT", DEFAULT_ANSWER_FROM_RESULTS_PROMPT)
DEFAULT_ANSWER_FROM_RESULTS_EXTRA_SYSTEM_PROMPT = (
    "You have been given current web search data in this conversation. "
    "Do not say you lack web access or cannot access current information when web search data is provided. "
    "If the provided web search data is empty, invalid, or insufficient, say that specifically."
)
ANSWER_FROM_RESULTS_EXTRA_SYSTEM_PROMPT = os.getenv(
    "ANSWER_FROM_RESULTS_EXTRA_SYSTEM_PROMPT",
    DEFAULT_ANSWER_FROM_RESULTS_EXTRA_SYSTEM_PROMPT,
)
DEFAULT_QWEN_DECIDER_SYSTEM_PROMPT = (
    "Today is {date-time}. Decide if web search is needed for the latest user request. "
    "Return exactly one word: SEARCH or ANSWER. Do not explain. "
    "Never return RESEARCH. SEARCH means use the internet. ANSWER means no internet. "
    "Choose SEARCH for current, recent, local, price, score, weather, news, market, "
    "product availability, reviews, recommendations, or uncertain factual claims. "
    "Choose ANSWER only when stable general knowledge is enough. "
    'Examples: "Explain why the Roman Empire fell." -> ANSWER. '
    '"What is Nvidia stock doing today?" -> SEARCH. '
    '"How does photosynthesis work?" -> ANSWER. '
    '"Are reviews good for the newest Framework laptop?" -> SEARCH.'
)
QWEN_DECIDER_SYSTEM_PROMPT = os.getenv("QWEN_DECIDER_SYSTEM_PROMPT", DEFAULT_QWEN_DECIDER_SYSTEM_PROMPT)
DEFAULT_QUERY_BUILDER_SYSTEM_PROMPT = (
    "Convert the user request into a concise web search query. "
    "Use prior chat context if helpful. "
    "Return only the query text, no quotes, no JSON, no explanation."
)
QUERY_BUILDER_SYSTEM_PROMPT = os.getenv("QUERY_BUILDER_SYSTEM_PROMPT", DEFAULT_QUERY_BUILDER_SYSTEM_PROMPT)
DEFAULT_OLLAMA_DECIDER_SYSTEM_PROMPT = (
    "Decide if web search is required to answer the user's latest request. "
    "Use prior chat context if relevant. "
    "For anything time-sensitive, recent, or uncertain, choose SEARCH. "
    "Return exactly one line in this format: DECISION|REASON. "
    "DECISION must be either SEARCH or ANSWER. "
    "If unsure, choose SEARCH."
)
OLLAMA_DECIDER_SYSTEM_PROMPT = os.getenv("OLLAMA_DECIDER_SYSTEM_PROMPT", DEFAULT_OLLAMA_DECIDER_SYSTEM_PROMPT)
DEFAULT_MEMORY_ANSWER_SYSTEM_PROMPT = (
    "Answer directly from general knowledge and prior chat context only. "
    "Do not claim web verification. Be concise."
)
MEMORY_ANSWER_SYSTEM_PROMPT = os.getenv("MEMORY_ANSWER_SYSTEM_PROMPT", DEFAULT_MEMORY_ANSWER_SYSTEM_PROMPT)
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
    for domain in os.getenv(
        "PREFERRED_SOURCE_DOMAINS",
        "yahoo.com,wikipedia.org,usatoday.com,nytimes.com",
    ).split(",")
    if domain.strip()
)
YAHOO_PREFERRED_LIMIT = int(os.getenv("YAHOO_PREFERRED_LIMIT", "2"))
CURRENT_NEWS_MARKERS = ("latest", "today", "yesterday", "current", "recent", "news", "what happened")
TEXT_SIMILARITY_THRESHOLD = float(os.getenv("TEXT_SIMILARITY_THRESHOLD", "0.72"))
TITLE_SIMILARITY_THRESHOLD = float(os.getenv("TITLE_SIMILARITY_THRESHOLD", "0.82"))
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
FORCE_SEARCH_MARKERS = tuple(
    marker.strip().lower()
    for marker in os.getenv(
        "FORCE_SEARCH_MARKERS",
        "latest,today,yesterday,current,news,score,odds,price,review,reviews,recommend,"
        "recommendation,best,newest,stock,weather,who won,what happened,search,look up,find",
    ).split(",")
    if marker.strip()
)
_python_models: dict[str, dict[str, Any]] = {}
_relevancy_models: dict[str, Any] = {}
_last_qwen_scores: tuple[float, float] | None = None
console = Console()


class LlmSkipped(RuntimeError):
    pass


def prompt_debug_enabled() -> bool:
    return PROMPT_DEBUG_CONTEXT.get()


def llm_enabled() -> bool:
    return LLM_ENABLED_CONTEXT.get()


def print_assistant_answer(answer: str, rich_output: bool = True) -> None:
    print("[Assistant]")
    if rich_output:
        Console(file=sys.stdout).print(Markdown(answer))
    else:
        print(answer)
    print()


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")


def fetched_page_quality(page_obj: dict[str, Any]) -> tuple[bool, str]:
    content = page_obj.get("content")
    if not isinstance(content, str):
        return False, "no content string"
    text = content.strip()
    if len(text) < 300:
        return False, f"too short ({len(text)} chars)"
    low = text.lower()
    bad_markers = [
        "enable javascript",
        "access denied",
        "captcha",
    ]
    for marker in bad_markers:
        if marker in low:
            return False, f"boilerplate marker: {marker}"
    return True, "ok"


def compact_text(text: str, max_chars: int) -> str:
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

    if compacted and not re.search(r'(\.|\!|\?|\[TRUNCATED\]|["\']\s*)$', compacted):
        compacted = f"{compacted} [TRUNCATED]"
    if compacted and not compacted.endswith("[END EXCERPT]"):
        compacted = f"{compacted} [END EXCERPT]"
    return compacted


def compact_text_with_metadata(text: str, max_chars: int) -> tuple[str, int, bool]:
    normalized = re.sub(r"\s+", " ", text or "").strip()
    compacted = compact_text(normalized, max_chars)
    return compacted, len(normalized), "[TRUNCATED]" in compacted


def title_from_html(html: str, fallback: str) -> str:
    title_match = re.search(r"<title[^>]*>(.*?)</title>", html, flags=re.I | re.S)
    if not title_match:
        return fallback
    return re.sub(r"\s+", " ", title_match.group(1)).strip() or fallback


def is_probable_ad_url(url: str) -> bool:
    parsed = urlparse(url)
    haystack = f"{parsed.netloc} {parsed.path} {parsed.query}".lower()
    return any(marker in haystack for marker in AD_URL_MARKERS)


def is_root_homepage_url(url: str) -> bool:
    parsed = urlparse(url)
    path = (parsed.path or "/").strip()
    if parsed.query or parsed.fragment:
        return False
    return path in {"", "/"}


def is_preferred_source_url(url: str) -> bool:
    host = urlparse(url).netloc.lower()
    return any(host == domain or host.endswith(f".{domain}") for domain in PREFERRED_SOURCE_DOMAINS)


def is_domain_url(url: str, domain: str) -> bool:
    host = urlparse(url).netloc.lower()
    return host == domain or host.endswith(f".{domain}")


def prioritize_search_items(search_items: list[dict[str, str]]) -> list[dict[str, str]]:
    preferred_non_yahoo: list[dict[str, str]] = []
    preferred_yahoo: list[dict[str, str]] = []
    regular: list[dict[str, str]] = []
    extra_yahoo: list[dict[str, str]] = []

    for item in search_items:
        url = item["url"]
        if is_domain_url(url, "yahoo.com"):
            if len(preferred_yahoo) < YAHOO_PREFERRED_LIMIT:
                preferred_yahoo.append(item)
            else:
                extra_yahoo.append(item)
        elif is_preferred_source_url(url):
            preferred_non_yahoo.append(item)
        else:
            regular.append(item)

    return preferred_non_yahoo + preferred_yahoo + regular + extra_yahoo


def asks_for_current_info(query: str) -> bool:
    low = query.lower()
    return any(marker in low for marker in CURRENT_NEWS_MARKERS)


def has_stale_year_marker(query: str, item: dict[str, str]) -> bool:
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


def parse_page_date(value: Any) -> datetime | None:
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
        month = month_names[match.group(1).lower().rstrip(".")[:4] if match.group(1).lower().startswith("sept") else match.group(1).lower().rstrip(".")[:3]]
        try:
            return datetime(int(match.group(3)), month, int(match.group(2)))
        except ValueError:
            return None
    return None


def first_date_from_text(*values: Any) -> str:
    for value in values:
        parsed = parse_page_date(value)
        if parsed:
            return parsed.date().isoformat()
    return ""


def token_set(text: str, max_tokens: int = 180) -> set[str]:
    tokens = []
    for token in re.findall(r"[a-z0-9]{3,}", (text or "").lower()):
        if token not in STOPWORDS:
            tokens.append(token)
        if len(tokens) >= max_tokens:
            break
    return set(tokens)


def jaccard_similarity(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


def duplicate_reason(page: dict[str, str], kept_pages: list[dict[str, str]]) -> str | None:
    title_tokens = token_set(page.get("title", ""), max_tokens=40)
    content_tokens = token_set(page.get("content", ""), max_tokens=220)
    for kept in kept_pages:
        kept_title_tokens = token_set(kept.get("title", ""), max_tokens=40)
        kept_content_tokens = token_set(kept.get("content", ""), max_tokens=220)
        title_score = jaccard_similarity(title_tokens, kept_title_tokens)
        content_score = jaccard_similarity(content_tokens, kept_content_tokens)
        if title_score >= TITLE_SIMILARITY_THRESHOLD:
            return f"near-duplicate title ({title_score:.2f}) of {kept.get('url', '')}"
        if content_score >= TEXT_SIMILARITY_THRESHOLD:
            return f"near-duplicate content ({content_score:.2f}) of {kept.get('url', '')}"
    return None


def extract_article_content(html: str, url: str, max_chars: int) -> dict[str, str]:
    fallback_title = title_from_html(html, url)
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
    except Exception as exc:
        return {"url": url, "title": fallback_title, "content": f"Fetch error: trafilatura extraction failed: {exc}"}

    if not extracted:
        return {"url": url, "title": fallback_title, "content": "Fetch error: trafilatura returned no content"}

    try:
        obj = json.loads(extracted)
    except json.JSONDecodeError as exc:
        return {"url": url, "title": fallback_title, "content": f"Fetch error: trafilatura returned invalid JSON: {exc}"}

    text, extracted_chars, was_truncated = compact_text_with_metadata(
        str(obj.get("text") or obj.get("raw_text") or ""),
        max_chars,
    )
    if not text:
        return {"url": url, "title": str(obj.get("title") or fallback_title), "content": "Fetch error: trafilatura returned empty text"}

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


def fetch_url_content(url: str, max_chars: int) -> dict[str, str]:
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
            return {
                "url": url,
                "title": url,
                "content": f"Fetch error: HTTP {resp.status_code} with empty body",
            }
        if "text/html" not in ctype and "application/xhtml+xml" not in ctype:
            return {"url": url, "title": url, "content": f"Fetch error: Unsupported content-type {ctype or 'unknown'}"}

        return extract_article_content(resp.text, resp.url or url, max_chars)
    except Exception as exc:
        return {"url": url, "title": url, "content": f"Fetch error: {exc}"}


def run_search(query: str, search_limit: int, fetch_top_n: int, fetch_scan_limit: int, fetch_max_chars: int) -> str:
    raw_with_modes: list[tuple[str, dict[str, Any]]] = []
    mode_errors: list[str] = []
    with DDGS(timeout=DDGS_TIMEOUT_SECONDS) as ddgs:
        if "news" in SEARCH_MODES:
            try:
                raw_with_modes.extend(("news", row) for row in ddgs.news(query, max_results=search_limit))
            except Exception as exc:
                mode_errors.append(f"news: {exc}")
        if "text" in SEARCH_MODES:
            try:
                raw_with_modes.extend(("text", row) for row in ddgs.text(query, max_results=search_limit))
            except Exception as exc:
                mode_errors.append(f"text: {exc}")

    if not raw_with_modes:
        detail = "; ".join(mode_errors) if mode_errors else "No results found."
        raise RuntimeError(f"Search failed: {detail}")

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
            published = first_date_from_text(
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
            if is_probable_ad_url(url):
                continue
            if is_root_homepage_url(url):
                continue
            if asks_for_current_info(query) and has_stale_year_marker(query, item):
                continue
            if asks_for_current_info(query) and "youtube.com" in url.lower():
                continue
            search_items.append(item)

    search_items = prioritize_search_items(search_items)

    fetched_good: list[dict[str, str]] = []
    fetched_fallback: list[dict[str, str]] = []
    fetch_debug: list[dict[str, str]] = []
    candidate_limit = max(fetch_top_n, FETCH_CANDIDATE_N)
    scan_items = search_items[:fetch_scan_limit]
    workers = max(1, FETCH_WORKERS)

    for batch_start in range(0, len(scan_items), workers):
        if len(fetched_good) >= candidate_limit:
            break
        batch = scan_items[batch_start:batch_start + workers]

        def fetch_item(item: dict[str, str]) -> tuple[dict[str, str], dict[str, str], float]:
            fetch_start = time.perf_counter()
            page = fetch_url_content(item["url"], fetch_max_chars)
            fetch_ms = (time.perf_counter() - fetch_start) * 1000
            return item, page, fetch_ms

        with ThreadPoolExecutor(max_workers=min(workers, len(batch))) as executor:
            batch_results = list(executor.map(fetch_item, batch))

        for item, page, fetch_ms in batch_results:
            content = page.get("content", "")
            if content.startswith("Fetch error:"):
                fetch_debug.append(
                    {
                        "url": item["url"],
                        "status": "skip",
                        "reason": content,
                        "ms": f"{fetch_ms:.0f}",
                    }
                )
                continue
            ok, reason = fetched_page_quality(page)
            if not page.get("published") and item.get("published"):
                page["published"] = item["published"]
                page["date_source"] = "search_result"
            elif page.get("published"):
                page["date_source"] = page.get("date_source", "extractor")
            else:
                inferred_date = first_date_from_text(page.get("title", ""), page.get("url", ""), page.get("content", ""))
                if inferred_date:
                    page["published"] = inferred_date
                    page["date_source"] = "content_inferred"
            page["search_mode"] = item.get("search_mode", "")
            if DECIDER_RELEVANCE_ENABLED:
                relevance_start = time.perf_counter()
                is_relevant, relevance_score, relevance_excerpt = decide_article_relevance(query, page)
                relevance_ms = (time.perf_counter() - relevance_start) * 1000
                page["relevance_ms"] = f"{relevance_ms:.0f}"
                page["relevance_score"] = f"{relevance_score:.3f}"
                page["relevance_threshold"] = f"{RELEVANCY_THRESHOLD:.3f}"
                page["relevance_model"] = RELEVANCY_MODEL
                if prompt_debug_enabled():
                    print(f"[Relevance input begin: {len(relevance_excerpt)} chars]")
                    print(f"Query: {query}")
                    print()
                    print(relevance_excerpt)
                    print("[Relevance input end]")
                print(
                    f"[Relevance: {relevance_ms:.0f} ms, "
                    f"{RELEVANCY_MODEL}, score = {relevance_score:.3f}, "
                    f"threshold = {RELEVANCY_THRESHOLD:.3f}, keep = {str(is_relevant).lower()}]"
                )
                if not is_relevant:
                    fetch_debug.append(
                        {
                            "url": item["url"],
                            "status": "skip",
                            "reason": (
                                f"irrelevant article score={relevance_score:.3f} "
                                f"threshold={RELEVANCY_THRESHOLD:.3f}"
                            ),
                            "ms": f"{fetch_ms:.0f}",
                            "relevance_ms": f"{relevance_ms:.0f}",
                        }
                    )
                    continue
            duplicate = duplicate_reason(page, fetched_good + fetched_fallback)
            if duplicate:
                fetch_debug.append({"url": item["url"], "status": "skip", "reason": duplicate, "ms": f"{fetch_ms:.0f}"})
                continue
            if ok:
                fetched_good.append(page)
                fetch_debug.append({"url": item["url"], "status": "keep", "reason": reason, "ms": f"{fetch_ms:.0f}"})
            else:
                fetched_fallback.append(page)
                fetch_debug.append({"url": item["url"], "status": "fallback", "reason": reason, "ms": f"{fetch_ms:.0f}"})

    fetched_pages = list(fetched_good[:fetch_top_n])

    payload = {"search_results": search_items, "fetched_pages": fetched_pages, "fetch_debug": fetch_debug}
    return json.dumps(payload, ensure_ascii=False, indent=2)


def validate_llm_messages(messages: list[dict[str, str]]) -> str:
    serialized = json.dumps(messages, ensure_ascii=False, indent=2)
    json.loads(serialized)

    for index, message in enumerate(messages):
        role = message.get("role")
        content = message.get("content")
        if not isinstance(role, str) or not isinstance(content, str):
            raise ValueError(f"LLM message {index} must have string role/content.")

        has_search_start = "BEGIN WEB NEWS SEARCH RESULTS" in content
        has_search_end = "END WEB NEWS SEARCH RESULTS" in content
        if has_search_start != has_search_end:
            raise ValueError(f"LLM message {index} has incomplete web search data markers.")
        if has_search_start:
            if not content.rstrip().endswith("END WEB NEWS SEARCH RESULTS"):
                raise ValueError(f"LLM message {index} does not end with web search data end marker.")
            match = re.search(
                r"BEGIN WEB NEWS SEARCH RESULTS\s*(.*?)\s*END WEB NEWS SEARCH RESULTS\s*$",
                content,
                flags=re.S,
            )
            if not match:
                raise ValueError(f"LLM message {index} web search data block was malformed.")
            block = match.group(1).strip()
            if "BEGIN SOURCE " in block and "END SOURCE " not in block:
                raise ValueError(f"LLM message {index} has incomplete source markers.")
            begins = re.findall(r"^BEGIN SOURCE (\d+)$", block, flags=re.M)
            ends = re.findall(r"^END SOURCE (\d+)$", block, flags=re.M)
            if begins != ends:
                raise ValueError(f"LLM message {index} source marker mismatch: begin={begins}, end={ends}.")
            for source_id in begins:
                source_match = re.search(
                    rf"^BEGIN SOURCE {source_id}\n(.*?)\nEND SOURCE {source_id}$",
                    block,
                    flags=re.M | re.S,
                )
                if not source_match:
                    raise ValueError(f"LLM message {index} source {source_id} block was malformed.")
                if "[END EXCERPT]" not in source_match.group(1):
                    raise ValueError(f"LLM message {index} source {source_id} missing [END EXCERPT].")

    return serialized


def print_prompt_debug(messages: list[dict[str, str]], serialized: str, model: str) -> None:
    digest = hashlib.sha256(serialized.encode("utf-8")).hexdigest()[:12]
    print(f"[Prompt begin: {len(serialized)} chars, model={model}, sha256={digest}]")
    for index, message in enumerate(messages, start=1):
        role = message.get("role", "")
        content = message.get("content", "")
        print(f"[Prompt message {index}: role={role}, chars={len(content)}]")
        if "[END EXCERPT]" in content:
            cursor = 0
            part = 1
            marker_pattern = re.compile(r"\[END EXCERPT\](?:\nEND SOURCE \d+)?")
            for match in marker_pattern.finditer(content):
                end = match.end()
                print(f"[Prompt message {index} part {part}: chars {cursor}-{end}]")
                print(content[cursor:end])
                cursor = end
                part += 1
            if cursor < len(content):
                print(f"[Prompt message {index} part {part}: chars {cursor}-{len(content)}]")
                print(content[cursor:])
        else:
            print(content)
    print("[Prompt end]")
    print()


def chat_once(messages: list[dict[str, str]], model: str = OLLAMA_MODEL) -> str:
    serialized_messages = validate_llm_messages(messages)
    if prompt_debug_enabled():
        print_prompt_debug(messages, serialized_messages, model)
    if not llm_enabled():
        raise LlmSkipped("LLM disabled.")
    options = {
        "num_ctx": OLLAMA_NUM_CTX,
        "temperature": OLLAMA_TEMPERATURE,
        "top_p": OLLAMA_TOP_P,
        "num_predict": OLLAMA_NUM_PREDICT,
    }
    if OLLAMA_NUM_THREAD is not None:
        options["num_thread"] = OLLAMA_NUM_THREAD

    payload = {
        "model": model,
        "messages": messages,
        "stream": False,
        "options": options,
    }
    response = requests.post(OLLAMA_API, json=payload, timeout=OLLAMA_TIMEOUT_SECONDS)
    response.raise_for_status()
    obj = response.json()
    return ((obj.get("message") or {}).get("content") or "").strip()


def expand_prompt_placeholders(prompt: str) -> str:
    now = datetime.now().astimezone()
    return prompt.replace("{date-time}", now.strftime("%Y-%m-%d %H:%M:%S %Z%z"))


def apply_python_generation_controls(prompt: str) -> str:
    if not PYTHON_GENERATION_NO_THINK:
        return prompt
    instruction = PYTHON_GENERATION_NO_THINK_INSTRUCTION.strip()
    if not instruction:
        return prompt
    return f"{instruction}\n{prompt}"


def prompt_forces_search(user_prompt: str) -> bool:
    return forced_search_marker(user_prompt) is not None


def forced_search_marker(user_prompt: str) -> str | None:
    prompt_low = user_prompt.lower()
    for marker in FORCE_SEARCH_MARKERS:
        if marker and re.search(rf"(?<![a-z0-9]){re.escape(marker)}(?![a-z0-9])", prompt_low):
            return marker
    return None


def get_python_model(model_name: str) -> dict[str, Any]:
    if model_name in _python_models:
        return _python_models[model_name]
    import torch
    from huggingface_hub import snapshot_download
    from transformers import AutoModelForCausalLM, AutoTokenizer

    device = "cuda" if torch.cuda.is_available() else "cpu"
    if os.path.isdir(model_name):
        model_path = model_name
    else:
        try:
            model_path = snapshot_download(model_name, local_files_only=True)
        except Exception:
            if DECIDER_LOCAL_ONLY:
                raise
            model_path = snapshot_download(model_name, local_files_only=False)

    tokenizer = AutoTokenizer.from_pretrained(
        model_path,
        local_files_only=True,
    )
    model = AutoModelForCausalLM.from_pretrained(
        model_path,
        dtype=torch.float16 if device == "cuda" else torch.float32,
        local_files_only=True,
    ).to(device)
    model.eval()
    loaded = {"tokenizer": tokenizer, "model": model, "torch": torch, "device": device}
    _python_models[model_name] = loaded
    return loaded


def get_qwen_decider() -> dict[str, Any]:
    return get_python_model(DECIDER_MODEL)


def get_relevancy_model() -> Any:
    if RELEVANCY_MODEL in _relevancy_models:
        return _relevancy_models[RELEVANCY_MODEL]
    from huggingface_hub import snapshot_download
    from sentence_transformers import CrossEncoder

    if os.path.isdir(RELEVANCY_MODEL):
        model_path = RELEVANCY_MODEL
    else:
        try:
            model_path = snapshot_download(RELEVANCY_MODEL, local_files_only=True)
        except Exception:
            if DECIDER_LOCAL_ONLY:
                raise
            model_path = snapshot_download(RELEVANCY_MODEL, local_files_only=False)

    model = CrossEncoder(model_path)
    _relevancy_models[RELEVANCY_MODEL] = model
    return model


def excerpt_body(content: str) -> str:
    text = (content or "").strip()
    text = text.replace("[END EXCERPT]", "").replace("[TRUNCATED]", "").strip()
    return text


def summarize_with_decider(excerpt_text: str) -> str:
    summary_model = get_python_model(SUMMARY_MODEL)
    tokenizer = summary_model["tokenizer"]
    model = summary_model["model"]
    torch = summary_model["torch"]
    device = summary_model["device"]
    messages = [
        {
            "role": "user",
            "content": apply_python_generation_controls(
                expand_prompt_placeholders(DECIDER_SUMMARY_PROMPT).replace("{excerpt_text}", excerpt_text)
            ),
        }
    ]
    text = tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
    inputs = tokenizer(text, return_tensors="pt").to(device)
    with torch.inference_mode():
        output = model.generate(
            **inputs,
            max_new_tokens=DECIDER_SUMMARY_MAX_TOKENS,
            do_sample=False,
            pad_token_id=tokenizer.eos_token_id,
        )
    generated = tokenizer.decode(output[0][inputs["input_ids"].shape[-1]:], skip_special_tokens=True)
    summary = re.sub(r"\s+", " ", generated or "").strip()
    if not summary:
        raise ValueError("Decider summary was empty.")
    if not summary.endswith((".", "!", "?")):
        summary = f"{summary}."
    return f"{summary} [END EXCERPT]"


def summarize_search_result_excerpts(tool_json: str) -> str:
    parsed = parse_search_data_for_prompt(tool_json)
    fetched_pages = parsed.get("fetched_pages", [])
    if not isinstance(fetched_pages, list):
        raise ValueError("Search data fetched_pages was not a list before summarization.")

    for page in fetched_pages:
        if not isinstance(page, dict):
            continue
        if page.get("extractor") != "trafilatura":
            continue
        excerpt = excerpt_body(str(page.get("content") or ""))
        if not excerpt:
            raise ValueError("Cannot summarize empty extracted article excerpt.")
        original_content_chars = len(str(page.get("content") or ""))
        page["content"] = summarize_with_decider(excerpt)
        page["summary_model"] = SUMMARY_MODEL
        page["summary_original_content_chars"] = str(original_content_chars)
        page["summary_content_chars"] = str(len(page["content"]))

    return json.dumps(parsed, ensure_ascii=False, indent=2)

def relevance_classifier_text(page: dict[str, str]) -> str:
    metadata = [
        ("Title", str(page.get("title") or "").strip()),
        ("URL", str(page.get("url") or "").strip()),
        ("Published", str(page.get("published") or "").strip()),
        ("Source", str(page.get("source") or page.get("domain") or "").strip()),
    ]
    lines = [f"{label}: {value}" for label, value in metadata if value]
    excerpt = excerpt_body(str(page.get("content") or ""))[:DECIDER_RELEVANCE_EXCERPT_CHARS]
    if not excerpt:
        raise ValueError("Article relevance classifier received empty excerpt.")
    if lines:
        lines.extend(["", "Excerpt:", excerpt])
        return "\n".join(lines)
    return excerpt


def decide_article_relevance(user_question: str, page: dict[str, str]) -> tuple[bool, float, str]:
    model = get_relevancy_model()
    relevance_text = relevance_classifier_text(page)
    score = float(model.predict([(user_question, relevance_text)])[0])
    return score >= RELEVANCY_THRESHOLD, score, relevance_text

def format_decider_user_content(user_prompt: str) -> str:
    return (
        "User request:\n"
        f"{user_prompt}\n\n"
        "Question: Does this request require current internet search?\n"
        "Allowed labels: SEARCH, ANSWER\n"
        "Correct label:"
    )


def decide_with_qwen(user_prompt: str, history: list[dict[str, str]]) -> tuple[bool, str, str | None]:
    global _last_qwen_scores

    decider = get_qwen_decider()
    tokenizer = decider["tokenizer"]
    model = decider["model"]
    torch = decider["torch"]
    device = decider["device"]
    messages = [
        {
            "role": "system",
            "content": expand_prompt_placeholders(QWEN_DECIDER_SYSTEM_PROMPT),
        }
    ]
    messages.append({"role": "user", "content": format_decider_user_content(user_prompt)})

    if prompt_debug_enabled():
        serialized = json.dumps(messages, ensure_ascii=False, indent=2)
        print(f"[Decider prompt begin: {len(serialized)} chars, model={DECIDER_MODEL}]")
        for index, message in enumerate(messages, start=1):
            print(f"[Decider prompt message {index}: role={message['role']}, chars={len(message['content'])}]")
            print(message["content"])
        print("[Decider prompt end]")

    text = tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
    inputs = tokenizer(text, return_tensors="pt").to(device)
    search_ids = tokenizer("SEARCH", add_special_tokens=False)["input_ids"]
    answer_ids = tokenizer("ANSWER", add_special_tokens=False)["input_ids"]
    if len(search_ids) < 1 or len(answer_ids) < 1:
        raise ValueError(f"Expected label tokens, got SEARCH={search_ids}, ANSWER={answer_ids}")
    with torch.inference_mode():
        logits = model(**inputs).logits[0, -1]
    log_probs = torch.log_softmax(logits, dim=-1)
    search_score = float(log_probs[search_ids[0]].item())
    answer_score = float(log_probs[answer_ids[0]].item())

    if abs(search_score - answer_score) < 0.75:
        prompt_ids = inputs["input_ids"][0]

        def score_label(label: str) -> float:
            label_ids = tokenizer(label, add_special_tokens=False, return_tensors="pt")["input_ids"][0].to(device)
            full_ids = torch.cat([prompt_ids, label_ids]).unsqueeze(0)
            with torch.inference_mode():
                label_logits = model(full_ids).logits[0]
            total = 0.0
            start = prompt_ids.shape[-1]
            for offset, token_id in enumerate(label_ids):
                label_log_probs = torch.log_softmax(label_logits[start + offset - 1], dim=-1)
                total += float(label_log_probs[token_id].item())
            return total / float(label_ids.numel())

        search_score = score_label("SEARCH")
        answer_score = score_label("ANSWER")

    if search_score == answer_score:
        raise ValueError("Qwen decider scored SEARCH and ANSWER equally.")
    _last_qwen_scores = (search_score, answer_score)
    decision = "SEARCH" if search_score > answer_score else "ANSWER"
    reason = f"qwen decider score SEARCH={search_score:.3f} ANSWER={answer_score:.3f}"
    if decision == "SEARCH":
        return True, reason, user_prompt
    return False, reason, None


def format_decider_elapsed(elapsed_ms: float) -> str:
    if _last_qwen_scores is None:
        return f"[Decider: {elapsed_ms:.0f} ms]"
    search_score, answer_score = _last_qwen_scores
    return f"[Decider: {elapsed_ms:.0f} ms, Search = {search_score:.3f}, Answer = {answer_score:.3f}]"


def decide_search_action(user_prompt: str, history: list[dict[str, str]]) -> tuple[bool, str, str | None]:
    global _last_qwen_scores

    _last_qwen_scores = None
    if SEARCH_DECIDER == "always":
        return True, "SEARCH_DECIDER=always", user_prompt
    marker = forced_search_marker(user_prompt)
    if marker:
        return True, f"forced search marker: {marker}", user_prompt
    if SEARCH_DECIDER == "rules":
        return False, "SEARCH_DECIDER=rules and no search rule matched", None
    if SEARCH_DECIDER == "qwen":
        raise ValueError("SEARCH_DECIDER=qwen is obsolete. Use SEARCH_DECIDER=python.")
    if SEARCH_DECIDER == "python":
        return decide_with_qwen(user_prompt, history)
    if SEARCH_DECIDER != "ollama":
        raise ValueError(f"Unsupported SEARCH_DECIDER={SEARCH_DECIDER!r}")

    should_search, reason = decide_search_needed(user_prompt, history)
    return should_search, reason, None


def derive_search_query(user_prompt: str, history: list[dict[str, str]]) -> str:
    messages = [
        {
            "role": "system",
            "content": expand_prompt_placeholders(QUERY_BUILDER_SYSTEM_PROMPT),
        }
    ]
    messages.extend(history)
    messages.append({"role": "user", "content": user_prompt})
    content = chat_once(messages)
    query = content.strip().strip('"').strip("'")
    if not query:
        raise RuntimeError("LLM query builder returned empty text.")
    return query


def decide_search_needed(user_prompt: str, history: list[dict[str, str]]) -> tuple[bool, str]:
    if prompt_forces_search(user_prompt):
        return True, "time-sensitive or explicit lookup request"

    messages = [
        {
            "role": "system",
            "content": expand_prompt_placeholders(OLLAMA_DECIDER_SYSTEM_PROMPT),
        }
    ]
    messages.extend(history)
    messages.append({"role": "user", "content": user_prompt})
    content = chat_once(messages, model=OLLAMA_DECIDER_MODEL).strip()
    lines = [ln.strip() for ln in content.splitlines() if ln.strip()]
    first = lines[0] if lines else ""

    # Preferred strict format: DECISION|REASON with DECISION in {SEARCH, ANSWER}
    if "|" in first:
        left, right = first.split("|", 1)
        decision = left.strip().upper()
        reason = right.strip()
        if decision in {"SEARCH", "ANSWER"}:
            return decision == "SEARCH", (reason or "no reason provided")

    # Tolerant parsing for small models (e.g. "DECISION: SEARCH", "SEARCH - ...")
    upper = content.upper()
    if re.search(r"\bSEARCH\b", upper) and not re.search(r"\bANSWER\b", upper):
        return True, content
    if re.search(r"\bANSWER\b", upper) and not re.search(r"\bSEARCH\b", upper):
        return False, content

    # If both appear, prefer explicit "DECISION: X" marker.
    m = re.search(r"DECISION\s*[:=]\s*(SEARCH|ANSWER)\b", upper)
    if m:
        return m.group(1) == "SEARCH", content

    # If the model produced a substantive sentence instead of a decision token,
    # fail closed to SEARCH to avoid fabricated or stale answers.
    if len(content.split()) >= 5:
        return True, f"implicit SEARCH due to unparsable decision text: {content}"

    return True, f"default SEARCH due to decision parse failure: {content}"


def parse_search_data_for_prompt(tool_json: str) -> dict[str, Any]:
    search_data = (tool_json or "").strip()
    if not search_data:
        raise ValueError("Search data was empty before LLM answer synthesis.")

    try:
        parsed = json.loads(search_data)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Search data was not valid JSON before LLM answer synthesis: {exc}") from exc

    fetched_pages = parsed.get("fetched_pages", []) if isinstance(parsed, dict) else []
    if not isinstance(fetched_pages, list):
        raise ValueError("Search data fetched_pages was not a list.")
    for index, page in enumerate(fetched_pages):
        if not isinstance(page, dict):
            raise ValueError(f"Search data fetched_pages[{index}] was not an object.")
        content = page.get("content")
        if not isinstance(content, str):
            raise ValueError(f"Search data fetched_pages[{index}].content was not a string.")
        if content and not content.rstrip().endswith("[END EXCERPT]"):
            raise ValueError(f"Search data fetched_pages[{index}].content was missing [END EXCERPT].")

    if not isinstance(parsed, dict):
        raise ValueError("Search data was not a JSON object.")

    return parsed


def format_search_data_for_prompt(tool_json: str) -> str:
    parsed = parse_search_data_for_prompt(tool_json)
    fetched_pages = [
        page
        for page in parsed.get("fetched_pages", [])
        if isinstance(page, dict) and page.get("extractor") == "trafilatura"
    ][:5]
    if not fetched_pages:
        raise ValueError("Search produced no usable Trafilatura-extracted article sources.")
    lines = [
        "BEGIN WEB NEWS SEARCH RESULTS",
        "These are fetched and extracted article sources from a live web news search.",
        "Use them as current source material for the user's question.",
    ]

    for index, page in enumerate(fetched_pages, start=1):
        if not isinstance(page, dict):
            continue
        lines.append(f"BEGIN SOURCE {index}")
        lines.append(f"Title: {str(page.get('title') or '').strip()}")
        lines.append(f"URL: {str(page.get('url') or '').strip()}")
        published = str(page.get("published") or "").strip()
        if published:
            lines.append(f"Published: {published}")
        author = str(page.get("author") or "").strip()
        if author:
            lines.append(f"Author: {author}")
        lines.append("Excerpt:")
        lines.append(str(page.get("content") or "").strip())
        lines.append(f"END SOURCE {index}")

    lines.append("END WEB NEWS SEARCH RESULTS")
    formatted = "\n".join(lines)
    if not formatted.rstrip().endswith("END WEB NEWS SEARCH RESULTS"):
        raise ValueError("Formatted web news search block is missing END WEB NEWS SEARCH RESULTS.")
    if len(re.findall(r"^BEGIN SOURCE \d+$", formatted, flags=re.M)) != len(
        re.findall(r"^END SOURCE \d+$", formatted, flags=re.M)
    ):
        raise ValueError("Formatted web news search block has mismatched source markers.")
    return formatted


def answer_from_results(user_prompt: str, tool_json: str, history: list[dict[str, str]]) -> str:
    search_data = format_search_data_for_prompt(tool_json)
    messages = [
        {
            "role": "user",
            "content": (
                f"{expand_prompt_placeholders(ANSWER_FROM_RESULTS_PROMPT)} "
                f"{expand_prompt_placeholders(ANSWER_FROM_RESULTS_EXTRA_SYSTEM_PROMPT)}"
            ),
        }
    ]
    messages.extend(history)
    messages.append({"role": "user", "content": user_prompt})
    messages.append(
        {
            "role": "user",
            "content": search_data,
        }
    )
    return chat_once(messages)


def answer_from_memory(user_prompt: str, history: list[dict[str, str]]) -> str:
    messages = [
        {
            "role": "system",
            "content": expand_prompt_placeholders(MEMORY_ANSWER_SYSTEM_PROMPT),
        }
    ]
    messages.extend(history)
    messages.append({"role": "user", "content": user_prompt})
    return chat_once(messages)


def answer_direct(user_prompt: str) -> str:
    return chat_once([{"role": "user", "content": user_prompt}])


def parse_args():
    parser = argparse.ArgumentParser(description="Run DDGS web search/fetch pipeline in debug mode.")
    parser.add_argument("query", nargs="*", help="Search query text.")
    parser.add_argument("--once", action="store_true", help="Run once and exit.")
    return parser.parse_args()


def print_commands() -> None:
    print("[Commands]")
    print("/?                 Show commands.")
    print("/new               Clear chat context.")
    print("/decider <prompt>  Run Python decider only; bypass rules.")
    print("/search-off        Disable search and send prompt directly to the LLM.")
    print("/search-on         Enable search and decider logic.")
    print("/llm-off           Skip final LLM answer after search.")
    print("/llm-on            Enable final LLM answer after search.")
    print("/prompt-on         Show text sent to the answer/query LLM.")
    print("/prompt-off        Hide text sent to the answer/query LLM.")
    print("exit, quit, q      Exit.")
    print()


class ChatSession:
    def __init__(self, rich_output: bool = True) -> None:
        self.history: list[dict[str, str]] = []
        self.rich_output = rich_output
        self.prompt_debug = PROMPT_DEBUG
        self.llm_enabled = LLM_ENABLED
        self.search_enabled = SEARCH_ENABLED
        self.search_limit = SEARCH_LIMIT
        self.fetch_top_n = FETCH_TOP_N
        self.fetch_scan_limit = FETCH_SCAN_LIMIT
        self.fetch_max_chars = FETCH_MAX_CHARS

    def _set_context(self) -> tuple[Any, Any]:
        prompt_token = PROMPT_DEBUG_CONTEXT.set(self.prompt_debug)
        llm_token = LLM_ENABLED_CONTEXT.set(self.llm_enabled)
        return prompt_token, llm_token

    def _reset_context(self, tokens: tuple[Any, Any]) -> None:
        prompt_token, llm_token = tokens
        PROMPT_DEBUG_CONTEXT.reset(prompt_token)
        LLM_ENABLED_CONTEXT.reset(llm_token)

    def run_query(self, query: str) -> None:
        tokens = self._set_context()
        try:
            self._run_query(query)
        finally:
            self._reset_context(tokens)

    def _run_query(self, query: str) -> None:
        if not self.search_enabled:
            llm_start = time.perf_counter()
            try:
                answer = answer_direct(query)
            except LlmSkipped:
                llm_ms = (time.perf_counter() - llm_start) * 1000
                print(f"[LLM: {llm_ms:.0f} ms, {OLLAMA_MODEL}]")
                print("[LLM: skipped]")
                print()
                return
            except Exception as exc:
                llm_ms = (time.perf_counter() - llm_start) * 1000
                print(f"[LLM: {llm_ms:.0f} ms, {OLLAMA_MODEL}]")
                print("[Assistant]")
                print(f"LLM answer failed: {exc}")
                print()
                return
            llm_ms = (time.perf_counter() - llm_start) * 1000
            print(f"[LLM: {llm_ms:.0f} ms, {OLLAMA_MODEL}]")
            print_assistant_answer(answer, self.rich_output)
            return

        marker = forced_search_marker(query)
        will_run_decider = SEARCH_DECIDER in {"python", "ollama"} and marker is None
        decider_start = time.perf_counter()
        should_search, decision_reason, search_query = decide_search_action(query, self.history)
        decider_ms = (time.perf_counter() - decider_start) * 1000
        if will_run_decider:
            print(format_decider_elapsed(decider_ms))
        elif marker:
            print(f"[Decider: skipped, forced search marker = {marker}]")

        if not should_search:
            llm_start = time.perf_counter()
            try:
                answer = answer_from_memory(query, self.history)
            except LlmSkipped:
                llm_ms = (time.perf_counter() - llm_start) * 1000
                print(f"[LLM: {llm_ms:.0f} ms, {OLLAMA_MODEL}]")
                print("[LLM: skipped]")
                print()
                return
            except Exception as exc:
                llm_ms = (time.perf_counter() - llm_start) * 1000
                print(f"[LLM: {llm_ms:.0f} ms, {OLLAMA_MODEL}]")
                print("[Assistant]")
                print(f"LLM answer failed: {exc}")
                print()
                return
            llm_ms = (time.perf_counter() - llm_start) * 1000
            print(f"[LLM: {llm_ms:.0f} ms, {OLLAMA_MODEL}]")
            print_assistant_answer(answer, self.rich_output)
            self.history.append({"role": "user", "content": query})
            self.history.append({"role": "assistant", "content": answer})
            return

        if not search_query:
            try:
                search_query = derive_search_query(query, self.history)
            except LlmSkipped:
                search_query = query
            except Exception as exc:
                print("[Assistant]")
                print(f"LLM query-builder failed: {exc}")
                print()
                return

        search_start = time.perf_counter()
        try:
            result = run_search(
                query=search_query,
                search_limit=self.search_limit,
                fetch_top_n=self.fetch_top_n,
                fetch_scan_limit=self.fetch_scan_limit,
                fetch_max_chars=self.fetch_max_chars,
            )
        except Exception as exc:
            search_ms = (time.perf_counter() - search_start) * 1000
            print(f"[Search: {search_ms:.0f} ms, failed]")
            print("[Assistant]")
            print(f"Search failed: {exc}")
            print()
            return
        search_ms = (time.perf_counter() - search_start) * 1000
        print(f"[Search: {search_ms:.0f} ms, {len(result):.0f} chars]")

        if DEBUG:
            print(f"[Tool] web_search query: {search_query}")
            print(f"[Tool] result: {result}\n")

        if SUMMARIZE_EXCERPTS_WITH_DECIDER:
            summary_start = time.perf_counter()
            original_chars = len(result)
            result = summarize_search_result_excerpts(result)
            summary_ms = (time.perf_counter() - summary_start) * 1000
            print(f"[Summaries: {summary_ms:.0f} ms, {original_chars} -> {len(result)} chars, {SUMMARY_MODEL}]")

        llm_start = time.perf_counter()
        try:
            answer = answer_from_results(query, result, self.history)
        except LlmSkipped:
            llm_ms = (time.perf_counter() - llm_start) * 1000
            print(f"[LLM: {llm_ms:.0f} ms, {OLLAMA_MODEL}]")
            print("[LLM: skipped]")
            print()
            return
        except Exception as exc:
            llm_ms = (time.perf_counter() - llm_start) * 1000
            print(f"[LLM: {llm_ms:.0f} ms, {OLLAMA_MODEL}]")
            print("[Assistant]")
            print(f"LLM answer failed: {exc}")
            print()
            return

        llm_ms = (time.perf_counter() - llm_start) * 1000
        print(f"[LLM: {llm_ms:.0f} ms, {OLLAMA_MODEL}]")
        print_assistant_answer(answer, self.rich_output)
        self.history.append({"role": "user", "content": query})
        self.history.append({"role": "assistant", "content": answer})

    def handle_input(self, user_query: str) -> bool:
        if not user_query:
            return True
        if user_query == "/?":
            print_commands()
            return True
        if user_query.lower() == "/new":
            self.history.clear()
            print("[System] Context cleared.")
            print()
            return True
        if user_query.lower() == "/prompt-on":
            self.prompt_debug = True
            print("[System] Prompt display enabled.")
            print()
            return True
        if user_query.lower() == "/prompt-off":
            self.prompt_debug = False
            print("[System] Prompt display disabled.")
            print()
            return True
        if user_query.lower() == "/llm-off":
            self.llm_enabled = False
            print("[System] Final LLM answer disabled.")
            print()
            return True
        if user_query.lower() == "/llm-on":
            self.llm_enabled = True
            print("[System] Final LLM answer enabled.")
            print()
            return True
        if user_query.lower() == "/search-off":
            self.search_enabled = False
            print("[System] Search disabled. Prompts will be sent directly to the LLM.")
            print()
            return True
        if user_query.lower() == "/search-on":
            self.search_enabled = True
            print("[System] Search enabled.")
            print()
            return True
        if user_query.lower().startswith("/decider"):
            decider_prompt = user_query[len("/decider"):].strip()
            if not decider_prompt:
                print("[System] Usage: /decider <prompt>")
                print()
                return True
            tokens = self._set_context()
            try:
                start = time.perf_counter()
                should_search, reason, search_query = decide_with_qwen(decider_prompt, self.history)
                decider_ms = (time.perf_counter() - start) * 1000
            finally:
                self._reset_context(tokens)
            decision = "SEARCH" if should_search else "ANSWER"
            print(format_decider_elapsed(decider_ms))
            print(f"{decision} | {reason}")
            if search_query:
                print(f"query: {search_query}")
            print()
            return True
        if user_query.lower() in {"quit", "exit", "q"}:
            print("Exiting.")
            return False
        if user_query.startswith("/"):
            print(f"[System] Unknown command: {user_query}")
            print_commands()
            return True

        self.run_query(user_query)
        return True


def preload_models() -> None:
    if SEARCH_DECIDER == "qwen":
        raise ValueError("SEARCH_DECIDER=qwen is obsolete. Use SEARCH_DECIDER=python.")
    if SEARCH_DECIDER == "python":
        preload_start = time.perf_counter()
        get_qwen_decider()
        preload_ms = (time.perf_counter() - preload_start) * 1000
        print(f"[Decider preload: {preload_ms:.0f} ms]")
    if SUMMARIZE_EXCERPTS_WITH_DECIDER:
        preload_start = time.perf_counter()
        get_python_model(SUMMARY_MODEL)
        preload_ms = (time.perf_counter() - preload_start) * 1000
        print(f"[Summary preload: {preload_ms:.0f} ms]")
    if DECIDER_RELEVANCE_ENABLED:
        preload_start = time.perf_counter()
        get_relevancy_model()
        preload_ms = (time.perf_counter() - preload_start) * 1000
        print(f"[Relevancy preload: {preload_ms:.0f} ms]")


def main():
    args = parse_args()
    preload_models()
    session = ChatSession()

    initial_query = (" ".join(args.query).strip() if args.query else "")
    if args.once:
        if not initial_query:
            initial_query = QUESTION.strip()
        if not initial_query:
            print("QUESTION is empty.")
            raise SystemExit(1)
        session.run_query(initial_query)
        raise SystemExit(0)

    while True:
        try:
            user_query = input("AI ready> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nExiting.")
            break
        if not session.handle_input(user_query):
            break


if __name__ == "__main__":
    main()


