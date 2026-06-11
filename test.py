from __future__ import annotations

import json

from ddgs import DDGS


def main() -> None:
    query = input("Search query: ").strip()
    if not query:
        print("No query provided.")
        return

    try:
        with DDGS(timeout=20) as ddgs:
            results = ddgs.text(query, max_results=5, backend="duckduckgo")
    except Exception as exc:
        print(f"Search failed: {exc}")
        return

    if not results:
        print("No results found.")
        return

    for index, row in enumerate(results[:5], start=1):
        print(f"Result {index}")
        if isinstance(row, dict):
            print(json.dumps(row, ensure_ascii=False, indent=2))
        else:
            print(str(row))
        print()


if __name__ == "__main__":
    main()
