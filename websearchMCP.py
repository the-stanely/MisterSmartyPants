from __future__ import annotations

import argparse
from contextvars import ContextVar
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
import hashlib
import html as html_module
import json
import os
import re
import sys
import time
from typing import Any
from urllib.parse import quote, unquote, urlparse

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


def read_non_negative_int_env(name: str, default: str) -> int:
    value = int(os.getenv(name, default))
    if value < 0:
        raise ValueError(f"{name} must be 0 or greater; got {value}")
    return value
OLLAMA_API = os.getenv("OLLAMA_API", "http://localhost:11434/api/chat")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "cow/gemma2_tools")
OLLAMA_TIMEOUT_SECONDS = int(os.getenv("OLLAMA_TIMEOUT_SECONDS", "300"))
OLLAMA_NUM_CTX = int(os.getenv("OLLAMA_NUM_CTX", "32768"))
OLLAMA_TEMPERATURE = float(os.getenv("OLLAMA_TEMPERATURE", "0.2"))
OLLAMA_TOP_P = float(os.getenv("OLLAMA_TOP_P", "0.9"))
OLLAMA_NUM_PREDICT = int(os.getenv("OLLAMA_NUM_PREDICT", "512"))
OLLAMA_NUM_THREAD_RAW = os.getenv("OLLAMA_NUM_THREAD", "").strip()
OLLAMA_NUM_THREAD = int(OLLAMA_NUM_THREAD_RAW) if OLLAMA_NUM_THREAD_RAW else None
QUESTION = os.getenv("QUESTION", "Wall street biggest movers.")
SEARCH_LIMIT = 12
SEARCH_NEWS_LIMIT = read_positive_int_env("SEARCH_NEWS_LIMIT", "10")
SEARCH_TEXT_LIMIT = read_positive_int_env("SEARCH_TEXT_LIMIT", "10")
FETCH_SURVIVOR_N = read_positive_int_env("FETCH_SURVIVOR_N", "20")
FETCH_TOP_N = read_positive_int_env("FETCH_TOP_N", "5")
FETCH_MAX_CHARS = int(os.getenv("FETCH_MAX_CHARS", "3000"))
FETCH_SCAN_LIMIT = read_positive_int_env("FETCH_SCAN_LIMIT", "20")
FETCH_CANDIDATE_N = read_positive_int_env("FETCH_CANDIDATE_N", "5")
FETCH_WORKERS = read_positive_int_env("FETCH_WORKERS", "4")
SEARCH_META_ENRICH_ENABLED = os.getenv("SEARCH_META_ENRICH_ENABLED", "1") == "1"
SEARCH_META_ENRICH_LIMIT_RAW = read_non_negative_int_env("SEARCH_META_ENRICH_LIMIT", "5")
SEARCH_META_ENRICH_LIMIT: int | None = None if SEARCH_META_ENRICH_LIMIT_RAW == 0 else SEARCH_META_ENRICH_LIMIT_RAW
SEARCH_MODES = tuple(
    mode.strip().lower()
    for mode in os.getenv("SEARCH_MODES", "news,text").split(",")
    if mode.strip()
)
SUMMARIZE_EXCERPTS = os.getenv(
    "SUMMARIZE_EXCERPTS",
    os.getenv("SUMMARIZE_EXCERPTS_WITH_DECIDER", "1"),
) == "1"
SUMMARY_PROVIDER = os.getenv("SUMMARY_PROVIDER", "python").strip().lower()
DECIDER_SUMMARY_MAX_TOKENS = int(os.getenv("DECIDER_SUMMARY_MAX_TOKENS", "180"))
DECIDER_SUMMARY_PROMPT = os.getenv(
    "DECIDER_SUMMARY_PROMPT",
    "User question:\n{user_question}\n\nWrite a concise summary of the article focusing on information that helps answer the user question. Preserve dates, names, numbers, and source-specific claims. Do not add information not present in the article.\n\nArticle:\n{excerpt_text}",
)
PYTHON_GENERATION_NO_THINK = os.getenv("PYTHON_GENERATION_NO_THINK", "1") == "1"
PYTHON_GENERATION_NO_THINK_INSTRUCTION = os.getenv("PYTHON_GENERATION_NO_THINK_INSTRUCTION", "/no_think")
DECIDER_RELEVANCE_ENABLED = os.getenv("DECIDER_RELEVANCE_ENABLED", "1") == "1"
DECIDER_RELEVANCE_EXCERPT_CHARS = int(os.getenv("DECIDER_RELEVANCE_EXCERPT_CHARS", "1200"))
RELEVANCY_MODEL = os.getenv("RELEVANCY_MODEL", "cross-encoder/ms-marco-MiniLM-L-6-v2")
RELEVANCY_THRESHOLD = float(os.getenv("RELEVANCY_THRESHOLD", "0.0"))
REQUEST_TIMEOUT_SECONDS = int(os.getenv("REQUEST_TIMEOUT_SECONDS", "20"))
DDGS_TIMEOUT_SECONDS = int(os.getenv("DDGS_TIMEOUT_SECONDS", "20"))
DDGS_TEXT_BACKEND = os.getenv("DDGS_TEXT_BACKEND", "duckduckgo").strip() or "duckduckgo"
DDGS_NEWS_BACKEND = os.getenv("DDGS_NEWS_BACKEND", "duckduckgo").strip() or "duckduckgo"
DDGS_REGION = os.getenv("DDGS_REGION", "us-en").strip() or "us-en"
DDGS_SAFESEARCH = os.getenv("DDGS_SAFESEARCH", "moderate").strip() or "moderate"
DDGS_TIMELIMIT_RAW = os.getenv("DDGS_TIMELIMIT", "").strip()
DDGS_TIMELIMIT = DDGS_TIMELIMIT_RAW or None
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "").strip()
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
    "Convert this user request into a Google web search query. "
    "Return only the query text, no quotes, no JSON, no explanation. "
    "Use spaces between words."
)
QUERY_BUILDER_SYSTEM_PROMPT = os.getenv("QUERY_BUILDER_SYSTEM_PROMPT", DEFAULT_QUERY_BUILDER_SYSTEM_PROMPT)
DEFAULT_OLLAMA_DECIDER_SYSTEM_PROMPT = (
    'Today is {today_date}. This is a YES or NO question. '
    'Say YES if you have enough knowledge to answer it. '
    'Say NO if you need more information. '
    '"{user_prompt}" '
    'Output 5 tokens max.'
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


def meta_description_from_html(html_text: str) -> str:
    patterns = (
        r'<meta[^>]+name=["\']description["\'][^>]+content=["\'](.*?)["\']',
        r'<meta[^>]+content=["\'](.*?)["\'][^>]+name=["\']description["\']',
        r'<meta[^>]+property=["\']og:description["\'][^>]+content=["\'](.*?)["\']',
        r'<meta[^>]+content=["\'](.*?)["\'][^>]+property=["\']og:description["\']',
    )
    for pattern in patterns:
        match = re.search(pattern, html_text, flags=re.I | re.S)
        if match:
            return html_module.unescape(re.sub(r"\s+", " ", match.group(1)).strip())
    return ""


def page_metadata_description(url: str) -> str:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
        )
    }
    try:
        response = requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT_SECONDS, allow_redirects=True)
        ctype = (response.headers.get("content-type") or "").lower()
        if response.status_code >= 400:
            return ""
        if "text/html" not in ctype and "application/xhtml+xml" not in ctype:
            return ""
        return meta_description_from_html(response.text)
    except Exception:
        return ""


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
    haystack = " ".join([item.get("title", ""), item.get("snippet", ""), item.get("url", ""), item.get("published", "")])
    years = [
        int(year_text)
        for year_text in re.findall(r"\b(20\d{2})\b", haystack)
        if int(year_text) not in requested_years
    ]
    if not years:
        return False
    # Keep when any current/recent year appears; reject only when all detected years are old.
    if any(year >= current_year - 1 for year in years):
        return False
    return True


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
            include_tables=True,
            deduplicate=True,
            favor_recall=True,
        )
    except Exception as exc:
        return {"url": url, "title": fallback_title, "content": f"Fetch error: trafilatura extraction failed: {exc}"}

    if not extracted:
        return {"url": url, "title": fallback_title, "content": "Fetch error: trafilatura returned no content"}

    try:
        obj = json.loads(extracted)
    except json.JSONDecodeError as exc:
        return {"url": url, "title": fallback_title, "content": f"Fetch error: trafilatura returned invalid JSON: {exc}"}

    normalized = re.sub(r"\s+", " ", str(obj.get("text") or obj.get("raw_text") or "")).strip()
    if not normalized:
        return {"url": url, "title": str(obj.get("title") or fallback_title), "content": "Fetch error: trafilatura returned empty text"}
    text = normalized if normalized.endswith("[END EXCERPT]") else f"{normalized} [END EXCERPT]"

    return {
        "url": url,
        "title": str(obj.get("title") or fallback_title),
        "author": str(obj.get("author") or ""),
        "published": str(obj.get("date") or ""),
        "content": text,
        "extractor": "trafilatura",
        "extracted_chars": str(len(normalized)),
        "content_chars": str(len(text)),
        "truncated": "false",
    }


