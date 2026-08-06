# MisterSmartyPants

MisterSmartyPants is a local AI chat demo that combines an Ollama-hosted chat model with built-in search. Live web search is triggered when a query needs current information or knowledge beyond the model's training. Search articles are extracted, scored for relevance, and summarized before being sent to the chat LLM. It is important to note that not all LLMs reliably use new information supplied in context; models that handle RAG-style context well will perform best.

This demo was developed on a slow CPU-only, memory-bound system, yet it performs surprisingly well. It supports local Ollama models and OpenRouter model chains. In the current default configuration, a strong OpenRouter planner decides whether ordinary conversational turns need web search, while local Hugging Face models remain available for decider, ranking, and summary paths.

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
  -> explicit command / forced-search rule, or search planner
  -> planner-supplied search query when search is needed
  -> web search (DDGS)
  -> metadata enrichment (optional)
  -> pre-fetch relevance rank (title/url/date/snippet)
  -> fetch candidate pages
  -> URL-based API adapters (supported domains)
  -> fallback extraction (GitHub API, then Trafilatura)
  -> post-fetch relevance rank (with extracted text)
  -> optional article summarization (Ollama/OpenRouter or Python Transformers)
  -> final LLM answer (Ollama or OpenRouter)
```

The goal is to reduce prompt bloat, keep poor search results away from the final answer model, and improve performance on slow hardware.

## Features

- Ollama or OpenRouter final answer model chains
- Strong OpenRouter search planner, plus optional Ollama or Python/Transformers deciders
- DDGS web search using news and text search modes
- URL-based API adapters for Wikipedia, arXiv, Stack Exchange, and Hacker News
- URL-aware GitHub API fetching for GitHub profile and repository results
- Optional metadata enrichment before the first rank pass
- Trafilatura article extraction
- Cross-encoder relevance ranking (pre-fetch and post-fetch)
- Configurable article summarization through Ollama or Python Transformers
- Rich Markdown terminal rendering
- Browser chat UI through FastAPI
- Per-browser sessions with mobile-friendly cookie renewal and local transcript restore
- Slash commands for debugging and testing
- `.env.example` configuration template
- Windows PowerShell install/run scripts

## Requirements

- Windows PowerShell
- Python 3.10 or newer
- Ollama installed and running, or an OpenRouter API key and model chain
- At least one local Ollama model only when using Ollama-based answer or summary paths
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

### OpenRouter final-answer provider

Set `USE_OPENROUTER=true` and provide `OPENROUTER_API_KEY` to route LLM requests through OpenRouter instead of Ollama. `OPENROUTER_MODEL_CHAIN` is a comma-separated ordered fallback list for final answers. `OR_PLANNER_MODEL` is the ordered chain for `SEARCH_DECIDER=planner`; `OR_DECIDER_MODEL` is retained for the legacy Ollama decider; and `OR_SUMMARY_MODEL` routes Ollama-compatible article summaries. An empty specialized chain falls back to `OPENROUTER_MODEL_CHAIN`.

```dotenv
USE_OPENROUTER=true
OPENROUTER_API_KEY=your-key
OPENROUTER_MODEL_CHAIN=openai/gpt-5.4-nano,openai/gpt-oss-120b,nvidia/nemotron-3-super-120b-a12b,deepseek/deepseek-v4-flash-0731,inclusionai/ring-2.6-1t,qwen/qwen3-32b
OR_PLANNER_MODEL=openai/gpt-5.4-nano,deepseek/deepseek-v4-flash-0731
OR_DECIDER_MODEL=openai/gpt-5.4-nano,deepseek/deepseek-v4-flash-0731
OR_SUMMARY_MODEL=openai/gpt-5.4-nano,deepseek/deepseek-v4-flash-0731
```

Search and fetch settings:

```env
SEARCH_ENABLED=1
PASSWORD=
PASSKEY_RP_ID=
SEARCH_MODES=news,text
SEARCH_NEWS_LIMIT=10
SEARCH_TEXT_LIMIT=10
FETCH_TOP_N=5
FETCH_SURVIVOR_N=20
FETCH_WORKERS=4
SEARCH_META_ENRICH_ENABLED=1
SEARCH_META_ENRICH_LIMIT=5
SEARCH_CONTEXT_HISTORY_MAX_CHARS=0
ROUTING_CONTEXT_MAX_CHARS=6000
SESSION_COOKIE_MAX_AGE_SECONDS=2592000
SESSION_COOKIE_SECURE=1
SEARCH_ONLY_TOP_N=10
APPEND_SOURCE_LINKS=1
SOURCE_LINKS_MAX=5
```

`SEARCH_NEWS_LIMIT` and `SEARCH_TEXT_LIMIT` control the initial DDGS search sample. `FETCH_SURVIVOR_N` controls how many post-Trafilatura survivors are collected before final reranking. `FETCH_TOP_N` controls how many final ranked sources are sent forward. `FETCH_WORKERS` is the fetch/extraction thread count. Lower it to reduce CPU and network pressure during article fetching; raise it to fetch more pages in parallel. `OLLAMA_NUM_THREAD` is optional; leave it blank to let Ollama choose, or set it to tune CPU threads for Ollama calls, including Ollama-based summaries.

`SEARCH_ENABLED` controls whether search starts enabled in new chat sessions. Default is `1` (ON). You can still toggle at runtime with `/search-on`, `/search-off`, and `/search-force`.

`PASSWORD` is an optional comma-separated list of unlock passwords. When it is set, sessions start locked, and only `/unlock <password>` is accepted until a password matches. Leave it blank for no session lock.

`PASSKEY_RP_ID` is optional. Set it to the public hostname serving the site (for example, `MisterSmartyPants.us`) to keep passkey configuration explicit. If blank, the server uses the request hostname. Do not include `https://` or a port.

