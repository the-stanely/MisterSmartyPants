# MisterSmartyPants

MisterSmartyPants is a local AI chat demo that combines an Ollama-hosted chat model with built-in search. Live web search is triggered when a query needs current information or knowledge beyond the model's training. Search articles are extracted, scored for relevance, and summarized before being sent to the chat LLM. It is important to note that not all LLMs reliably use new information supplied in context; models that handle RAG-style context well will perform best.

This demo was developed on a slow CPU-only, memory-bound system, yet it performs surprisingly well. The chat LLM as configured is llama3.2:latest. Several lightweight local models are also used to decide when to search and to process search results. The default summary path uses Ollama, while the search decider and relevance filter use Python models.

This project started as a practical experiment in making local models better at current-event questions without dumping raw search results into the final LLM prompt. The current pipeline tries to keep the slow, capable model focused on clean, relevant, current source material.

## Consulting / Custom AI Tools

MisterSmartyPants was built as a practical local AI/search demo. If you want similar AI-enabled software for a business, research workflow, internal tool, or automation project, contact me for consulting or custom development. Email me at stan.ely.kleszczelski at Gmail.

This project was built with AI-assisted development in VSCode and is intended to help others learn how local models, retrieval augmentation, search, extraction, ranking, and prompt construction can work together.

If you have a problem or need help, open an issue on GitHub.

## What It Does

MisterSmartyPants can run as either:

- a terminal chat application
- a simple HTTP chat server with a browser frontend

For search-backed answers, the pipeline is roughly:

```text
user question
  -> search decider (Python Transformers)
  -> query builder (Ollama)
  -> web search (DDGS)
  -> metadata enrichment (optional)
  -> pre-fetch relevance rank (title/url/date/snippet)
  -> fetch candidate pages
  -> URL-based API adapters (supported domains)
  -> fallback extraction (GitHub API, then Trafilatura)
  -> post-fetch relevance rank (with extracted text)
  -> article summarization (Ollama by default, Python Transformers optional)
  -> final LLM answer (Python requests + Ollama HTTP API)
```

The goal is to reduce prompt bloat, keep poor search results away from the final answer model, and improve performance on slow hardware.

## Features

- Local Ollama final answer model
- Ollama or Python/Transformers search decider
- DDGS web search using news and text search modes
- URL-based API adapters for Wikipedia, arXiv, Stack Exchange, and Hacker News
- URL-aware GitHub API fetching for GitHub profile and repository results
- Optional metadata enrichment before the first rank pass
- Trafilatura article extraction
- Cross-encoder relevance ranking (pre-fetch and post-fetch)
- Configurable article summarization through Ollama or Python Transformers
- Rich Markdown terminal rendering
- Browser chat UI through FastAPI
- Per-browser session isolation for the HTTP server
- Slash commands for debugging and testing
- `.env.example` configuration template
- Windows PowerShell install/run scripts

## Requirements

- Windows PowerShell
- Python 3.10 or newer
- Ollama installed and running
- At least one Ollama chat model pulled locally
- Internet access for web search and first-time Hugging Face model downloads

The installer script can install Python 3.11 with `winget` if Python is missing.

## Quick Start

Clone the repository, then from the project folder run:

```powershell
powershell -ExecutionPolicy Bypass -File .\install.ps1
```

Create your local config:

```powershell
Copy-Item .env.example .env
```

Edit `.env` as needed.

Start the terminal chat:

```powershell
powershell -ExecutionPolicy Bypass -File .\run.ps1
```

Start the HTTP server:

```powershell
powershell -ExecutionPolicy Bypass -File .\run-server.ps1
```

Open:

```text
http://127.0.0.1:8080
```

## Ollama Setup

Install Ollama from:

```text
https://ollama.com/
```

Pull a model, for example:

```powershell
ollama pull llama3.2:latest
```

Then set it in `.env`:

```env
OLLAMA_MODEL=llama3.2:latest
```

You can use larger or smaller models depending on your hardware and patience.

## Configuration

Most behavior is controlled through `.env`.

Start with:

```powershell
Copy-Item .env.example .env
```

Important settings:

```env
OLLAMA_API=http://localhost:11434/api/chat
OLLAMA_MODEL=llama3.2:latest
OLLAMA_TIMEOUT_SECONDS=1200
OLLAMA_NUM_PREDICT=2048
OLLAMA_NUM_THREAD=
```

`OLLAMA_NUM_PREDICT` is the maximum generated-token budget for normal Ollama answers. Lowering it can speed up final responses if your model tends to produce long answers. Try `1024` or `2048` if speed matters more than long-form output. Ollama-based article summaries use `DECIDER_SUMMARY_MAX_TOKENS` instead.

Search and fetch settings:

```env
SEARCH_MODES=news,text
SEARCH_NEWS_LIMIT=10
SEARCH_TEXT_LIMIT=10
FETCH_TOP_N=5
FETCH_SURVIVOR_N=20
FETCH_WORKERS=4
SEARCH_META_ENRICH_ENABLED=1
SEARCH_META_ENRICH_LIMIT=5
```

