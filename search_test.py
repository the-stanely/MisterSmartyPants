from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
import os
import re
import time
from typing import Any
from urllib.parse import urlparse

import requests
import trafilatura
from ddgs import DDGS
from dotenv import load_dotenv
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from websearchMCP import (
    DDGS_NEWS_BACKEND,
    DDGS_REGION,
    DDGS_SAFESEARCH,
    DDGS_TEXT_BACKEND,
    DDGS_TIMELIMIT,
    DDGS_TIMEOUT_SECONDS,
    FETCH_WORKERS,
    RELEVANCY_MODEL,
    SEARCH_NEWS_LIMIT,
    SEARCH_TEXT_LIMIT,
    asks_for_current_info,
    enrich_search_items_for_ranking,
    get_relevancy_model,
    has_stale_year_marker,
    is_probable_ad_url,
    is_root_homepage_url,
    normalize_query_for_ddgs,
)

load_dotenv(override=True)

NEWS_RESULTS = SEARCH_NEWS_LIMIT
TEXT_RESULTS = SEARCH_TEXT_LIMIT
FETCH_TOP_N = 20
FINAL_TOP_N = 5
REQUEST_TIMEOUT_SECONDS = int(os.getenv("REQUEST_TIMEOUT_SECONDS", "20"))

console = Console()


@dataclass
class SearchCandidate:
    mode: str
    title: str
    url: str
    snippet: str
    published: str
    initial_score: float = 0.0


@dataclass
class FetchedArticle:
    candidate: SearchCandidate
    final_url: str
    title: str
    published: str
    author: str
    text: str
    error: str
    fetch_ms: float
    final_score: float = 0.0


def clean_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def result_date(row: dict[str, Any]) -> str:
    for key in ("date", "published", "published_date", "source_date"):
        value = clean_text(row.get(key))
        if value:
            return value
    return ""


def search_result_text(candidate: SearchCandidate) -> str:
    parts = [
        f"Mode: {candidate.mode}",
        f"Title: {candidate.title}",
        f"URL: {candidate.url}",
    ]
    if candidate.published:
        parts.append(f"Published: {candidate.published}")
    if candidate.snippet:
        parts.extend(["", "Snippet:", candidate.snippet])
    return "\n".join(parts)


def article_rank_text(article: FetchedArticle) -> str:
    parts = [
        f"Title: {article.title or article.candidate.title}",
        f"URL: {article.final_url or article.candidate.url}",
    ]
    if article.published or article.candidate.published:
        parts.append(f"Published: {article.published or article.candidate.published}")
    if article.author:
        parts.append(f"Author: {article.author}")
    parts.extend(["", "Text:", article.text])
    return "\n".join(parts)


def search_ddgs(query: str) -> tuple[str, list[tuple[str, dict[str, Any]]], list[SearchCandidate]]:
    effective_query = normalize_query_for_ddgs(query)
    raw: list[tuple[str, dict[str, Any]]] = []
    errors: list[str] = []
    with DDGS(timeout=DDGS_TIMEOUT_SECONDS) as ddgs:
        try:
            raw.extend(
                ("news", row)
                for row in ddgs.news(
                    effective_query,
                    max_results=NEWS_RESULTS,
                    backend=DDGS_NEWS_BACKEND,
                    region=DDGS_REGION,
                    safesearch=DDGS_SAFESEARCH,
                    timelimit=DDGS_TIMELIMIT,
                )
            )
        except Exception as exc:
            errors.append(f"news: {exc}")
        try:
            raw.extend(
                ("text", row)
                for row in ddgs.text(
                    effective_query,
                    max_results=TEXT_RESULTS,
                    backend=DDGS_TEXT_BACKEND,
                    region=DDGS_REGION,
                    safesearch=DDGS_SAFESEARCH,
                    timelimit=DDGS_TIMELIMIT,
                )
            )
        except Exception as exc:
            errors.append(f"text: {exc}")

    seen: set[str] = set()
    candidate_rows: list[dict[str, str]] = []
    for mode, row in raw:
        url = clean_text(row.get("href") or row.get("url"))
        if not url.startswith("http"):
            continue
        normalized = url.split("#", 1)[0]
        if normalized in seen:
            continue
        seen.add(normalized)
        candidate_rows.append(
            {
                "search_mode": mode,
                "title": clean_text(row.get("title") or normalized),
                "url": normalized,
                "snippet": clean_text(row.get("body") or row.get("snippet") or row.get("description")),
                "published": result_date(row),
            }
        )

    enriched_rows = enrich_search_items_for_ranking(candidate_rows)
    candidates = [
        SearchCandidate(
            mode=str(item.get("search_mode") or ""),
            title=clean_text(item.get("title")),
            url=clean_text(item.get("url")),
            snippet=clean_text(item.get("snippet")),
            published=clean_text(item.get("published")),
        )
        for item in enriched_rows
    ]

    if not candidates:
        detail = "; ".join(errors) if errors else "No usable results."
        raise RuntimeError(f"DDGS returned no usable candidates: {detail}")
    return effective_query, raw, candidates


