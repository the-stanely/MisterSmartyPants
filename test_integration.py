#!/usr/bin/env python
"""Test adapters integrated with websearchMCP fetch_url_content."""
import websearchMCP

# Test Wikipedia fetch
print("Testing Wikipedia fetch via websearchMCP:")
wiki_result = websearchMCP.fetch_url_content("https://en.wikipedia.org/wiki/Machine_learning", 2000)
print(f"  Extractor: {wiki_result.get('extractor', 'trafilatura')}")
print(f"  Title: {wiki_result.get('title', '')[:60]}")
print(f"  Content length: {len(wiki_result.get('content', ''))}")
print(f"  Has [END EXCERPT]: {'[END EXCERPT]' in wiki_result.get('content', '')}")

# Test arXiv fetch
print("\nTesting arXiv fetch via websearchMCP:")
arxiv_result = websearchMCP.fetch_url_content("https://arxiv.org/abs/2310.11111", 2000)
print(f"  Extractor: {arxiv_result.get('extractor', 'trafilatura')}")
print(f"  Title: {arxiv_result.get('title', '')[:60]}")
print(f"  Content length: {len(arxiv_result.get('content', ''))}")

# Test regular URL (should fall back to trafilatura)
print("\nTesting regular HTML fetch (fallback to Trafilatura):")
regular_result = websearchMCP.fetch_url_content("https://example.com", 500)
print(f"  Extractor: {regular_result.get('extractor', 'trafilatura')}")
print(f"  Title: {regular_result.get('title', '')[:60]}")
print(f"  Content exists: {len(regular_result.get('content', '')) > 0}")

print("\nAll integration tests completed.")
