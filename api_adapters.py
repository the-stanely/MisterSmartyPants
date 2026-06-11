"""API adapters for structured content extraction from major platforms.

This module provides specialized content extraction adapters for high-value sources:
- Wikipedia: MediaWiki API for articles
- arXiv: arXiv API for research papers  
- Stack Exchange: Stack Exchange API for Q&A posts (Stack Overflow, etc.)
- Hacker News: HN API for stories and comments

Architecture:
1. route_to_api_adapter(url) checks the URL domain and calls the appropriate adapter
2. Each adapter normalizes its payload to: {url, title, published, author, content, extractor}
3. Integrated into websearchMCP.fetch_url_content() before Trafilatura fallback

Priority order in router:
  fetch_wikipedia → fetch_arxiv → fetch_stackexchange → fetch_hackernews

Fallback: If all adapters return None, websearchMCP uses GitHub API (if applicable) or Trafilatura.

Example:
  from api_adapters import route_to_api_adapter
  result = route_to_api_adapter("https://en.wikipedia.org/wiki/Python_(programming_language)")
  # Returns: {url: "...", title: "Python (programming language)", content: "...", extractor: "wikipedia-api"}
"""
from __future__ import annotations

import json
import os
import re
from typing import Any
from urllib.parse import urlparse, parse_qs
import requests


REQUEST_TIMEOUT = 20
DEFAULT_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"