`SEARCH_META_ENRICH_ENABLED` toggles snippet enrichment from page metadata before the pre-fetch rank pass. `SEARCH_META_ENRICH_LIMIT` controls how many eligible text-mode results are enriched; set `0` for no cap.

`SEARCH_CONTEXT_HISTORY_MAX_CHARS` controls how much of each search turn's evidence block is persisted into chat history for follow-up questions (including when `/search-off` is enabled). Set `0` to keep full search context (default), or set a positive cap to limit history growth.

`ROUTING_CONTEXT_MAX_CHARS` bounds recent user/assistant dialogue supplied to routing models. Prior web-search evidence is excluded from this routing context. Set it to `0` to disable conversational routing context.

`SESSION_COOKIE_MAX_AGE_SECONDS` controls the renewed browser-session lifetime. Set `SESSION_COOKIE_SECURE=1` for HTTPS deployments; use `0` only for local HTTP development.

`SEARCH_ONLY_TOP_N` controls how many ranked results search-only commands keep (for example `/search`, `/news`, `/finance`).

`APPEND_SOURCE_LINKS` appends missing source URLs to answers after generation so links are present even if the model ignores prompt instructions. `SOURCE_LINKS_MAX` limits how many links are appended.

Search decision settings:

```env
SEARCH_DECIDER=planner
DECIDER_MODEL=Qwen/Qwen2.5-0.5B-Instruct
FORCE_SEARCH_MARKERS=
```

`SEARCH_DECIDER=planner` uses `PLANNER_SYSTEM_PROMPT` and `OR_PLANNER_MODEL` to make one strong-model answer/search plan for ordinary turns. It returns either an answer decision or a concise DDGS query, so the legacy query-builder stage is skipped. `SEARCH_DECIDER=python` uses a local Hugging Face `DECIDER_MODEL`; `SEARCH_DECIDER=ollama` uses an Ollama-compatible model. `FORCE_SEARCH_MARKERS` is a comma-separated list of keywords that force a search before any model routing.

