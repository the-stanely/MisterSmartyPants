#!/usr/bin/env python
"""Comprehensive test of API adapters in a realistic search workflow."""
import json
import websearchMCP

# Test 1: Search for a Wikipedia topic and fetch via adapter
print("=" * 70)
print("TEST 1: Wikipedia via DDGS search")
print("=" * 70)
query = "python programming language wikipedia"
results = []
with websearchMCP.DDGS(timeout=20) as ddgs:
    search_results = ddgs.text(query, max_results=3)
    for item in search_results:
        results.append({"url": item["href"], "title": item["title"]})

# Find and fetch Wikipedia result
for result in results:
    if "wikipedia.org" in result["url"]:
        print(f"Found Wikipedia URL: {result['url']}")
        content = websearchMCP.fetch_url_content(result["url"], 1000)
        print(f"Extractor used: {content.get('extractor', 'trafilatura')}")
        print(f"Title: {content.get('title', '')}")
        print(f"Content preview: {content.get('content', '')[:150]}...")
        break

# Test 2: Search for arXiv papers and fetch via adapter
print("\n" + "=" * 70)
print("TEST 2: arXiv via DDGS search")
print("=" * 70)
query = "arxiv machine learning papers"
results = []
with websearchMCP.DDGS(timeout=20) as ddgs:
    search_results = ddgs.text(query, max_results=3)
    for item in search_results:
        results.append({"url": item["href"], "title": item["title"]})

# Find and fetch arXiv result
for result in results:
    if "arxiv.org" in result["url"]:
        print(f"Found arXiv URL: {result['url']}")
        content = websearchMCP.fetch_url_content(result["url"], 1000)
        print(f"Extractor used: {content.get('extractor', 'trafilatura')}")
        print(f"Title: {content.get('title', '')}")
        print(f"Published: {content.get('published', '')}")
        print(f"Content preview: {content.get('content', '')[:150]}...")
        break

# Test 3: Search that returns multiple provider types
print("\n" + "=" * 70)
print("TEST 3: Multi-provider search (mixed results)")
print("=" * 70)
query = "stack overflow python tutorial"
with websearchMCP.DDGS(timeout=20) as ddgs:
    search_results = ddgs.text(query, max_results=5)
    for i, item in enumerate(search_results[:3], 1):
        url = item["href"]
        print(f"\nResult {i}: {url[:70]}")
        content = websearchMCP.fetch_url_content(url, 500)
        extractor = content.get("extractor", "trafilatura")
        print(f"  Extractor: {extractor}")
        print(f"  Content length: {len(content.get('content', ''))}")

print("\n" + "=" * 70)
print("All workflow tests completed successfully!")
print("=" * 70)
