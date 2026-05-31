from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from html import unescape
from typing import Any

import requests
from ddgs import DDGS

try:
    from dotenv import load_dotenv
    load_dotenv(override=True)
except Exception:
    pass

OLLAMA_API = os.getenv("OLLAMA_API", "http://localhost:11434/api/chat")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "cow/gemma2_tools")
OLLAMA_TIMEOUT_SECONDS = int(os.getenv("OLLAMA_TIMEOUT_SECONDS", "300"))
OLLAMA_NUM_CTX = int(os.getenv("OLLAMA_NUM_CTX", "32768"))
OLLAMA_TEMPERATURE = float(os.getenv("OLLAMA_TEMPERATURE", "0.2"))
OLLAMA_TOP_P = float(os.getenv("OLLAMA_TOP_P", "0.9"))
OLLAMA_NUM_PREDICT = int(os.getenv("OLLAMA_NUM_PREDICT", "512"))
QUESTION = os.getenv("QUESTION", "Wall street biggest movers.")
SEARCH_LIMIT = 12
FETCH_TOP_N = 3
FETCH_MAX_CHARS = 12000
FETCH_SCAN_LIMIT = 12
REQUEST_TIMEOUT_SECONDS = int(os.getenv("REQUEST_TIMEOUT_SECONDS", "20"))
DEBUG = False

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


def html_to_text(html: str, max_chars: int) -> str:
    no_script = re.sub(r"<script\b[^<]*(?:(?!</script>)<[^<]*)*</script>", " ", html, flags=re.I | re.S)
    no_style = re.sub(r"<style\b[^<]*(?:(?!</style>)<[^<]*)*</style>", " ", no_script, flags=re.I | re.S)
    body = re.sub(r"<[^>]+>", " ", no_style)
    text = unescape(body)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:max_chars]


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

        html = resp.text
        title_match = re.search(r"<title[^>]*>(.*?)</title>", html, flags=re.I | re.S)
        title = re.sub(r"\s+", " ", unescape(title_match.group(1))).strip() if title_match else url
        content = html_to_text(html, max_chars=max_chars)
        return {"url": resp.url or url, "title": title or url, "content": content}
    except Exception as exc:
        return {"url": url, "title": url, "content": f"Fetch error: {exc}"}


def run_search(query: str, search_limit: int, fetch_top_n: int, fetch_scan_limit: int, fetch_max_chars: int) -> str:
    try:
        with DDGS() as ddgs:
            raw = list(ddgs.text(query, max_results=search_limit))
    except Exception as exc:
        return f"Search failed: {exc}"

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
    for item in search_items[:fetch_scan_limit]:
        if len(fetched_good) >= fetch_top_n:
            break
        page = fetch_url_content(item["url"], fetch_max_chars)
        content = page.get("content", "")
        if content.startswith("Fetch error:"):
            fetch_debug.append(
                {
                    "url": item["url"],
                    "status": "skip",
                    "reason": content,
                }
            )
            continue
        ok, reason = fetched_page_quality(page)
        if ok:
            fetched_good.append(page)
            fetch_debug.append({"url": item["url"], "status": "keep", "reason": reason})
        else:
            fetched_fallback.append(page)
            fetch_debug.append({"url": item["url"], "status": "fallback", "reason": reason})

    fetched_pages = list(fetched_good)
    if len(fetched_pages) < fetch_top_n:
        needed = fetch_top_n - len(fetched_pages)
        fetched_pages.extend(fetched_fallback[:needed])

    payload = {"search_results": search_items, "fetched_pages": fetched_pages, "fetch_debug": fetch_debug}
    return json.dumps(payload, ensure_ascii=False, indent=2)


def chat_once(messages: list[dict[str, str]]) -> str:
    payload = {
        "model": OLLAMA_MODEL,
        "messages": messages,
        "stream": False,
        "options": {
            "num_ctx": OLLAMA_NUM_CTX,
            "temperature": OLLAMA_TEMPERATURE,
            "top_p": OLLAMA_TOP_P,
            "num_predict": OLLAMA_NUM_PREDICT,
        },
    }
    response = requests.post(OLLAMA_API, json=payload, timeout=OLLAMA_TIMEOUT_SECONDS)
    response.raise_for_status()
    obj = response.json()
    return ((obj.get("message") or {}).get("content") or "").strip()