Summarization settings:

```env
SUMMARIZE_EXCERPTS=0
SUMMARY_PROVIDER=ollama
SUMMARY_MODEL=gemma2:2b
SUMMARIZE_EXCERPTS_MIN_CHARS=100000
DECIDER_SUMMARY_MAX_TOKENS=300
DECIDER_SUMMARY_PROMPT="User question:\n{user_question}\n...\nArticle:\n{excerpt_text}"
```

`SUMMARIZE_EXCERPTS` is disabled in the checked-in configuration. When enabled, `SUMMARIZE_EXCERPTS_MIN_CHARS` controls when the excerpt summarizer runs: set it to `0` to summarize every search payload, or raise it to summarize only large result sets.

Relevance ranking settings:

```env
RELEVANCY_MODEL=cross-encoder/ms-marco-MiniLM-L-6-v2
DECIDER_RELEVANCE_ENABLED=1
DECIDER_RELEVANCE_EXCERPT_CHARS=1200
```

The cross-encoder is now used twice as a numeric ranker: first over DDGS result metadata before fetch, then again over extracted Trafilatura article text after post-fetch rejection. `RELEVANCY_THRESHOLD` may still exist in older `.env` files, but the current main search path ranks and selects top results instead of using it as the primary article gate.

Prompt settings are also in `.env`, including the final answer prompt, planner prompt, legacy query-builder and decider prompts, memory-answer prompt, and article-summary prompt. `PLANNER_SYSTEM_PROMPT` receives bounded recent dialogue and the latest request, and must return JSON with either `{"action":"ANSWER"}` or `{"action":"SEARCH","query":"..."}`. The legacy query builder is used only outside planner mode for conversational search follow-ups. The article-summary prompt supports `{user_question}` and `{excerpt_text}` so summaries can be focused on the original request.

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

[Search & Lookup]
/arxiv <query>     Run search only against arXiv.
/decider <prompt>  Run configured planner/decider only; bypass rules, search, and final-answer LLM.
/finance <query>   Run search only for finance news.
/hn <query>        Run search only against Hacker News.
/news <query>      Run search only for current news.
/search <query>    Run search only; bypass planner/decider and answer LLM.
/stack <query>     Run search only against Stack Overflow/Exchange.
/stocks <query>    Run search only for stock market news.
/weather <query>   Run search only for weather results for a city/state.
/wiki <query>      Run search only against Wikipedia.

[Session Controls]
/focus-off         Web UI: stop following output while working.
/focus-on          Web UI: resume following output while working.
/lock              Lock command processing.
/llm-off           Skip the final LLM answer.
/llm-on            Enable the final LLM answer.
/new               Clear chat context.
/llm-reload        Reload OpenRouter settings from .env.
/prompt-off        Hide text sent to the answer/query LLM.
/prompt-on         Show text sent to the answer/query LLM.
/search-force      Enable forced full search answers; bypass decider.
/search-off        Disable search; answer from prior context.
/search-on         Enable search and decider logic.
/unlock <password> Unlock command processing.
/verbose-off       Web UI: show final answers only.
/verbose-on        Web UI: show pipeline details.
exit, quit, q      Exit.
```

In the web UI, slash commands work the same way and affect only that browser session.

When `PASSWORD` is configured, sessions start locked. While locked, the system responds only to `/unlock <password>`.

### Biometric/passkey unlock

The web UI can unlock with a registered platform passkey, using the phone or computer’s built-in biometric check or device PIN. First unlock with `/unlock <password>`, then select **Add passkey** on each device you want to authorize. Later, select **Unlock with passkey** instead of entering the password.

The server stores only the public WebAuthn credential in its local `passkeys.json` file; biometric data and private keys never leave the device. `passkeys.json` is intentionally ignored by Git.

Passkeys require HTTPS in production and are tied to the exact public hostname. Set `PASSKEY_RP_ID` to that hostname (for example, `MisterSmartyPants.us`, without `https://` or a port), and enroll from the same hostname on the phone or computer that will use it.