GITHUB_RESERVED_PATHS = {
    "about",
    "collections",
    "customer-stories",
    "enterprise",
    "events",
    "explore",
    "features",
    "issues",
    "login",
    "marketplace",
    "new",
    "notifications",
    "organizations",
    "pricing",
    "pulls",
    "search",
    "settings",
    "sponsors",
    "topics",
    "trending",
}


def github_api_headers() -> dict[str, str]:
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "MisterSmartyPants",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if GITHUB_TOKEN:
        headers["Authorization"] = f"Bearer {GITHUB_TOKEN}"
    return headers


def github_api_get(path: str, params: dict[str, Any] | None = None) -> Any:
    response = requests.get(
        f"https://api.github.com{path}",
        headers=github_api_headers(),
        params=params or {},
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    if response.status_code >= 400:
        raise RuntimeError(f"GitHub API HTTP {response.status_code}: {response.text[:300]}")
    return response.json()


def github_url_parts(url: str) -> tuple[str, str | None] | None:
    parsed = urlparse(url)
    host = parsed.netloc.lower()
    if host not in {"github.com", "www.github.com"}:
        return None
    parts = [unquote(part) for part in parsed.path.strip("/").split("/") if part]
    if not parts:
        return None
    owner = parts[0]
    if owner.lower() in GITHUB_RESERVED_PATHS:
        return None
    repo = parts[1] if len(parts) >= 2 and parts[1] else None
    if repo and repo.lower() in GITHUB_RESERVED_PATHS:
        repo = None
    return owner, repo


def is_low_value_github_snippet(snippet: str) -> bool:
    low = snippet.lower()
    markers = (
        "prevent this user from interacting",
        "sending you notifications",
        "learn more about blocking users",
        "block or report",
        "uh oh",
        "there was an error while loading",
    )
    if not low.strip():
        return True
    return any(marker in low for marker in markers)


def github_meta_description(url: str) -> str:
    return page_metadata_description(url)


def enrich_search_snippet(url: str, title: str, snippet: str) -> str:
    if github_url_parts(url) and is_low_value_github_snippet(snippet):
        meta_description = github_meta_description(url)
        if meta_description:
            return meta_description
    return snippet


def should_prefetch_metadata(item: dict[str, str]) -> bool:
    if item.get("search_mode") != "text":
        return False
    url = str(item.get("url") or "")
    if not url.startswith("http") or is_probable_ad_url(url) or is_root_homepage_url(url):
        return False
    return True


def enrich_search_items_for_ranking(search_items: list[dict[str, str]]) -> list[dict[str, str]]:
    if not SEARCH_META_ENRICH_ENABLED or not search_items:
        return search_items

    enriched = [dict(item) for item in search_items]
    target_indexes = [
        index
        for index, item in enumerate(enriched)
        if should_prefetch_metadata(item)
    ]
    if SEARCH_META_ENRICH_LIMIT is not None:
        target_indexes = target_indexes[:SEARCH_META_ENRICH_LIMIT]

    if not target_indexes:
        return enriched

    def fetch_metadata(index: int) -> tuple[int, str]:
        item = enriched[index]
        return index, page_metadata_description(str(item.get("url") or ""))

    with ThreadPoolExecutor(max_workers=min(FETCH_WORKERS, len(target_indexes))) as executor:
        for index, description in executor.map(fetch_metadata, target_indexes):
            if not description:
                continue
            original_snippet = str(enriched[index].get("snippet") or "")
            enriched[index]["snippet"] = description
            enriched[index]["snippet_source"] = "meta-description"
            if original_snippet and original_snippet != description:
                enriched[index]["snippet_original"] = original_snippet

    return enriched


def format_github_datetime(value: Any) -> str:
    return str(value or "").strip()


def github_repo_line(repo: dict[str, Any]) -> str:
    pushed = format_github_datetime(repo.get("pushed_at"))
    updated = format_github_datetime(repo.get("updated_at"))
    language = str(repo.get("language") or "unknown")
    description = str(repo.get("description") or "").strip()
    details = [
        f"Repo: {repo.get('full_name')}",
        f"URL: {repo.get('html_url')}",
        f"Language: {language}",
        f"Stars: {repo.get('stargazers_count', 0)}",
        f"Forks: {repo.get('forks_count', 0)}",
    ]
    if pushed:
        details.append(f"Pushed: {pushed}")
    if updated:
        details.append(f"Updated: {updated}")
    if description:
        details.append(f"Description: {description}")
    return "\n".join(details)


def fetch_github_user(owner: str, source_url: str) -> dict[str, str]:
    safe_owner = quote(owner, safe="")
    user = github_api_get(f"/users/{safe_owner}")
    repos = github_api_get(
        f"/users/{safe_owner}/repos",
        {"sort": "updated", "direction": "desc", "per_page": 10},
    )
    if not isinstance(repos, list):
        repos = []

    lines = [
        f"GitHub user: {user.get('login') or owner}",
        f"Profile URL: {user.get('html_url') or source_url}",
    ]
    name = str(user.get("name") or "").strip()
    if name:
        lines.append(f"Name: {name}")
    bio = str(user.get("bio") or "").strip()
    if bio:
        lines.append(f"Bio: {bio}")
    lines.extend(
        [
            f"Public repos: {user.get('public_repos', '')}",
            f"Followers: {user.get('followers', '')}",
            f"Following: {user.get('following', '')}",
            f"Account created: {user.get('created_at', '')}",
            f"Profile updated: {user.get('updated_at', '')}",
            "",
            "Recently updated repositories:",
        ]
    )
    for repo in repos[:10]:
        if isinstance(repo, dict):
            lines.extend(["", github_repo_line(repo)])

    content = "\n".join(lines).strip()
    if not content.endswith("[END EXCERPT]"):
        content = f"{content} [END EXCERPT]"
    return {
        "url": str(user.get("html_url") or source_url),
        "title": f"GitHub user: {user.get('login') or owner}",
        "author": str(user.get("login") or owner),
        "published": str(user.get("updated_at") or ""),
        "content": content,
        "extractor": "github-api",
        "extracted_chars": str(len(content)),
        "content_chars": str(len(content)),
        "truncated": "false",
    }


def fetch_github_repo(owner: str, repo: str, source_url: str) -> dict[str, str]:
    safe_owner = quote(owner, safe="")
    safe_repo = quote(repo, safe="")
    repo_obj = github_api_get(f"/repos/{safe_owner}/{safe_repo}")
    commits = github_api_get(f"/repos/{safe_owner}/{safe_repo}/commits", {"per_page": 5})
    issues = github_api_get(
        f"/repos/{safe_owner}/{safe_repo}/issues",
        {"state": "open", "per_page": 5},
    )
    if not isinstance(commits, list):
        commits = []
    if not isinstance(issues, list):
        issues = []

    lines = [
        github_repo_line(repo_obj),
        f"Default branch: {repo_obj.get('default_branch', '')}",
        f"Open issues count: {repo_obj.get('open_issues_count', '')}",
        f"Created: {repo_obj.get('created_at', '')}",
        "",
        "Recent commits:",
    ]
    for commit_row in commits:
        if not isinstance(commit_row, dict):
            continue
        commit = commit_row.get("commit") if isinstance(commit_row.get("commit"), dict) else {}
        message = str(commit.get("message") or "").splitlines()[0]
        author = commit.get("author") if isinstance(commit.get("author"), dict) else {}
        lines.append(
            f"- {commit_row.get('sha', '')[:7]} {format_github_datetime(author.get('date'))} "
            f"{author.get('name', '')}: {message}"
        )

    lines.extend(["", "Open issues and pull requests:"])
    for issue in issues:
        if not isinstance(issue, dict):
            continue
        kind = "pull request" if issue.get("pull_request") else "issue"
        lines.append(
            f"- #{issue.get('number')} {kind}, updated {issue.get('updated_at')}: "
            f"{issue.get('title')} ({issue.get('html_url')})"
        )

    content = "\n".join(lines).strip()
    if not content.endswith("[END EXCERPT]"):
        content = f"{content} [END EXCERPT]"
    return {
        "url": str(repo_obj.get("html_url") or source_url),
        "title": f"GitHub repository: {repo_obj.get('full_name') or f'{owner}/{repo}'}",
        "author": str(owner),
        "published": str(repo_obj.get("pushed_at") or repo_obj.get("updated_at") or ""),
        "content": content,
        "extractor": "github-api",
        "extracted_chars": str(len(content)),
        "content_chars": str(len(content)),
        "truncated": "false",
    }


def fetch_github_api_content(url: str) -> dict[str, str] | None:
    parts = github_url_parts(url)
    if not parts:
        return None
    owner, repo = parts
    try:
        if repo:
            return fetch_github_repo(owner, repo, url)
        return fetch_github_user(owner, url)
    except Exception as exc:
        return {"url": url, "title": url, "content": f"Fetch error: GitHub API failed: {exc}"}


def fetch_url_content(url: str, max_chars: int) -> dict[str, str]:
    github_page = fetch_github_api_content(url)
    if github_page is not None:
        return github_page

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


def search_item_relevance_text(item: dict[str, str]) -> str:
    lines = [
        f"Mode: {item.get('search_mode', '')}",
        f"Title: {item.get('title', '')}",
        f"URL: {item.get('url', '')}",
    ]
    published = str(item.get("published") or "").strip()
    if published:
        lines.append(f"Published: {published}")
    snippet = str(item.get("snippet") or "").strip()
    if snippet:
        lines.extend(["", "Snippet:", snippet])
    return "\n".join(lines)


def score_search_items(query: str, search_items: list[dict[str, str]]) -> list[dict[str, str]]:
    if not search_items or not DECIDER_RELEVANCE_ENABLED:
        return search_items
    model = get_relevancy_model()
    pairs = [(query, search_item_relevance_text(item)) for item in search_items]
    scores = model.predict(pairs)
    ranked: list[dict[str, str]] = []
    for item, score in zip(search_items, scores):
        ranked_item = dict(item)
        ranked_item["initial_relevance_score"] = f"{float(score):.3f}"
        ranked.append(ranked_item)
    return sorted(ranked, key=lambda item: float(item.get("initial_relevance_score", "0")), reverse=True)


def post_fetch_reject_reason(query: str, item: dict[str, str], page: dict[str, str]) -> str | None:
    content = str(page.get("content") or "")
    if content.startswith("Fetch error:"):
        return content
    ok, reason = fetched_page_quality(page)
    if not ok:
        return reason
    url = str(page.get("url") or item.get("url") or "")
    if is_probable_ad_url(url):
        return "probable ad/tracking URL after redirect"
    if is_root_homepage_url(url):
        return "root homepage URL after redirect"
    extractor = str(page.get("extractor") or "")
    skip_stale_year_reject = extractor.endswith("-api") or github_url_parts(url) is not None
    stale_item = {
        "title": str(page.get("title") or item.get("title") or ""),
        "url": url,
        "snippet": content,
        "published": str(page.get("published") or item.get("published") or ""),
    }
    if asks_for_current_info(query) and not skip_stale_year_reject and has_stale_year_marker(query, stale_item):
        return "stale year marker after extraction"
    if asks_for_current_info(query) and "youtube.com" in url.lower():
        return "YouTube result for current-info query"
    return None


def score_fetched_pages(query: str, pages: list[dict[str, str]]) -> list[dict[str, str]]:
    if not pages or not DECIDER_RELEVANCE_ENABLED:
        return pages
    model = get_relevancy_model()
    relevance_texts = [relevance_classifier_text(page) for page in pages]
    scores = model.predict([(query, text) for text in relevance_texts])
    ranked: list[dict[str, str]] = []
    for page, relevance_text, score in zip(pages, relevance_texts, scores):
        ranked_page = dict(page)
        relevance_score = float(score)
        ranked_page["relevance_score"] = f"{relevance_score:.3f}"
        ranked_page["relevance_threshold"] = f"{RELEVANCY_THRESHOLD:.3f}"
        ranked_page["relevance_model"] = RELEVANCY_MODEL
        if prompt_debug_enabled():
            print(f"[Relevance input begin: {len(relevance_text)} chars]")
            print(f"Query: {query}")
            print()
            print(relevance_text)
            print("[Relevance input end]")
        ranked.append(ranked_page)
    return sorted(ranked, key=lambda page: float(page.get("relevance_score", "0")), reverse=True)


def print_search_candidate_debug(title: str, items: list[dict[str, str]]) -> None:
    print(f"[{title}: {len(items)}]")
    for index, item in enumerate(items, start=1):
        print(f"RESULT {index}")
        score = str(item.get("initial_relevance_score") or "").strip()
        if score:
            print(f"Initial score: {score}")
        print(f"Mode: {item.get('search_mode', '')}")
        print(f"Title: {item.get('title', '')}")
        print(f"URL: {item.get('url', '')}")
        published = str(item.get("published") or "").strip()
        if published:
            print(f"Published: {published}")
        snippet = str(item.get("snippet") or "").strip()
        if snippet:
            print("Snippet:")
            print(snippet)
        print()


def print_raw_ddgs_debug(raw_with_modes: list[tuple[str, dict[str, Any]]]) -> None:
    print(f"[Raw search results: {len(raw_with_modes)}]")
    for index, (mode, row) in enumerate(raw_with_modes, start=1):
        print(f"RAW RESULT {index}")
        print(f"Mode: {mode}")
        if isinstance(row, dict):
            for key in ("title", "href", "url", "date", "published", "published_date", "source", "body", "snippet"):
                if key in row and row.get(key):
                    print(f"{key}: {row.get(key)}")
        else:
            print(row)
        print()


def print_fetch_debug_detail(
    item: dict[str, str],
    page: dict[str, str],
    fetch_ms: float,
    status_text: str,
    reason: str,
) -> None:
    print(f"[Fetch detail: {status_text}]")
    score = str(item.get("initial_relevance_score") or "").strip()
    if score:
        print(f"Initial score: {score}")
    print(f"Fetch ms: {fetch_ms:.0f}")
    print(f"Reason: {reason}")
    print(f"Search mode: {item.get('search_mode', '')}")
    print(f"Search title: {item.get('title', '')}")
    print(f"Search URL: {item.get('url', '')}")
    snippet = str(item.get("snippet") or "").strip()
    if snippet:
        print("Search snippet:")
        print(snippet)
    print("Trafilatura title:", page.get("title", ""))
    print("Trafilatura URL:", page.get("url", ""))
    print("Published:", page.get("published", ""))
    print("Author:", page.get("author", ""))
    print("Extractor:", page.get("extractor", ""))
    print("Extracted chars:", page.get("extracted_chars", ""))
    print("Content chars:", page.get("content_chars", ""))
    print("Truncated:", page.get("truncated", ""))
    content = str(page.get("content") or "")
    if content:
        print("Trafilatura content:")
        print(content)
    print("[Fetch detail end]")
    print()


def print_final_rank_debug(pages: list[dict[str, str]]) -> None:
    print(f"[Final fetched article ranking: {len(pages)}]")
    for index, page in enumerate(pages, start=1):
        print(f"ARTICLE {index}")
        print(f"Final score: {page.get('relevance_score', '')}")
        print(f"Initial score: {page.get('initial_relevance_score', '')}")
        print(f"Search mode: {page.get('search_mode', '')}")
        print(f"Title: {page.get('title', '')}")
        print(f"URL: {page.get('url', '')}")
        print(f"Published: {page.get('published', '')}")
        print(f"Author: {page.get('author', '')}")
        print(f"Extracted chars: {page.get('extracted_chars', '')}")
        print(f"Content chars: {page.get('content_chars', '')}")
        print()

def run_search(query: str, search_limit: int, fetch_top_n: int, fetch_scan_limit: int, fetch_max_chars: int) -> str:
    raw_with_modes: list[tuple[str, dict[str, Any]]] = []
    mode_errors: list[str] = []
    # Normalize query format for DDGS compatibility
    query = normalize_query_for_ddgs(query)
    if prompt_debug_enabled():
        print(f"[DDGS search with query: {query!r}]")
    with DDGS(timeout=DDGS_TIMEOUT_SECONDS) as ddgs:
        if "news" in SEARCH_MODES:
            try:
                raw_with_modes.extend(
                    ("news", row)
                    for row in ddgs.news(
                        query,
                        max_results=SEARCH_NEWS_LIMIT,
                        backend=DDGS_NEWS_BACKEND,
                        region=DDGS_REGION,
                        safesearch=DDGS_SAFESEARCH,
                        timelimit=DDGS_TIMELIMIT,
                    )
                )
            except Exception as exc:
                mode_errors.append(f"news: {exc}")
        if "text" in SEARCH_MODES:
            try:
                raw_with_modes.extend(
                    ("text", row)
                    for row in ddgs.text(
                        query,
                        max_results=SEARCH_TEXT_LIMIT,
                        backend=DDGS_TEXT_BACKEND,
                        region=DDGS_REGION,
                        safesearch=DDGS_SAFESEARCH,
                        timelimit=DDGS_TIMELIMIT,
                    )
                )
            except Exception as exc:
                mode_errors.append(f"text: {exc}")
    if prompt_debug_enabled():
        print_raw_ddgs_debug(raw_with_modes)

    if not raw_with_modes:
        detail = "; ".join(mode_errors) if mode_errors else "No results found."
        raise RuntimeError(f"Search failed: {detail}")

    search_items: list[dict[str, str]] = []
    seen_urls: set[str] = set()
    fetch_debug: list[dict[str, str]] = []
    for search_mode, row in raw_with_modes:
        if not isinstance(row, dict):
            continue
        url = row.get("href") or row.get("url")
        title = row.get("title") or url or ""
        if isinstance(url, str) and url.startswith("http"):
            normalized_url = url.split("#", 1)[0]
            if normalized_url in seen_urls:
                continue
            seen_urls.add(normalized_url)
            snippet = enrich_search_snippet(
                normalized_url,
                str(title),
                str(row.get("body") or row.get("snippet") or ""),
            )
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
                "url": normalized_url,
                "snippet": str(snippet),
                "published": published,
                "search_mode": search_mode,
            }
            search_items.append(item)

    if not search_items:
        raise RuntimeError("Search produced no usable URL candidates.")

    if prompt_debug_enabled():
        print_search_candidate_debug("Deduped DDGS candidates before rank", search_items)

    ranked_search_items = score_search_items(
        query,
        enrich_search_items_for_ranking(prioritize_search_items(search_items)),
    )
    if ranked_search_items:
        print(f"[Search rank: {len(ranked_search_items)} candidates, {RELEVANCY_MODEL if DECIDER_RELEVANCE_ENABLED else 'disabled'}]")
        if prompt_debug_enabled():
            print_search_candidate_debug("Initial cross-encoder search ranking", ranked_search_items)

    fetched_survivors: list[dict[str, str]] = []
    workers = max(1, FETCH_WORKERS)
    survivor_limit = max(FETCH_SURVIVOR_N, fetch_top_n)

    for batch_start in range(0, len(ranked_search_items), workers):
        if len(fetched_survivors) >= survivor_limit:
            break
        batch = ranked_search_items[batch_start:batch_start + workers]

        def fetch_item(item: dict[str, str]) -> tuple[dict[str, str], dict[str, str], float]:
            fetch_start = time.perf_counter()
            page = fetch_url_content(item["url"], fetch_max_chars)
            fetch_ms = (time.perf_counter() - fetch_start) * 1000
            return item, page, fetch_ms

        with ThreadPoolExecutor(max_workers=min(workers, len(batch))) as executor:
            batch_results = list(executor.map(fetch_item, batch))

        for item, page, fetch_ms in batch_results:
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
            page["initial_relevance_score"] = item.get("initial_relevance_score", "")

            reject_reason = post_fetch_reject_reason(query, item, page)
            if reject_reason:
                fetch_debug.append({"url": item["url"], "status": "skip", "reason": reject_reason, "ms": f"{fetch_ms:.0f}"})
                if prompt_debug_enabled():
                    print_fetch_debug_detail(item, page, fetch_ms, "skip", reject_reason)
                continue

            duplicate = duplicate_reason(page, fetched_survivors)
            if duplicate:
                fetch_debug.append({"url": item["url"], "status": "skip", "reason": duplicate, "ms": f"{fetch_ms:.0f}"})
                if prompt_debug_enabled():
                    print_fetch_debug_detail(item, page, fetch_ms, "skip", duplicate)
                continue

            fetched_survivors.append(page)
            fetch_debug.append({"url": item["url"], "status": "keep", "reason": "post-fetch ok", "ms": f"{fetch_ms:.0f}"})
            if prompt_debug_enabled():
                print_fetch_debug_detail(item, page, fetch_ms, "keep", "post-fetch ok")
            if len(fetched_survivors) >= survivor_limit:
                break

    ranked_pages = score_fetched_pages(query, fetched_survivors)
    fetched_pages = ranked_pages[:fetch_top_n]
    print(f"[Fetch rank: {len(fetched_survivors)} survivors -> {len(fetched_pages)} sources]")
    if prompt_debug_enabled():
        print_final_rank_debug(ranked_pages)

    payload = {"search_results": ranked_search_items, "fetched_pages": fetched_pages, "fetch_debug": fetch_debug}
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


