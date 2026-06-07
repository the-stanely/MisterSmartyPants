# MisterSmartyPants

MisterSmartyPants is a local AI chat demo that combines an Ollama-hosted chat model with built-in search. Live web search is triggered when a query needs current information or knowledge beyond the model's training. Search articles are extracted, scored for relevance, and summarized before being sent to the chat LLM. It is important to note that not all LLMs reliably use new information supplied in context; models that handle RAG-style context well will perform best.

This demo was developed on a slow CPU-only, memory-bound system, yet it performs surprisingly well. The chat LLM as configured is llama3.2:latest. Several lightweight Hugging Face models are also used to decide when to search and to process search results.

This project started as a practical experiment in making local models better at current-event questions without dumping raw search results into the final LLM prompt. The current pipeline tries to keep the slow, capable model focused on clean, relevant, current source material.

## What It Does

MisterSmartyPants can run as either:

- a terminal chat application
- a simple HTTP chat server with a browser frontend

For search-backed answers, the pipeline is roughly:

```text
user question
  -> search decider (Python Transformers)
  -> web search (DDGS)
  -> fetch candidate pages
  -> Trafilatura article extraction
  -> cross-encoder relevance scoring (Python sentence-transformers)
  -> article summarization (Python Transformers)
  -> final LLM answer (Python requests + Ollama HTTP API)
```

The goal is to reduce prompt bloat, keep poor search results away from the final answer model, and improve performance on slow hardware.

## Features

- Local Ollama final answer model
- Python/Transformers search decider
- DDGS web search using news and text search modes
- Trafilatura article extraction
- Cross-encoder relevance filtering
- Local Python summarizer model for article excerpts
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
```

Search and fetch settings:

```env
SEARCH_MODES=news,text
FETCH_TOP_N=5
FETCH_SCAN_LIMIT=20
FETCH_CANDIDATE_N=5
FETCH_WORKERS=4
```

`FETCH_WORKERS` is the fetch/extraction thread count. Lower it to reduce CPU and network pressure during article fetching; raise it to fetch more pages in parallel.

Search decision settings:

```env
SEARCH_DECIDER=python
DECIDER_MODEL=Qwen/Qwen2.5-0.5B-Instruct
FORCE_SEARCH_MARKERS=latest,today,yesterday,current,news,recent,newest,weather,search,look up,find
```

Summarization settings:

```env
SUMMARIZE_EXCERPTS=1
SUMMARY_PROVIDER=ollama
SUMMARY_MODEL=qwen2.5:0.5b-instruct
DECIDER_SUMMARY_MAX_TOKENS=300
```

Relevance scoring settings:

```env
RELEVANCY_MODEL=cross-encoder/ms-marco-MiniLM-L-6-v2
RELEVANCY_THRESHOLD=0.0
DECIDER_RELEVANCE_ENABLED=1
DECIDER_RELEVANCE_EXCERPT_CHARS=1200
```

Prompt settings are also in `.env`, including the final answer prompt, query builder prompt, memory-answer prompt, and search-decider prompt.

## Hugging Face Token

A Hugging Face token is optional for public models, but useful for higher rate limits and private/gated models.

If you use one, keep it only in `.env`, not in `.env.example` and not in git.

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
/decider <prompt>  Run Python decider only; bypass rules.
/search-off        Disable search and send prompt directly to the LLM.
/search-on         Enable search and decider logic.
/llm-off           Skip final LLM answer after search.
/llm-on            Enable final LLM answer after search.
/prompt-on         Show prompts and relevance inputs.
/prompt-off        Hide prompt debug output.
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

The server uses an `msp_session` cookie. Each browser session gets its own `ChatSession`, including its own history and slash-command state.

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

The search pipeline intentionally avoids sending raw search result dumps directly to the final LLM.

Current behavior:

1. The search decider decides whether current web data is needed.
2. DDGS runs configured search modes, usually `news,text`.
3. Candidate URLs are deduplicated and filtered.
4. Obvious homepage/root URLs are skipped.
5. Pages are fetched.
6. Trafilatura extracts article text.
7. A cross-encoder scores `(query, extracted excerpt)` for relevance.
8. Relevant articles are summarized by a small local Python model.
9. The final Ollama model receives the user question and summarized current source material.

Useful logs include:

```text
[Decider: nnn ms, Search = x.xxx, Answer = y.yyy]
[Relevance: nnn ms, model, score = x.xxx, threshold = y.yyy, keep = true]
[Search: nnn ms, nnn chars]
[Summaries: nnn ms, original_chars -> summarized_chars, provider, model]
[LLM: nnn ms, model]
```

## Model Downloads and Cache

Python models are loaded through Hugging Face and cached locally.

The search decider and summary model use local-first snapshot loading. The relevance cross-encoder also uses local-first snapshot loading.

First run may download model files. Later runs should use the local Hugging Face cache.

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

## Consulting / Custom AI Tools

MisterSmartyPants was built as a practical local AI/search demo. If you want similar AI-enabled software for a business, research workflow, internal tool, or automation project, contact me for consulting or custom development. Email me at stan.ely.kleszczelski at Gmail.

This project was built with AI-assisted development and is intended to help others learn how local models, search, extraction, ranking, and prompt construction can work together.

If you have a problem or need help, open an issue on GitHub.

## License

MIT License. See `LICENSE`.