Passkeys currently provide site-level unlock access, not separate user accounts: any registered passkey can unlock a new browser session. This is suitable for a small trusted deployment. The unlocked state remains in the server’s in-memory chat session; after a server restart, unlock again with a password or passkey.

The web input helper text shows the current state as `Search is ON/OFF/FORCED. Ask something or use /?` and updates when you run `/search-on`, `/search-off`, or `/search-force`.

The web UI starts in concise mode, showing only `You` and `Mr. Smarty Pants` final answers. Use `/verbose-on` to restore the search, model, and pipeline details; `/verbose-off` returns to concise mode.

Each completed non-system reply also has a **Copy formatted** button. It writes both a light-themed HTML representation (black text on white) and matching plain text to the clipboard. Desktop Google Docs normally uses the rich HTML representation; Android browsers may provide only the compatible plain-text clipboard entry. This preserves common formatting such as headings, emphasis, lists, links, and code blocks where rich clipboard support is available.

The adjacent **Share HTML** button creates a light-themed standalone HTML file and opens the device share sheet. On Android, choose Google Drive to upload the file to the selected Google account and folder. In Drive, use **More** → **Open with** → **Google Docs** on that HTML file to import and edit it with its formatting and mobile word wrapping intact. Drive retains the uploaded HTML file; its upload timestamp distinguishes repeated exports. Google Docs for Android supports importing and editing HTML files.

`/search <query>` is a strict search-engine mode: it bypasses the planner/decider and all LLM calls. It uses DDGS result metadata and fast meta-description enrichment (no full page extraction), ranks results with the metadata relevance ranker, and returns the top `SEARCH_ONLY_TOP_N` links with summaries.

`/search-force` switches the session into forced search mode. Subsequent normal prompts use the full search-backed answer pipeline and skip only the planner/decider; DDGS search, fetch/extraction, ranking, optional summarization, final answer generation, source-link appending, and history updates still run. Use `/search-on` to return to planner/decider-controlled search, or `/search-off` to answer from memory and prior context.

`/arxiv <query>` and `/wiki <query>` are the same no-LLM mode, but with the search query biased to `arxiv.org` or `wikipedia.org/wiki` so the results stay domain-specific.

`/hn <query>` and `/stack <query>` are the same no-LLM mode, but with the search query biased to Hacker News or Stack Overflow/Exchange domains.

`/weather <query>` is the same no-LLM mode, but with the query biased toward general weather results. It is web-search based, not a dedicated weather API.

`/news <query>` is the same no-LLM mode, but with the query biased toward current news and DDGS news results.

`/finance <query>` and `/stocks <query>` are the same no-LLM mode, but with the query biased toward finance or stock market news.

