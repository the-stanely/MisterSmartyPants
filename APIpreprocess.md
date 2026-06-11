# API Preprocess Workflow

This document describes the current API routing workflow used by MisterSmartyPants.

## Scope

The API layer is URL-based and runs during fetch.

It does not use an intent/classifier pass over the query text.

This is intentional: the optional second pass (query-level API classifier) is not part of the current workflow.

## Current Retrieval Flow

```text
user question
  -> search decider
  -> query builder
  -> DDGS search (news/text)
  -> metadata enrichment (optional)
  -> pre-fetch relevance ranking
  -> fetch URL content (per result URL)
       -> API adapter router (by URL/domain)
       -> if no API match: GitHub API fetch (GitHub URLs)
       -> if still no match: Trafilatura extraction
  -> post-fetch filtering
  -> post-fetch relevance ranking
  -> summarize
  -> final answer
```

Search-only slash commands (for example `/search`, `/news`, `/finance`) use a lighter path:

```text
user slash command
  -> DDGS search (news/text)
  -> fast meta-description enrichment (head-only HTML read)
  -> metadata relevance ranking
  -> top-N formatted link list
```

## Why This Design

Many sources are brittle under HTML scraping or bot protection.

When DDGS already returns a known domain URL, direct API fetch is usually more stable and more structured than scraping.

After fetch, the general post-fetch filter can reject stale pages for current-info queries, but only after 5 articles have already survived. That stale check uses the newer of the normalized `published` date and the newest non-requested year detected in the title, URL, or extracted text, so updated pages are less likely to be discarded just because the original published date is old.

## Adapter Routing

Routing entry point:

- `route_to_api_adapter(url)` in `api_adapters.py`

Current adapters:

- `fetch_wikipedia` (`wikipedia-api`)
- `fetch_arxiv` (`arxiv-api`)
- `fetch_stackexchange` (`stackexchange-api`)
- `fetch_hackernews` (`hackernews-api`)

Integration point:

- `fetch_url_content(url, max_chars)` in `websearchMCP.py`

Order in `fetch_url_content`:

1. API adapter router
2. GitHub API route (for GitHub URLs)
3. Generic HTML fetch + Trafilatura

## Normalized Output Contract

Every API adapter should return a page object compatible with the existing pipeline:

```json
{
  "url": "https://example.com/...",
  "title": "Source title",
  "published": "YYYY-MM-DD",
  "author": "author or empty",
  "content": "Normalized source text... [END EXCERPT]",
  "extractor": "provider-api-name"
}
```

Notes:

- `content` should be plain text suitable for ranking/summarization.
- Include `[END EXCERPT]` marker for consistency with downstream prompt formatting.
- Return `None` when the adapter does not match or cannot produce usable content.

## Configuration Notes

Relevant environment settings:

- `SEARCH_ENABLED` (`0` starts new sessions with search OFF)
- `SEARCH_META_ENRICH_ENABLED`
- `SEARCH_META_ENRICH_LIMIT` (`0` means unlimited)
- `SEARCH_CONTEXT_HISTORY_MAX_CHARS` (`0` keeps full prior search context in chat history)
- `SEARCH_ONLY_TOP_N` (max ranked results kept by search-only slash commands)
- `APPEND_SOURCE_LINKS`
- `SOURCE_LINKS_MAX`
- `DDGS_TEXT_BACKEND`
- `DDGS_NEWS_BACKEND`

Prompt-related environment variables are required at startup.

If a required prompt variable is missing/empty, startup fails fast.

## Out of Scope (Current State)

The following are not implemented in the current API workflow:

- Query-level API classifier before DDGS
- Forced API fetch based only on prompt intent
- Silent fallback from API failure to a different API route

## Future Extensions

Potential future additions (not implemented here):

- Additional Stack Exchange network domains
- Optional adapter response caching