def score_candidates(query: str, candidates: list[SearchCandidate]) -> list[SearchCandidate]:
    model = get_relevancy_model()
    pairs = [(query, search_result_text(candidate)) for candidate in candidates]
    scores = model.predict(pairs)
    for candidate, score in zip(candidates, scores):
        candidate.initial_score = float(score)
    return sorted(candidates, key=lambda item: item.initial_score, reverse=True)

def candidate_as_main_item(candidate: SearchCandidate) -> dict[str, str]:
    return {
        "title": candidate.title,
        "url": candidate.url,
        "snippet": candidate.snippet,
        "published": candidate.published,
        "search_mode": candidate.mode,
    }


def reject_reason(query: str, candidate: SearchCandidate) -> str | None:
    item = candidate_as_main_item(candidate)
    if is_probable_ad_url(candidate.url):
        return "probable ad/tracking URL"
    if is_root_homepage_url(candidate.url):
        return "root homepage URL"
    if asks_for_current_info(query) and has_stale_year_marker(query, item):
        return "stale year marker for current-info query"
    if asks_for_current_info(query) and "youtube.com" in candidate.url.lower():
        return "YouTube result for current-info query"
    return None


def apply_main_rejecter(query: str, candidates: list[SearchCandidate]) -> tuple[list[SearchCandidate], list[tuple[SearchCandidate, str]]]:
    kept: list[SearchCandidate] = []
    rejected: list[tuple[SearchCandidate, str]] = []
    for candidate in candidates:
        reason = reject_reason(query, candidate)
        if reason:
            rejected.append((candidate, reason))
        else:
            kept.append(candidate)
    return kept, rejected


def print_rejected(rejected: list[tuple[SearchCandidate, str]]) -> None:
    if not rejected:
        console.print("Main rejecter removed 0 search candidates.")
        return
    table = Table(title=f"Main rejecter removed {len(rejected)} search candidates", show_lines=True)
    table.add_column("#", justify="right")
    table.add_column("Mode")
    table.add_column("Reason")
    table.add_column("Title")
    table.add_column("URL")
    table.add_column("Date")
    for index, (candidate, reason) in enumerate(rejected, start=1):
        table.add_row(str(index), candidate.mode, reason, candidate.title, candidate.url, candidate.published)
    console.print(table)


def extract_full_article(html: str, url: str) -> dict[str, str]:
    extracted = trafilatura.extract(
        html,
        url=url,
        output_format="json",
        include_comments=False,
        include_tables=False,
        with_metadata=True,
        favor_recall=True,
    )
    if not extracted:
        raise ValueError("Trafilatura returned no article text.")

    import json

    obj = json.loads(extracted)
    text = str(obj.get("text") or obj.get("raw_text") or "").strip()
    if not text:
        raise ValueError("Trafilatura returned empty article text.")
    return {
        "title": clean_text(obj.get("title")),
        "published": clean_text(obj.get("date")),
        "author": clean_text(obj.get("author")),
        "text": text,
    }


def fetch_article(candidate: SearchCandidate) -> FetchedArticle:
    start = time.perf_counter()
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
        )
    }
    try:
        response = requests.get(candidate.url, headers=headers, timeout=REQUEST_TIMEOUT_SECONDS, allow_redirects=True)
        content_type = (response.headers.get("content-type") or "").lower()
        if response.status_code >= 400:
            raise RuntimeError(f"HTTP {response.status_code}")
        if "text/html" not in content_type and "application/xhtml+xml" not in content_type:
            raise RuntimeError(f"Unsupported content-type {content_type or 'unknown'}")
        extracted = extract_full_article(response.text, response.url or candidate.url)
        return FetchedArticle(
            candidate=candidate,
            final_url=response.url or candidate.url,
            title=extracted["title"] or candidate.title,
            published=extracted["published"] or candidate.published,
            author=extracted["author"],
            text=extracted["text"],
            error="",
            fetch_ms=(time.perf_counter() - start) * 1000,
        )
    except Exception as exc:
        return FetchedArticle(
            candidate=candidate,
            final_url=candidate.url,
            title=candidate.title,
            published=candidate.published,
            author="",
            text="",
            error=str(exc),
            fetch_ms=(time.perf_counter() - start) * 1000,
        )