def chat_once(messages: list[dict[str, str]], model: str = OLLAMA_MODEL, num_predict: int | None = None) -> str:
    serialized_messages = validate_llm_messages(messages)
    if prompt_debug_enabled():
        print_prompt_debug(messages, serialized_messages, model)
    options = {
        "num_ctx": OLLAMA_NUM_CTX,
        "temperature": OLLAMA_TEMPERATURE,
        "top_p": OLLAMA_TOP_P,
        "num_predict": num_predict if num_predict is not None else OLLAMA_NUM_PREDICT,
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


def expand_prompt_placeholders(prompt: str, **values: str) -> str:
    now = datetime.now().astimezone()
    expanded = prompt
    expanded = expanded.replace("{date-time}", now.strftime("%Y-%m-%d %H:%M:%S %Z%z"))
    expanded = expanded.replace("{today_date}", now.strftime("%Y-%m-%d"))
    for key, value in values.items():
        expanded = expanded.replace("{" + key + "}", value)
    return expanded


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


def summary_prompt_for_excerpt(excerpt_text: str, user_question: str) -> str:
    return (
        expand_prompt_placeholders(DECIDER_SUMMARY_PROMPT)
        .replace("{user_question}", user_question)
        .replace("{excerpt_text}", excerpt_text)
    )

def normalize_summary_text(generated: str) -> str:
    summary = re.sub(r"\s+", " ", generated or "").strip()
    if not summary:
        raise ValueError("Article summary was empty.")
    if not summary.endswith((".", "!", "?")):
        summary = f"{summary}."
    return f"{summary} [END EXCERPT]"


def summarize_with_python(excerpt_text: str, user_question: str) -> str:
    summary_model = get_python_model(SUMMARY_MODEL)
    tokenizer = summary_model["tokenizer"]
    model = summary_model["model"]
    torch = summary_model["torch"]
    device = summary_model["device"]
    messages = [
        {
            "role": "user",
            "content": apply_python_generation_controls(summary_prompt_for_excerpt(excerpt_text, user_question)),
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
    return normalize_summary_text(generated)


def summarize_with_ollama(excerpt_text: str, user_question: str) -> str:
    generated = chat_once(
        [{"role": "user", "content": summary_prompt_for_excerpt(excerpt_text, user_question)}],
        model=SUMMARY_MODEL,
        num_predict=DECIDER_SUMMARY_MAX_TOKENS,
    )
    return normalize_summary_text(generated)

def summarize_article_excerpt(excerpt_text: str, user_question: str) -> str:
    if SUMMARY_PROVIDER == "python":
        return summarize_with_python(excerpt_text, user_question)
    if SUMMARY_PROVIDER == "ollama":
        return summarize_with_ollama(excerpt_text, user_question)
    raise ValueError(f"Unsupported SUMMARY_PROVIDER={SUMMARY_PROVIDER!r}; expected 'python' or 'ollama'.")

def summarize_search_result_excerpts(tool_json: str, user_question: str) -> str:
    parsed = parse_search_data_for_prompt(tool_json)
    fetched_pages = parsed.get("fetched_pages", [])
    if not isinstance(fetched_pages, list):
        raise ValueError("Search data fetched_pages was not a list before summarization.")

    for page in fetched_pages:
        if not isinstance(page, dict):
            continue
        if not is_prompt_source(page):
            continue
        excerpt = excerpt_body(str(page.get("content") or ""))
        if not excerpt:
            raise ValueError("Cannot summarize empty extracted article excerpt.")
        original_content_chars = len(str(page.get("content") or ""))
        page["content"] = summarize_article_excerpt(excerpt, user_question)
        page["summary_provider"] = SUMMARY_PROVIDER
        page["summary_model"] = SUMMARY_MODEL
        page["summary_original_content_chars"] = str(original_content_chars)
        page["summary_content_chars"] = str(len(page["content"]))

    return json.dumps(parsed, ensure_ascii=False, indent=2)


def is_prompt_source(page: dict[str, Any]) -> bool:
    extractor = str(page.get("extractor") or "")
    return extractor == "trafilatura" or extractor.endswith("-api")


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


def format_decider_elapsed(elapsed_ms: float, decision: str | None = None) -> str:
    if _last_qwen_scores is None:
        if decision:
            return f"[Search decider said {decision} in {elapsed_ms:.0f} ms]"
        return f"[Search decider finished in {elapsed_ms:.0f} ms]"
    search_score, answer_score = _last_qwen_scores
    decision = decision or ("SEARCH" if search_score > answer_score else "ANSWER")
    if prompt_debug_enabled():
        return (
            f"[Search decider said {decision} in {elapsed_ms:.0f} ms, "
            f"Search = {search_score:.3f}, Answer = {answer_score:.3f}]"
        )
    return f"[Search decider said {decision} in {elapsed_ms:.0f} ms]"

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


def decide_with_configured_decider(user_prompt: str) -> tuple[bool, str, str | None]:
    global _last_qwen_scores

    _last_qwen_scores = None
    if SEARCH_DECIDER == "qwen":
        raise ValueError("SEARCH_DECIDER=qwen is obsolete. Use SEARCH_DECIDER=python.")
    if SEARCH_DECIDER == "python":
        return decide_with_qwen(user_prompt, [])
    if SEARCH_DECIDER == "ollama":
        should_search, reason = decide_search_needed(user_prompt, [])
        return should_search, reason, None
    if SEARCH_DECIDER == "always":
        return True, "SEARCH_DECIDER=always", user_prompt
    if SEARCH_DECIDER == "rules":
        return False, "SEARCH_DECIDER=rules has no model decider", None
    raise ValueError(f"Unsupported SEARCH_DECIDER={SEARCH_DECIDER!r}")


def validate_search_query(query: str) -> str:
    cleaned = query.strip().strip('"').strip("'").strip()
    if not cleaned:
        raise RuntimeError("LLM query builder returned empty text.")
    if "\n" in cleaned or "\r" in cleaned:
        raise RuntimeError(f"LLM query builder returned multiple lines: {query!r}")
    if cleaned.startswith("{") or cleaned.startswith("["):
        raise RuntimeError(f"LLM query builder returned structured data: {query!r}")
    if len(cleaned) > 200:
        raise RuntimeError(f"LLM query builder returned an overlong query ({len(cleaned)} chars): {query!r}")
    if re.search(r"\b(query|search query|explanation|here is|sure)\s*:", cleaned, flags=re.I):
        raise RuntimeError(f"LLM query builder returned explanatory text: {query!r}")
    return cleaned


def quoted_spans(text: str) -> list[str]:
    spans = re.findall(r'"([^"\r\n]+)"', text)
    spans.extend(re.findall(r"'([^'\r\n]+)'", text))
    seen: set[str] = set()
    result: list[str] = []
    for span in spans:
        cleaned = span.strip()
        if cleaned and cleaned not in seen:
            seen.add(cleaned)
            result.append(cleaned)
    return result


def restore_user_quotes(user_prompt: str, query: str) -> str:
    restored = query
    for span in sorted(quoted_spans(user_prompt), key=len, reverse=True):
        if f'"{span}"' in restored or f"'{span}'" in restored:
            continue
        pattern = re.compile(rf"(?<![\w\"']){re.escape(span)}(?![\w\"'])")
        restored = pattern.sub(f'"{span}"', restored)
    return restored


def normalize_query_for_ddgs(query: str) -> str:
    """Ensure quotes in query are properly formatted for DDGS."""
    # DDGS expects quoted phrases to work, but let's ensure consistent quote style
    # Convert any mixed quotes to standard double quotes
    query = query.replace("'", '"')
    return query


def derive_search_query(user_prompt: str) -> str:
    messages = [
        {
            "role": "system",
            "content": expand_prompt_placeholders(QUERY_BUILDER_SYSTEM_PROMPT),
        }
    ]
    messages.append({"role": "user", "content": user_prompt})
    content = chat_once(messages, model=DECIDER_MODEL, num_predict=64)
    return restore_user_quotes(user_prompt, validate_search_query(content))


def decide_search_needed(user_prompt: str, history: list[dict[str, str]]) -> tuple[bool, str]:
    messages = [
        {
            "role": "system",
            "content": expand_prompt_placeholders(
                OLLAMA_DECIDER_SYSTEM_PROMPT,
                user_prompt=user_prompt,
            ),
        }
    ]
    content = chat_once(
        messages,
        model=DECIDER_MODEL,
        num_predict=64,
    ).strip()
    label_match = re.search(r"\b(YES|NO)\b", content, flags=re.I)
    if not label_match:
        raise ValueError(f"Ollama search decider returned unexpected text: {content!r}; expected YES or NO.")
    label = label_match.group(1).upper()
    if label == "YES":
        return False, f"ollama decider answered YES: {content}"
    return True, f"ollama decider answered NO: {content}"


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
        if isinstance(page, dict) and is_prompt_source(page)
    ][:5]
    if not fetched_pages:
        raise ValueError("Search produced no usable extracted or API-backed sources.")
    lines = [
        "BEGIN WEB NEWS SEARCH RESULTS",
        "These are fetched article or API-backed sources from a live web search.",
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
        extractor = str(page.get("extractor") or "").strip()
        if extractor:
            lines.append(f"Extractor: {extractor}")
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
    print("/decider <prompt>  Run configured decider and query builder only; bypass rules, search, and LLM.")
    print("/search-off        Disable search and send prompt directly to the LLM.")
    print("/search-on         Enable search and decider logic.")
    print("/llm-off           Skip only the final assistant answer.")
    print("/llm-on            Enable the final assistant answer.")
    print("/prompt-on         Show text sent to the answer/query LLM.")
    print("/prompt-off        Hide text sent to the answer/query LLM.")
    print("/focus-off         Web UI: stop following output while working.")
    print("/focus-on          Web UI: follow output while working.")
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
            if not llm_enabled():
                llm_ms = (time.perf_counter() - llm_start) * 1000
                print(f"[LLM: {llm_ms:.0f} ms, {OLLAMA_MODEL}]")
                print("[LLM: skipped]")
                print()
                return
            try:
                answer = answer_direct(query)
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
            print(format_decider_elapsed(decider_ms, "SEARCH" if should_search else "ANSWER"))
        elif marker:
            print(f"[Search decider skipped; forced search marker = {marker}]")

        if not should_search:
            llm_start = time.perf_counter()
            if not llm_enabled():
                llm_ms = (time.perf_counter() - llm_start) * 1000
                print(f"[LLM: {llm_ms:.0f} ms, {OLLAMA_MODEL}]")
                print("[LLM: skipped]")
                print()
                return
            try:
                answer = answer_from_memory(query, self.history)
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

        query_builder_start = time.perf_counter()
        try:
            search_query = derive_search_query(query)
        except Exception as exc:
            query_builder_ms = (time.perf_counter() - query_builder_start) * 1000
            print(f"[Query builder: {query_builder_ms:.0f} ms, failed]")
            print("[Assistant]")
            print(f"LLM query-builder failed: {exc}")
            print()
            return
        query_builder_ms = (time.perf_counter() - query_builder_start) * 1000
        print(f'[Query builder: {query_builder_ms:.0f} ms, "{search_query}"]')

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

        if SUMMARIZE_EXCERPTS:
            summary_start = time.perf_counter()
            original_chars = len(result)
            result = summarize_search_result_excerpts(result, query)
            summary_ms = (time.perf_counter() - summary_start) * 1000
            print(f"[Summaries: {summary_ms:.0f} ms, {original_chars} -> {len(result)} chars, {SUMMARY_PROVIDER}, {SUMMARY_MODEL}]")

        llm_start = time.perf_counter()
        if not llm_enabled():
            llm_ms = (time.perf_counter() - llm_start) * 1000
            print(f"[LLM: {llm_ms:.0f} ms, {OLLAMA_MODEL}]")
            print("[LLM: skipped]")
            print()
            return
        try:
            answer = answer_from_results(query, result, self.history)
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
        if user_query.lower() == "/focus-off":
            print("[System] Focus follow disabled in the web UI.")
            print()
            return True
        if user_query.lower() == "/focus-on":
            print("[System] Focus follow enabled in the web UI.")
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
                should_search, reason, search_query = decide_with_configured_decider(decider_prompt)
                decider_ms = (time.perf_counter() - start) * 1000
            finally:
                self._reset_context(tokens)
            decision = "SEARCH" if should_search else "ANSWER"
            print(format_decider_elapsed(decider_ms, decision))
            print(f"{decision} | {reason}")
            if should_search:
                query_builder_start = time.perf_counter()
                try:
                    search_query = derive_search_query(decider_prompt)
                except Exception as exc:
                    query_builder_ms = (time.perf_counter() - query_builder_start) * 1000
                    print(f"[Query builder: {query_builder_ms:.0f} ms, failed]")
                    print(f"query-builder failed: {exc}")
                    print()
                    return True
                query_builder_ms = (time.perf_counter() - query_builder_start) * 1000
                print(f'[Query builder: {query_builder_ms:.0f} ms, "{search_query}"]')
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
    if SUMMARIZE_EXCERPTS and SUMMARY_PROVIDER == "python":
        preload_start = time.perf_counter()
        get_python_model(SUMMARY_MODEL)
        preload_ms = (time.perf_counter() - preload_start) * 1000
        print(f"[Summary preload: {preload_ms:.0f} ms, {SUMMARY_PROVIDER}, {SUMMARY_MODEL}]")
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