`SEARCH_NEWS_LIMIT` and `SEARCH_TEXT_LIMIT` control the initial DDGS search sample. `FETCH_SURVIVOR_N` controls how many post-Trafilatura survivors are collected before final reranking. `FETCH_TOP_N` controls how many final ranked sources are sent forward. `FETCH_WORKERS` is the fetch/extraction thread count. Lower it to reduce CPU and network pressure during article fetching; raise it to fetch more pages in parallel. `OLLAMA_NUM_THREAD` is optional; leave it blank to let Ollama choose, or set it to tune CPU threads for Ollama calls, including Ollama-based summaries.

`SEARCH_META_ENRICH_ENABLED` toggles snippet enrichment from page metadata before the pre-fetch rank pass. `SEARCH_META_ENRICH_LIMIT` controls how many eligible text-mode results are enriched; set `0` for no cap.

Search decision settings:

```env
SEARCH_DECIDER=ollama
DECIDER_MODEL=gemma2:2B
FORCE_SEARCH_MARKERS=
```

`DECIDER_MODEL` is a Hugging Face model id when `SEARCH_DECIDER=python`, and an Ollama model name when `SEARCH_DECIDER=ollama`. `FORCE_SEARCH_MARKERS` is a comma-separated list of keywords that force a search regardless of the decider result. It is empty by default; add terms to override the decider for obvious search queries.

Summarization settings:

```env
SUMMARIZE_EXCERPTS=1
SUMMARY_PROVIDER=ollama
SUMMARY_MODEL=gemma2:2B
DECIDER_SUMMARY_MAX_TOKENS=300
DECIDER_SUMMARY_PROMPT="User question:\n{user_question}\n...\nArticle:\n{excerpt_text}"
```

Relevance ranking settings:

```env
RELEVANCY_MODEL=cross-encoder/ms-marco-MiniLM-L-6-v2
DECIDER_RELEVANCE_ENABLED=1
DECIDER_RELEVANCE_EXCERPT_CHARS=1200
```

The cross-encoder is now used twice as a numeric ranker: first over DDGS result metadata before fetch, then again over extracted Trafilatura article text after post-fetch rejection. `RELEVANCY_THRESHOLD` may still exist in older `.env` files, but the current main search path ranks and selects top results instead of using it as the primary article gate.

Prompt settings are also in `.env`, including the final answer prompt, query builder prompt, memory-answer prompt, search-decider prompts, and article-summary prompt. The query builder uses `DECIDER_MODEL` through Ollama to rewrite conversational requests into concise search queries before DDGS runs. The Ollama search-decider prompt supports `{today_date}` and `{user_prompt}` and maps `YES` to answer from model knowledge and `NO` to search. The article-summary prompt supports `{user_question}` and `{excerpt_text}` so summaries can be focused on the original request.

Prompt environment variables are required. Startup exits with a fatal error if any required prompt variable is missing or empty.

## Hugging Face Token

A Hugging Face token is optional for public models, but useful for higher rate limits and private/gated models.

If you use one, keep it only in `.env`, not in `.env.example` and not in git.

`GITHUB_TOKEN` is also optional. GitHub API-backed fetching works without it for public data, but a token raises rate limits. Keep real tokens only in `.env`.

Common environment variable names used by Hugging Face tooling include:

```env
HF_TOKEN=your_token_here
```

If you add custom token handling, keep the real token out of the repository.

## Terminal Commands

Inside the chat, these slash commands are available:

```text
/?                 Show commands.
/new               Clear chat context.
/decider <prompt>  Run configured decider and query builder only; bypass rules, search, and LLM.
/search-off        Disable search and send prompt directly to the LLM.
/search-on         Enable search and decider logic.
/llm-off           Skip only the final assistant answer.
/llm-on            Enable the final assistant answer.
/prompt-on         Show prompts and relevance inputs.
/prompt-off        Hide prompt debug output.
/focus-off         Web UI: stop following output while working.
/focus-on          Web UI: follow output while working.
exit, quit, q      Exit.
```

In the web UI, slash commands work the same way and affect only that browser session.

## HTTP Server

The HTTP server is implemented in `server.py` with FastAPI.

Run it with:

```powershell
powershell -ExecutionPolicy Bypass -File .\run-server.ps1
```

Default address:

```text
http://127.0.0.1:8080
```

The frontend is:

```text
static/index.html
```

API endpoints:

```text
GET  /api/health
POST /api/chat           Start a chat job
GET  /api/chat/{job_id}  Poll a chat job until it is done
POST /api/new
```

Public static/crawler endpoints:

```text
GET /favicon.ico
GET /robots.txt
GET /sitemap.xml
```

The crawler files live in `static/robots.txt` and `static/sitemap.xml`. Update the sitemap URL if you host the demo on a different domain.

The server uses an `msp_session` cookie. Each browser session gets its own `ChatSession`, including its own history and slash-command state. Chat requests run as background jobs so reverse proxies and Cloudflare do not have to hold one long request open. The browser polls job status and shows a changing `[working...]` indicator while the job runs.