def fetch_wikipedia(url: str) -> dict[str, str] | None:
    """Fetch Wikipedia article via MediaWiki API."""
    parsed = urlparse(url)
    if "wikipedia.org" not in parsed.netloc:
        return None

    # Extract page title from URL
    path = parsed.path.strip("/")
    if not path.startswith("wiki/"):
        return None

    page_title = path[5:]  # Remove "wiki/" prefix
    if not page_title:
        return None

    try:
        # Infer language from domain
        lang = parsed.netloc.split(".")[0] if "." in parsed.netloc else "en"
        api_url = f"https://{lang}.wikipedia.org/w/api.php"
        
        # Wikipedia requires a User-Agent
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
        }
        
        resp = requests.get(
            api_url,
            headers=headers,
            params={
                "action": "query",
                "titles": page_title,
                "prop": "extracts|info",
                "explaintext": True,
                "format": "json",
                "redirects": 1,
                "inprop": "url|displaytitle",
            },
            timeout=REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()

        pages = data.get("query", {}).get("pages", {})
        if not pages:
            return None

        page_id = list(pages.keys())[0]
        page = pages[page_id]

        if "missing" in page:
            return None

        title = page.get("title") or page_title
        extract = page.get("extract") or ""
        canonical_url = page.get("canonicalurl") or url

        if not extract:
            return None

        return {
            "url": canonical_url,
            "title": title,
            "published": "",
            "author": "",
            "content": extract + " [END EXCERPT]",
            "extractor": "wikipedia-api",
        }
    except Exception:
        return None


def fetch_arxiv(url: str) -> dict[str, str] | None:
    """Fetch arXiv paper via arXiv API."""
    parsed = urlparse(url)
    if "arxiv.org" not in parsed.netloc:
        return None

    # Extract arXiv ID from URL
    match = re.search(r"(\d+\.\d+)", url)
    if not match:
        return None

    arxiv_id = match.group(1)

    try:
        resp = requests.get(
            "http://export.arxiv.org/api/query",
            params={"id_list": arxiv_id, "start": 0, "max_results": 1},
            timeout=REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        
        # Parse Atom feed
        import xml.etree.ElementTree as ET
        root = ET.fromstring(resp.content)
        
        # Extract entry (arXiv uses Atom namespace)
        ns = {"atom": "http://www.w3.org/2005/Atom"}
        entry = root.find("atom:entry", ns)
        if entry is None:
            return None

        title_elem = entry.find("atom:title", ns)
        summary_elem = entry.find("atom:summary", ns)
        published_elem = entry.find("atom:published", ns)
        author_elems = entry.findall("atom:author", ns)
        id_elem = entry.find("atom:id", ns)

        title = (title_elem.text or "").strip() if title_elem is not None else ""
        summary = (summary_elem.text or "").strip() if summary_elem is not None else ""
        published = (published_elem.text or "").split("T")[0] if published_elem is not None else ""
        authors = [elem.findtext("atom:name", namespaces=ns) for elem in author_elems if elem.findtext("atom:name", namespaces=ns)]
        arxiv_url = (id_elem.text or "").replace("http://", "https://") if id_elem is not None else url

        content = f"Abstract: {summary}" if summary else ""
        if not content:
            return None

        return {
            "url": arxiv_url,
            "title": title,
            "published": published,
            "author": ", ".join(authors) if authors else "",
            "content": content + " [END EXCERPT]",
            "extractor": "arxiv-api",
        }
    except Exception:
        return None





def fetch_stackexchange(url: str) -> dict[str, str] | None:
    """Fetch Stack Exchange post via Stack Exchange API."""
    parsed = urlparse(url)
    domain = parsed.netloc.lower()
    
    # Map domain to Stack Exchange site
    site_map = {
        "stackoverflow.com": "stackoverflow",
        "superuser.com": "superuser",
        "serverfault.com": "serverfault",
        "askubuntu.com": "askubuntu",
    }
    
    site = None
    for d, s in site_map.items():
        if d in domain:
            site = s
            break
    
    if not site:
        return None

    # Extract question/answer ID from URL
    match = re.search(r"/(?:questions|a)/(\d+)", url)
    if not match:
        return None

    post_id = match.group(1)

    try:
        # Query Stack Exchange API
        resp = requests.get(
            "https://api.stackexchange.com/2.3/posts/" + post_id,
            params={
                "site": site,
                "filter": "withbody",
            },
            timeout=REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()

        items = data.get("items", [])
        if not items:
            return None

        post = items[0]
        title = post.get("title") or ""
        body = post.get("body") or ""
        created = post.get("creation_date")
        owner = post.get("owner", {}).get("display_name") or ""

        created_date = ""
        if created:
            from datetime import datetime
            created_date = datetime.utcfromtimestamp(created).strftime("%Y-%m-%d")

        # Strip HTML tags from body
        body_clean = re.sub(r"<[^>]+>", "", body)
        body_clean = body_clean.replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&")
        body_clean = body_clean.strip()

        if not body_clean:
            return None

        content = f"{title}\n\n{body_clean[:2000]}" if len(body_clean) > 2000 else f"{title}\n\n{body_clean}"
        content += " [END EXCERPT]"

        return {
            "url": url,
            "title": title,
            "published": created_date,
            "author": owner,
            "content": content,
            "extractor": "stackexchange-api",
        }
    except Exception:
        return None


def fetch_hackernews_item(item_id: str) -> dict[str, str] | None:
    """Fetch Hacker News item via HN API."""
    try:
        resp = requests.get(
            f"https://hacker-news.firebaseio.com/v0/item/{item_id}.json",
            timeout=REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        item = resp.json()

        if not item:
            return None

        title = item.get("title") or ""
        by = item.get("by") or ""
        time_val = item.get("time")
        text = item.get("text") or ""
        url = item.get("url") or ""
        score = item.get("score") or 0

        created_date = ""
        if time_val:
            from datetime import datetime
            created_date = datetime.utcfromtimestamp(time_val).strftime("%Y-%m-%d")

        # Clean HTML entities in text
        text_clean = text.replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&")

        content = f"{title}\n\n"
        if text_clean:
            content += text_clean[:1000] + ("\n..." if len(text_clean) > 1000 else "")
        content += f"\n\nScore: {score}, Posted by: {by}"
        content += " [END EXCERPT]"

        final_url = url or f"https://news.ycombinator.com/item?id={item_id}"

        return {
            "url": final_url,
            "title": title,
            "published": created_date,
            "author": by,
            "content": content,
            "extractor": "hackernews-api",
        }
    except Exception:
        return None


def fetch_hackernews(url: str) -> dict[str, str] | None:
    """Fetch Hacker News item from URL."""
    if "news.ycombinator.com" not in url.lower():
        return None

    # Extract item ID from URL
    match = re.search(r"id=(\d+)", url)
    if not match:
        return None

    item_id = match.group(1)
    return fetch_hackernews_item(item_id)


def route_to_api_adapter(url: str) -> dict[str, str] | None:
    """Route URL to the appropriate API adapter."""
    adapters = [
        fetch_wikipedia,
        fetch_arxiv,
        fetch_stackexchange,
        fetch_hackernews,
    ]

    for adapter in adapters:
        try:
            result = adapter(url)
            if result is not None:
                return result
        except Exception:
            continue

    return None