def fetch_top(candidates: list[SearchCandidate]) -> list[FetchedArticle]:
    workers = max(1, FETCH_WORKERS)
    with ThreadPoolExecutor(max_workers=min(workers, len(candidates))) as executor:
        return list(executor.map(fetch_article, candidates))

def article_as_main_item(article: FetchedArticle) -> dict[str, str]:
    return {
        "title": article.title or article.candidate.title,
        "url": article.final_url or article.candidate.url,
        "snippet": article.text or article.candidate.snippet,
        "published": article.published or article.candidate.published,
        "search_mode": article.candidate.mode,
    }


def post_trafilatura_reject_reason(query: str, article: FetchedArticle) -> str | None:
    item = article_as_main_item(article)
    if article.error:
        return f"fetch/extraction error: {article.error}"
    if not article.text.strip():
        return "empty Trafilatura text"
    if is_probable_ad_url(article.final_url):
        return "probable ad/tracking URL after redirect"
    if is_root_homepage_url(article.final_url):
        return "root homepage URL after redirect"
    host = urlparse(article.final_url).netloc.lower()
    is_github_result = host == "github.com" or host.endswith(".github.com")
    if asks_for_current_info(query) and not is_github_result and has_stale_year_marker(query, item):
        return "stale year marker after extraction"
    if asks_for_current_info(query) and "youtube.com" in article.final_url.lower():
        return "YouTube result for current-info query"
    return None


def fetch_until_post_reject_done(
    query: str,
    ranked_candidates: list[SearchCandidate],
) -> tuple[list[FetchedArticle], list[tuple[FetchedArticle, str]], int]:
    kept: list[FetchedArticle] = []
    rejected: list[tuple[FetchedArticle, str]] = []
    attempts = 0
    workers = max(1, FETCH_WORKERS)

    for start in range(0, len(ranked_candidates), workers):
        if len(kept) >= FETCH_TOP_N:
            break
        batch = ranked_candidates[start:start + workers]
        fetched = fetch_top(batch)
        attempts += len(fetched)
        for article in fetched:
            reason = post_trafilatura_reject_reason(query, article)
            if reason:
                rejected.append((article, reason))
                continue
            kept.append(article)
            if len(kept) >= FETCH_TOP_N:
                break

    return kept[:FETCH_TOP_N], rejected, attempts


def print_post_rejected(rejected: list[tuple[FetchedArticle, str]]) -> None:
    if not rejected:
        console.print("Post-Trafilatura rejecter removed 0 fetched articles.")
        return
    table = Table(title=f"Post-Trafilatura rejecter removed {len(rejected)} fetched articles", show_lines=True)
    table.add_column("#", justify="right")
    table.add_column("Initial", justify="right")
    table.add_column("Mode")
    table.add_column("Reason")
    table.add_column("Title")
    table.add_column("URL")
    table.add_column("Chars", justify="right")
    for index, (article, reason) in enumerate(rejected, start=1):
        table.add_row(
            str(index),
            f"{article.candidate.initial_score:.3f}",
            article.candidate.mode,
            reason,
            article.title or article.candidate.title,
            article.final_url or article.candidate.url,
            str(len(article.text)),
        )
    console.print(table)


def score_articles(query: str, articles: list[FetchedArticle]) -> list[FetchedArticle]:
    usable = [article for article in articles if article.text and not article.error]
    if not usable:
        return []
    model = get_relevancy_model()
    pairs = [(query, article_rank_text(article)) for article in usable]
    scores = model.predict(pairs)
    for article, score in zip(usable, scores):
        article.final_score = float(score)
    return sorted(usable, key=lambda item: item.final_score, reverse=True)


def print_search_table(candidates: list[SearchCandidate]) -> None:
    table = Table(title="Initial cross-encoder ranking of DDGS results", show_lines=True)
    table.add_column("Rank", justify="right")
    table.add_column("Score", justify="right")
    table.add_column("Mode")
    table.add_column("Title")
    table.add_column("URL")
    table.add_column("Date")
    for index, item in enumerate(candidates, start=1):
        table.add_row(str(index), f"{item.initial_score:.3f}", item.mode, item.title, item.url, item.published)
    console.print(table)


