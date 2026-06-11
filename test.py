from __future__ import annotations

import json
import os

from dotenv import load_dotenv
import requests

from ddgs import DDGS

load_dotenv(override=True)


def ddgs_text_search(query: str) -> list[dict]:
    """Search via DDGS text mode."""
    with DDGS(timeout=20) as ddgs:
        return ddgs.text(query, max_results=5, backend="auto")


def github_user_search(query: str) -> dict:
    """Search GitHub users via API."""
    try:
        resp = requests.get(
            "https://api.github.com/search/users",
            params={"q": query, "per_page": 5, "sort": "followers", "order": "desc"},
            timeout=20,
        )
        resp.raise_for_status()
        return resp.json()
    except Exception as exc:
        return {"error": str(exc)}


def github_repo_search(query: str) -> dict:
    """Search GitHub repositories via API."""
    try:
        resp = requests.get(
            "https://api.github.com/search/repositories",
            params={"q": query, "per_page": 5, "sort": "stars", "order": "desc"},
            timeout=20,
        )
        resp.raise_for_status()
        return resp.json()
    except Exception as exc:
        return {"error": str(exc)}


def wikipedia_search(query: str) -> dict:
    """Search Wikipedia via API."""
    try:
        resp = requests.get(
            "https://en.wikipedia.org/w/api.php",
            params={"action": "query", "list": "search", "srsearch": query, "srwhat": "text", "format": "json", "srlimit": 5},
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=20,
        )
        resp.raise_for_status()
        return resp.json()
    except Exception as exc:
        return {"error": str(exc)}


def arxiv_search(query: str) -> dict:
    """Search arXiv via API."""
    try:
        resp = requests.get(
            "http://export.arxiv.org/api/query",
            params={"search_query": f"all:{query}", "start": 0, "max_results": 5, "sortBy": "submittedDate", "sortOrder": "descending"},
            timeout=20,
        )
        resp.raise_for_status()
        # Parse Atom XML response
        import xml.etree.ElementTree as ET
        root = ET.fromstring(resp.content)
        ns = {"atom": "http://www.w3.org/2005/Atom"}
        entries = root.findall("atom:entry", ns)
        results = []
        for entry in entries:
            title_elem = entry.find("atom:title", ns)
            summary_elem = entry.find("atom:summary", ns)
            id_elem = entry.find("atom:id", ns)
            results.append({
                "title": (title_elem.text or "").strip() if title_elem is not None else "",
                "summary": (summary_elem.text or "").strip() if summary_elem is not None else "",
                "id": (id_elem.text or "").strip() if id_elem is not None else "",
            })
        return {"entries": results, "count": len(results)}
    except Exception as exc:
        return {"error": str(exc)}


def stackexchange_search(query: str) -> dict:
    """Search Stack Exchange (Stack Overflow) via API."""
    try:
        resp = requests.get(
            "https://api.stackexchange.com/2.3/search/advanced",
            params={"q": query, "site": "stackoverflow", "sort": "votes", "order": "desc", "pagesize": 5},
            timeout=20,
        )
        resp.raise_for_status()
        return resp.json()
    except Exception as exc:
        return {"error": str(exc)}


def archive_org_search(query: str) -> dict:
    """Search Internet Archive via Advanced Search API."""
    try:
        resp = requests.get(
            "https://archive.org/advancedsearch.php",
            params={
                "q": query,
                "output": "json",
                "rows": 10,
                "page": 1,
                "fl[]": ["identifier", "title", "description", "date", "creator", "format"],
            },
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
            },
            timeout=20,
        )
        resp.raise_for_status()
        return resp.json()
    except Exception as exc:
        return {"error": str(exc)}


def show_menu() -> int:
    """Display endpoint menu and return selection."""
    print("\n" + "=" * 70)
    print("API Search Test Menu")
    print("=" * 70)
    print("1. DDGS (DuckDuckGo)")
    print("2. GitHub Users")
    print("3. GitHub Repositories")
    print("4. Wikipedia")
    print("5. arXiv")
    print("6. Stack Exchange (Stack Overflow)")
    print("7. Internet Archive")
    print("0. Exit")
    print("=" * 70)
    
    while True:
        choice = input("Select endpoint (0-7): ").strip()
        if choice in "01234567":
            return int(choice)
        print("Invalid choice. Please enter 0-7.")


def main() -> None:
    endpoints = {
        1: ("DDGS Text", ddgs_text_search),
        2: ("GitHub Users", github_user_search),
        3: ("GitHub Repositories", github_repo_search),
        4: ("Wikipedia", wikipedia_search),
        5: ("arXiv", arxiv_search),
        6: ("Stack Exchange", stackexchange_search),
        7: ("Internet Archive", archive_org_search),
    }
    
    while True:
        choice = show_menu()
        if choice == 0:
            print("Exiting.")
            break
        
        if choice not in endpoints:
            continue
        
        endpoint_name, endpoint_func = endpoints[choice]
        query = input(f"\nEnter search query for {endpoint_name}: ").strip()
        if not query:
            print("No query provided.")
            continue
        
        print(f"\nSearching {endpoint_name} for: {query!r}")
        print("-" * 70)
        
        try:
            results = endpoint_func(query)
            print(json.dumps(results, ensure_ascii=False, indent=2))
        except Exception as exc:
            print(f"Error: {exc}")
        
        print()


if __name__ == "__main__":
    main()
