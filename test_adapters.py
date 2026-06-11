#!/usr/bin/env python
"""Quick test of API adapters."""
import api_adapters

# Test Wikipedia
wiki_result = api_adapters.fetch_wikipedia("https://en.wikipedia.org/wiki/Python_(programming_language)")
print("Wikipedia test:")
if wiki_result:
    print(f"  Title: {wiki_result.get('title', '')[:60]}")
    print(f"  Content preview: {wiki_result.get('content', '')[:100]}")
    print(f"  Extractor: {wiki_result.get('extractor', '')}")
else:
    print("  Failed")

# Test arXiv
print("\narXiv test:")
arxiv_result = api_adapters.fetch_arxiv("https://arxiv.org/abs/2306.01169")
if arxiv_result:
    print(f"  Title: {arxiv_result.get('title', '')[:60]}")
    print(f"  Published: {arxiv_result.get('published', '')}")
    print(f"  Extractor: {arxiv_result.get('extractor', '')}")
else:
    print("  Failed")

# Test Hacker News
print("\nHacker News test:")
hn_result = api_adapters.fetch_hackernews("https://news.ycombinator.com/item?id=36962316")
if hn_result:
    print(f"  Title: {hn_result.get('title', '')[:60]}")
    print(f"  Author: {hn_result.get('author', '')}")
    print(f"  Extractor: {hn_result.get('extractor', '')}")
else:
    print("  Failed")

# Test Router
print("\nRouter test (Wikipedia):")
route_result = api_adapters.route_to_api_adapter("https://en.wikipedia.org/wiki/Machine_learning")
if route_result:
    print(f"  ✓ Routed successfully, extractor: {route_result.get('extractor', '')}")
else:
    print("  ✗ Router failed")

print("\nAll tests completed.")
