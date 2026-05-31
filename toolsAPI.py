import requests
import json
import re

OLLAMA_API = "http://localhost:11434/api/chat"
MODEL = "cow/gemma2_tools"
QUESTION = "What's the latest news about Model Context Protocol servers?"


def web_search(query: str):
    lines = []
    try:
        response = requests.get(
            "https://api.gdeltproject.org/api/v2/doc/doc",
            params={
                "query": query,
                "mode": "ArtList",
                "maxrecords": 5,
                "format": "json",
                "sort": "DateDesc",
            },
            timeout=15,
        )
        if response.status_code == 200:
            data = response.json()
            articles = data.get("articles", [])
            if isinstance(articles, list):
                for article in articles[:3]:
                    title = (article.get("title") or "").strip()
                    url = (article.get("url") or "").strip()
                    source = (article.get("sourcecountry") or "").strip()
                    date = (article.get("seendate") or "").strip()
                    summary = (article.get("socialimage") or "").strip()

                    if title or url:
                        meta = ", ".join([x for x in [date, source] if x])
                        extra = f" [{meta}]" if meta else ""
                        lines.append(f"{title}{extra} ({url})")
                    elif summary:
                        lines.append(summary)
    except requests.RequestException:
        pass

    gdelt_result = "\n".join(lines).strip()
    if gdelt_result:
        return gdelt_result

    # Fallback for sparse/non-news topics.
    headers = {
        "User-Agent": "toolsAPI/1.0 (local script; educational use)",
        "Accept": "application/json",
    }
    try:
        search_resp = requests.get(
            "https://en.wikipedia.org/w/api.php",
            params={
                "action": "query",
                "list": "search",
                "srsearch": query,
                "format": "json",
                "srlimit": 3,
            },
            headers=headers,
            timeout=30,
        )
        if search_resp.status_code != 200:
            return ""
        data = search_resp.json()
    except requests.RequestException:
        return ""

    search_items = data.get("query", {}).get("search", [])
    if not search_items:
        return ""

    lines = []
    for item in search_items[:3]:
        title = (item.get("title") or "").strip()
        if not title:
            continue

        try:
            summary_resp = requests.get(
                f"https://en.wikipedia.org/api/rest_v1/page/summary/{title.replace(' ', '_')}",
                headers=headers,
                timeout=30,
            )
            if summary_resp.status_code != 200:
                continue
            summary = summary_resp.json()
        except requests.RequestException:
            continue
        extract = (summary.get("extract") or "").strip()
        page_url = summary.get("content_urls", {}).get("desktop", {}).get("page", "")
        if extract:
            lines.append(f"{title} - {extract} ({page_url})")

    return "\n".join(lines).strip()
# Define tools
tools = [
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": "Search the web for live information",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"}
                },
                "required": ["query"]
            }
        }
    }
]


def chat_once(messages, include_tools=True):
    payload = {
        "model": MODEL,
        "messages": messages,
        "stream": False,
    }
    if include_tools:
        payload["tools"] = tools

    response = requests.post(OLLAMA_API, json=payload, timeout=120)
    response.raise_for_status()
    return response.json()


def looks_like_refusal(text):
    if not text:
        return False
    t = text.lower()
    flags = [
        "i don't have",
        "i do not have",
        "has not yet occurred",
        "has not occurred yet",
        "knowledge cutoff",
    ]
    return any(f in t for f in flags)


def parse_text_tool_call(text):
    if not text:
        return None

    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.removeprefix("```json").removeprefix("```").removesuffix("```").strip()

    # If the model wrapped JSON in extra text, extract the first object-like block.
    if "{" in cleaned and "}" in cleaned:
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        cleaned = cleaned[start:end + 1]

    try:
        obj = json.loads(cleaned)
    except json.JSONDecodeError:
        value_match = re.search(r'"value"\s*:\s*"([^"]+)"', cleaned)
        if value_match:
            return value_match.group(1).strip()

        query_match = re.search(r'"query"\s*:\s*"([^"]+)"', cleaned)
        if query_match:
            return query_match.group(1).strip()

        query_word_match = re.search(r'query[^a-zA-Z0-9]+([a-zA-Z0-9][^"}]+)', cleaned, re.IGNORECASE)
        if query_word_match:
            return query_word_match.group(1).strip()

        return None

    tool_name = str(obj.get("name", "")).strip().lower()
    valid_names = {"web_search", "search the web", "web search"}
    is_search_alias = "search" in tool_name and "web" in tool_name
    if tool_name and tool_name not in valid_names and not is_search_alias:
        return None

    params = obj.get("parameters", obj)
    if not isinstance(params, dict):
        return None

    query = params.get("query")
    if isinstance(query, dict):
        query = query.get("value")

    if not isinstance(query, str) or not query.strip():
        return None

    return query.strip()


def normalize_query(value):
    if isinstance(value, str):
        v = value.strip()
        return v or None
    if isinstance(value, dict):
        nested = value.get("value") or value.get("query")
        if isinstance(nested, str):
            v = nested.strip()
            return v or None
    return None


messages = [
    {"role": "user", "content": QUESTION}
]

# First pass: ask model with tools available.
first = chat_once(messages, include_tools=True)
assistant_msg = first.get("message", {})
assistant_content = assistant_msg.get("content", "")
tool_calls = assistant_msg.get("tool_calls", [])

query = None
if tool_calls:
    for tool_call in tool_calls:
        func = tool_call.get("function", {})
        if func.get("name") == "web_search":
            args = func.get("arguments", {})
            if isinstance(args, str):
                args = json.loads(args)
            query = normalize_query(args.get("query"))
            break

if not query:
    query = normalize_query(parse_text_tool_call(assistant_content))

if query:
    result = web_search(query)
    if not result:
        # Retry with sports-specific hints.
        retry_query = f"{query} January 2026 winner Ohio State Notre Dame"
        result = web_search(retry_query)
        query = retry_query if result else query

    print(f"[Tool] web_search query: {query}")
    print(f"[Tool] result: {result}\n")

    messages.append(
        {
            "role": "system",
            "content": "Use tool output as the source of truth. If tool output is empty, say that clearly.",
        }
    )
    messages.append(assistant_msg)
    messages.append(
        {
            "role": "tool",
            "name": "web_search",
            "content": result or f"No search result found for query: {query}",
        }
    )

    if not result:
        print("[Assistant]")
        print(f"No tool result returned for query: {query}")
        raise SystemExit(0)

    # Second pass: ask model to synthesize a user-facing answer from tool output.
    second = chat_once(messages, include_tools=False)
    final_content = second.get("message", {}).get("content", "").strip()

    if final_content:
        print("[Assistant]")
        if looks_like_refusal(final_content) and result:
            print(f"Based on tool output: {result}")
        else:
            print(final_content)
    else:
        if result:
            print(f"Based on tool output: {result}")
        else:
            print("No assistant text returned on second pass.")
else:
    # No tool call; print normal assistant output if present.
    if assistant_content.strip():
        print("[Assistant]")
        print(assistant_content.strip())
    else:
        print("No assistant text or tool call returned.")