Yahoo is no longer treated as a preferred source in the default ranking order.

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
GET  /api/session        Check whether this browser still has server conversation context
POST /api/chat           Start a chat job
GET  /api/chat/{job_id}  Poll a chat job until it is done
POST /api/new
```

Public static/crawler endpoints:

```text
GET /favicon.ico
GET /manifest.webmanifest
GET /icon-192.png
GET /icon-512-maskable.png
GET /robots.txt
GET /sitemap.xml
```

### Favicon and Android home-screen shortcut

`static/favicon.ico` is the browser favicon and contains multiple icon sizes. The Android home-screen metadata is in `static/manifest.webmanifest`; it uses these PNG assets:

```text
static/icon-192.png              Standard 192 × 192 app icon
static/icon-512-maskable.png     512 × 512 Android maskable app icon
```

The manifest is linked from `static/index.html`, requests standalone display, and sets the app's dark theme/background color. On Android Chrome, visit the HTTPS site, then use Chrome's menu to choose **Install app** or **Add to Home screen** (the exact wording varies by Chrome version). The resulting shortcut uses the manifest name and Android icon rather than relying only on the browser favicon.

To replace the artwork, update the ICO and regenerate both PNG variants from the same source. Keep the maskable icon's full square background intact; Android may crop maskable icons into a circle or rounded shape. Restart the server after changing `server.py`; manifest or icon file changes are served from `static/`, though browser or CDN caching may require a hard refresh or a short wait before the updated asset appears.

The crawler files live in `static/robots.txt` and `static/sitemap.xml`. Update the sitemap URL if you host the demo on a different domain.

The server uses a renewed persistent `msp_session` cookie. Each browser session gets its own in-memory `ChatSession`, including history and slash-command state. The browser also restores up to 100 recent turns from device-local storage after a reload. If the server no longer has the matching chat context—for example after a server restart—the UI labels those restored turns as review-only rather than implying they will affect the next answer. Chat requests run as background jobs so reverse proxies and Cloudflare do not have to hold one long request open. The browser polls job status and shows a changing `[working...]` indicator while the job runs.

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

For ordinary turns, the configured planner makes the answer-versus-search decision with the latest request and bounded recent dialogue. This avoids asking a small local model to reinterpret a conversational follow-up before a stronger online answer model sees it. Local Python and Ollama deciders remain available for lower-cost deployments.

Current behavior:

1. Explicit slash commands and `FORCE_SEARCH_MARKERS` take priority. For other turns, the planner decides whether current web data is needed and supplies a concise search query when it is.
2. DDGS runs configured search modes, usually 10 news results plus 10 text results.
3. Candidate URLs are deduplicated.
4. Optional metadata enrichment updates snippets for eligible text-mode results before ranking.
5. A cross-encoder ranks the search-result sample using title, URL, date, and snippet.
6. Pages are fetched in ranked order until the pipeline has enough post-fetch survivors or runs out of candidates.
7. The fetch step first tries URL-based API adapters for supported domains (Wikipedia, arXiv, Stack Exchange, Hacker News), then GitHub API for GitHub URLs, then Trafilatura for general HTML pages.
8. Post-fetch rejection removes fetch failures, empty/short extractions, redirected homepages, ad/tracking URLs, YouTube current-info results, and near-duplicates. For current-info queries, stale-result rejection does not begin until 5 articles have already survived post-fetch checks, and freshness is based on the newer of the parsed published date or the newest non-requested year detected in the title, URL, or extracted text.
9. A cross-encoder reranks surviving extracted articles using metadata plus extracted text.
10. The top fetched articles are optionally summarized by the configured summary provider. Summarization is disabled in the checked-in configuration.
11. The final Ollama or OpenRouter model receives the original user request, prior context, and current source material.
12. Missing source links are appended deterministically from validated fetched URLs when `APPEND_SOURCE_LINKS=1`.

Useful logs include:

```text
[Search planner said ANSWER in nnn ms]
[Search planner said SEARCH in nnn ms]
[Search planner query: "concise search query"]
[Search rank: nnn candidates, model]
[Fetch rank: nnn survivors -> 5 sources]
[Search: nnn ms, nnn chars]
[Summaries: nnn ms, original_chars -> summarized_chars, provider, model]
[LLM: nnn ms, model]
```

With `/prompt-on`, relevance debug output also shows the exact metadata and extracted text sent to the cross-encoder for the post-fetch ranking pass.

## Model Downloads and Cache

Python models are loaded through Hugging Face and cached locally.

When `SEARCH_DECIDER=python`, the Python decider model uses local-first Hugging Face snapshot loading. The relevance cross-encoder also uses local-first snapshot loading. If `SUMMARY_PROVIDER=python`, the summary model uses the same local-first Hugging Face cache path. If `SUMMARY_PROVIDER=ollama` and `USE_OPENROUTER=false`, the summary model must be available in Ollama, for example with `ollama pull gemma2:2b`. When `USE_OPENROUTER=true`, Ollama-compatible summary calls use `OR_SUMMARY_MODEL` instead.

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