def print_raw_ddgs_results(raw_results: list[tuple[str, dict[str, Any]]]) -> None:
    """Display unfiltered raw DDGS response data."""
    console.rule(f"Raw DDGS results ({len(raw_results)} items)")
    for index, (mode, row) in enumerate(raw_results, start=1):
        lines = [
            f"Mode: {mode}",
        ]
        if isinstance(row, dict):
            for key in ("title", "href", "url", "date", "published", "published_date", "body", "snippet", "description", "source"):
                if key in row and row.get(key):
                    value = str(row[key])
                    if len(value) > 200:
                        value = value[:200] + "..."
                    lines.append(f"{key}: {value}")
        else:
            lines.append(str(row))
        console.print(Panel("\n".join(lines), title=f"Result {index}", expand=False))


def print_fetches(articles: list[FetchedArticle]) -> None:
    console.rule("Up to 20 articles kept after post-Trafilatura rejecter")
    for index, article in enumerate(articles, start=1):
        status = "OK" if article.text and not article.error else f"ERROR: {article.error}"
        header = (
            f"Fetch {index} | initial score {article.candidate.initial_score:.3f} | "
            f"{article.fetch_ms:.0f} ms | {status}"
        )
        body = [
            f"Mode: {article.candidate.mode}",
            f"Search title: {article.candidate.title}",
            f"Article title: {article.title}",
            f"URL: {article.final_url}",
            f"Published: {article.published}",
            f"Author: {article.author}",
            f"Extracted chars: {len(article.text)}",
        ]
        if article.candidate.snippet:
            body.extend(["", "Search snippet:", article.candidate.snippet])
        if article.text:
            body.extend(["", "Full extracted text:", article.text])
        console.print(Panel("\n".join(body), title=header, expand=False))


def print_top_picks(articles: list[FetchedArticle]) -> None:
    console.rule("Top 5 after fetch + Trafilatura + second cross-encoder ranking")
    for index, article in enumerate(articles[:FINAL_TOP_N], start=1):
        body = [
            f"Final score: {article.final_score:.3f}",
            f"Initial score: {article.candidate.initial_score:.3f}",
            f"Mode: {article.candidate.mode}",
            f"Title: {article.title}",
            f"URL: {article.final_url}",
            f"Published: {article.published}",
            f"Author: {article.author}",
            f"Extracted chars: {len(article.text)}",
            "",
            "Full extracted text:",
            article.text,
        ]
        console.print(Panel("\n".join(body), title=f"Top pick {index}", expand=False))


def run_once(query: str) -> None:
    console.rule(f"DDGS search: {query}")
    started = time.perf_counter()
    effective_query, raw_results, candidates = search_ddgs(query)
    console.print(f"Effective DDGS query: {effective_query}")
    console.print(
        f"DDGS options: text_backend={DDGS_TEXT_BACKEND}, news_backend={DDGS_NEWS_BACKEND}, "
        f"region={DDGS_REGION}, safesearch={DDGS_SAFESEARCH}, timelimit={DDGS_TIMELIMIT or 'none'}"
    )
    news_count = sum(1 for item in candidates if item.mode == "news")
    text_count = sum(1 for item in candidates if item.mode == "text")
    console.print(f"DDGS candidates: {len(candidates)} total ({news_count} news, {text_count} text)")
    
    # Display raw DDGS output first
    print_raw_ddgs_results(raw_results)

    ranked_candidates = score_candidates(query, candidates)
    print_search_table(ranked_candidates)

    fetch_started = time.perf_counter()
    fetched, rejected, attempts = fetch_until_post_reject_done(query, ranked_candidates)
    console.print(
        f"Fetched {attempts} ranked candidates in {(time.perf_counter() - fetch_started) * 1000:.0f} ms; "
        f"kept {len(fetched)} after post-Trafilatura rejecter"
    )
    print_post_rejected(rejected)
    print_fetches(fetched)

    final_ranked = score_articles(query, fetched)
    print_top_picks(final_ranked)
    console.print(f"Total elapsed: {(time.perf_counter() - started) * 1000:.0f} ms")


def main() -> None:
    console.print("DDGS/cross-encoder search experiment. Type a Google-style query, or q to quit.")
    while True:
        try:
            query = input("search_test> ").strip()
        except (EOFError, KeyboardInterrupt):
            console.print()
            return
        if not query:
            continue
        if query.lower() in {"q", "quit", "exit"}:
            return
        try:
            run_once(query)
        except Exception as exc:
            console.print(f"[red]Error:[/red] {type(exc).__name__}: {exc}")


if __name__ == "__main__":
    main()