def derive_search_query(user_prompt: str, history: list[dict[str, str]]) -> str:
    messages = [
        {
            "role": "system",
            "content": (
                "Convert the user request into a concise web search query. "
                "Use prior chat context if helpful. "
                "Return only the query text, no quotes, no JSON, no explanation."
            ),
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
    prompt_low = user_prompt.lower()
    force_search_markers = [
        "latest",
        "today",
        "yesterday",
        "current",
        "news",
        "score",
        "odds",
        "price",
        "stock",
        "weather",
        "who won",
        "what happened",
        "search",
        "look up",
        "find",
    ]
    if any(m in prompt_low for m in force_search_markers):
        return True, "time-sensitive or explicit lookup request"

    messages = [
        {
            "role": "system",
            "content": (
                "Decide if web search is required to answer the user's latest request. "
                "Use prior chat context if relevant. "
                "For anything time-sensitive, recent, or uncertain, choose SEARCH. "
                "Return exactly one line in this format: DECISION|REASON. "
                "DECISION must be either SEARCH or ANSWER. "
                "If unsure, choose SEARCH."
            ),
        }
    ]
    messages.extend(history)
    messages.append({"role": "user", "content": user_prompt})
    content = chat_once(messages).strip()
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


def answer_from_results(user_prompt: str, tool_json: str, history: list[dict[str, str]]) -> str:
    messages = [
        {
            "role": "system",
            "content": (
                "Answer the user using only the provided web search data. "
                "Use prior chat context if relevant. "
                "If evidence conflicts, say that clearly and mention source links. "
                "Be concise."
            ),
        }
    ]
    messages.extend(history)
    messages.append({"role": "user", "content": user_prompt})
    messages.append({"role": "user", "content": f"Web search data:\n{tool_json}"})
    return chat_once(messages)


def answer_from_memory(user_prompt: str, history: list[dict[str, str]]) -> str:
    messages = [
        {
            "role": "system",
            "content": (
                "Answer directly from general knowledge and prior chat context only. "
                "Do not claim web verification. Be concise."
            ),
        }
    ]
    messages.extend(history)
    messages.append({"role": "user", "content": user_prompt})
    return chat_once(messages)


def parse_args():
    parser = argparse.ArgumentParser(description="Run DDGS web search/fetch pipeline in debug mode.")
    parser.add_argument("query", nargs="*", help="Search query text.")
    parser.add_argument("--once", action="store_true", help="Run once and exit.")
    return parser.parse_args()


def main():
    args = parse_args()
    search_limit = SEARCH_LIMIT
    fetch_top_n = FETCH_TOP_N
    fetch_scan_limit = FETCH_SCAN_LIMIT
    fetch_max_chars = FETCH_MAX_CHARS

    history: list[dict[str, str]] = []

    def run_query(query: str):
        try:
            should_search, decision_reason = decide_search_needed(query, history)
        except Exception as exc:
            print("[Assistant]")
            print(f"LLM search-decision failed: {exc}")
            print()
            return

        if not should_search:
            llm_start = time.perf_counter()
            try:
                answer = answer_from_memory(query, history)
            except Exception as exc:
                llm_ms = (time.perf_counter() - llm_start) * 1000
                print(f"[LLM: {llm_ms:.0f} ms]")
                print("[Assistant]")
                print(f"LLM answer failed: {exc}")
                print()
                return
            llm_ms = (time.perf_counter() - llm_start) * 1000
            print(f"[LLM: {llm_ms:.0f} ms]")
            print("[Assistant]")
            print(answer)
            print()
            history.append({"role": "user", "content": query})
            history.append({"role": "assistant", "content": answer})
            return

        try:
            search_query = derive_search_query(query, history)
        except Exception as exc:
            print("[Assistant]")
            print(f"LLM query-builder failed: {exc}")
            print()
            return

        search_start = time.perf_counter()
        result = run_search(
            query=search_query,
            search_limit=search_limit,
            fetch_top_n=fetch_top_n,
            fetch_scan_limit=fetch_scan_limit,
            fetch_max_chars=fetch_max_chars,
        )
        search_ms = (time.perf_counter() - search_start) * 1000
        print(f"[Search: {search_ms:.0f} ms]")

        if DEBUG:
            print(f"[Tool] web_search query: {search_query}")
            print(f"[Tool] result: {result}\n")

        llm_start = time.perf_counter()
        try:
            answer = answer_from_results(query, result, history)
        except Exception as exc:
            llm_ms = (time.perf_counter() - llm_start) * 1000
            print(f"[LLM: {llm_ms:.0f} ms]")
            print("[Assistant]")
            print(f"LLM answer failed: {exc}")
            print()
            return

        llm_ms = (time.perf_counter() - llm_start) * 1000
        print(f"[LLM: {llm_ms:.0f} ms]")
        print("[Assistant]")
        print(answer)
        print()
        history.append({"role": "user", "content": query})
        history.append({"role": "assistant", "content": answer})

    initial_query = (" ".join(args.query).strip() if args.query else "")
    if args.once:
        if not initial_query:
            initial_query = QUESTION.strip()
        if not initial_query:
            print("QUESTION is empty.")
            raise SystemExit(1)
        run_query(initial_query)
        raise SystemExit(0)

    while True:
        try:
            user_query = input("AI ready> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nExiting.")
            break

        if not user_query:
            continue
        if user_query.lower() == "/new":
            history.clear()
            print("[System] Context cleared.")
            print()
            continue
        if user_query.lower() in {"quit", "exit", "q"}:
            print("Exiting.")
            break

        run_query(user_query)


if __name__ == "__main__":
    main()