The server also has a small in-memory bot guard: if one client IP receives 3 consecutive 404 responses, that IP is blocked for 10 minutes. Behind Cloudflare, the server uses `CF-Connecting-IP`; behind other proxies it falls back to the first `X-Forwarded-For` value, then the socket IP. HTTP request logs are timestamped, and block start/deny/expiry events are logged explicitly.

## Reverse Proxy Notes

For a public demo behind a reverse proxy, point the proxy to the local server:

```text
http://127.0.0.1:8080
```

If the reverse proxy runs on another machine, change `run-server.ps1` to listen on the LAN interface, for example:

```powershell
--host 0.0.0.0 --port 8080
```

Do not expose Ollama directly. Expose only the MisterSmartyPants HTTP server.

## Search Pipeline Details

The search pipeline intentionally avoids sending raw search result dumps directly to the final LLM. Search result quality and user question intent are still the weakest links in this workflow. MisterSmartyPants uses a free search backend; if the initial search candidates are poor, extraction, relevance scoring, and summarization can only recover so much. A dedicated paid search or news API will likely improve answer quality more than additional prompt tuning. Many search results include browser-rendered content that's difficult to extract. They include graphics, tables, sliders, etc.

User intent could also use some work. My experience is that models below 1B can't reliably divine the user's intent. The decider LLM scores whether the request needs search or can be answered from model knowledge. Because of my low-end test hardware (Intel I7-8700, 16GB), a 0.5B model is used.

Current behavior:

1. The search decider decides whether current web data is needed. A keyword intent detector is used to force obvious search cases.
2. The query builder rewrites the prompt into a concise DDGS query.
3. DDGS runs configured search modes, usually 10 news results plus 10 text results.
4. Candidate URLs are deduplicated.
5. Optional metadata enrichment updates snippets for eligible text-mode results before ranking.
6. A cross-encoder ranks the search-result sample using title, URL, date, and snippet.
7. Pages are fetched in ranked order until the pipeline has enough post-fetch survivors or runs out of candidates.
8. The fetch step first tries URL-based API adapters for supported domains (Wikipedia, arXiv, Stack Exchange, Hacker News), then GitHub API for GitHub URLs, then Trafilatura for general HTML pages.
9. Post-fetch rejection removes fetch failures, empty/short extractions, redirected homepages, ad/tracking URLs, YouTube current-info results, and near-duplicates. For current-info queries, stale-result rejection does not begin until 5 articles have already survived post-fetch checks, and freshness is based on the newer of the parsed published date or the newest non-requested year detected in the title, URL, or extracted text.
10. A cross-encoder reranks surviving extracted articles using metadata plus extracted text.
11. The top 5 articles are summarized by the configured summary provider, usually Ollama.
12. The final Ollama model receives the user question and summarized current source material.

Useful logs include:

```text
[Search decider said ANSWER in nnn ms]
[Search decider said SEARCH in nnn ms, Search = x.xxx, Answer = y.yyy]
[Query builder: nnn ms, "concise search query"]
[Search rank: nnn candidates, model]
[Fetch rank: nnn survivors -> 5 sources]
[Search: nnn ms, nnn chars]
[Summaries: nnn ms, original_chars -> summarized_chars, provider, model]
[LLM: nnn ms, model]
```

With `/prompt-on`, relevance debug output also shows the exact metadata and extracted text sent to the cross-encoder for the post-fetch ranking pass.

## Model Downloads and Cache

Python models are loaded through Hugging Face and cached locally.

When `SEARCH_DECIDER=python`, the Python decider model uses local-first Hugging Face snapshot loading. The relevance cross-encoder also uses local-first snapshot loading. If `SUMMARY_PROVIDER=python`, the summary model uses the same local-first Hugging Face cache path. If `SUMMARY_PROVIDER=ollama`, the summary model must be available in Ollama, for example with `ollama pull gemma2:2b`.

First run may download Python model files. Later runs should use the local Hugging Face cache.

## Project Scripts

```text
install.ps1          Install Python dependencies into .venv
run.ps1              Run terminal chat
run-server.ps1       Run HTTP server on port 8080
export-vscode.ps1    Export local VS Code settings/extensions
import-vscode.ps1    Restore local VS Code settings/extensions
```

`vscode-backup/` is ignored and should not be committed.

## Repository Hygiene

The real `.env` file is ignored and should not be committed.

Commit `.env.example` instead.

Before publishing, check:

```powershell
git status --short
git ls-files -- .env vscode-backup
```

Those should not show tracked secret or personal config files.

## Troubleshooting

If Python is missing:

```powershell
powershell -ExecutionPolicy Bypass -File .\install.ps1
```

If Ollama is not responding:

```powershell
ollama list
ollama run llama3.2:latest "hello"
```

If a Hugging Face model download is slow or rate-limited, set `HF_TOKEN` in your local `.env` or environment.

If the web UI does not load, check:

```text
http://127.0.0.1:8080/api/health
```

If port 8080 is already in use, edit `run-server.ps1` and your reverse proxy config to use another port.

## License

MIT License. See `LICENSE`.
