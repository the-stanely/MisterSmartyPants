
# MisterSmartyPants / Unsloth Integration Brainstorming Document

## Project objective
Integrate MisterSmartyPants (MSP) with Unsloth Studio to create a locally hosted, Internet-accessible, multiuser AI chat service.

## Architecture
- Preserve MSP's existing Python retrieval and preprocessing engine.
- Use Unsloth Studio for the chat UI, model inference, chat history, and model settings.
- Initially use Gemma 4 E4B or a comparable quantization.
- Expose MSP retrieval through one high-level MCP tool, tentatively named `research_current`.
- MSP retains responsibility for source selection, retrieval, filtering, and evidence preparation.
- Do not replace MSP's retrieval pipeline with generic agentic web searches.

## Security requirements
- Support authenticated WAN access.
- Ordinary users must not be able to install, configure, or invoke arbitrary tools.
- Only the administrator-approved MSP retrieval tool should be available.
- Do not expose shell execution, filesystem access, arbitrary code execution, or unrestricted web tools.
- Enforce restrictions through actual permissions and configuration, not merely system prompts.
- Do not enable public access until these restrictions are verified.

## Engineering approach
- Preserve existing MSP behavior wherever possible.
- Favor modular, testable changes.
- Evaluate Unsloth capabilities against installed code and current documentation.
- Distinguish confirmed features from proposed features.
- Ask before significant architectural changes.
- Test locally before enabling WAN access.


# MisterSmartyPants + Unsloth Studio Details

## Background
MisterSmartyPants (MSP) is a Python-based retrieval and preprocessing system that supplies curated current information to local LLMs.

It currently uses Ollama and Gemma 4 E4B.

MSP uses an LLM-based decider to select retrieval strategies and supports specialized information sources such as news, weather, finance, Wikipedia, arXiv, and programming resources.

## Previous experiments
MSP and AnythingLLM were compared using the same Gemma 4 E4B model.

Observed:
- MSP produced better results from short questions.
- MSP was more responsive.
- Generic agentic tool selection often required more explicit prompting.
- Retrieval latency was generally more significant than final model generation time.

These are observations from local testing, not universal benchmark results.

## Proposed architecture
Remote browser
    |
Authenticated HTTPS access
    |
Unsloth Studio
    |
Gemma 4 E4B
    |
Approved MCP research tool
    |
MisterSmartyPants
    |
Source selection / retrieval / preprocessing
    |
Curated evidence returned to model

## Desired Unsloth features
- Persistent per-user chat history
- Multiple authenticated users
- Shared local model inference
- Adjustable model parameters
- Quantization selection
- System prompt management
- MCP integration
- Secure WAN access

## Security priorities
Users should have access to chat and approved research capabilities, but not general-purpose system tools.

Verify whether Unsloth supports:
1. Administrator-managed MCP servers.
2. Per-user or global restrictions on tools.
3. Prevention of user-installed MCP servers.
4. Separation of user histories and data.
5. Secure remote access without exposing local administrative services.

If these cannot be enforced, investigate an alternative restricted frontend or gateway.

## Potential implementation steps (unordered)
- Install and validate Unsloth Studio locally.
- Load and benchmark Gemma 4 E4B.
- Inspect Unsloth MCP integration.
- Wrap MSP preprocessing as a single MCP tool.
- Test tool selection and retrieval behavior.
- Verify multiuser permissions and isolation.
- Configure authenticated WAN access.
- Perform security testing before inviting users.
- Create a detailed specification after questions have been settled and gaps have been closed.
- Create a milestone-based implementation plan in the style of Phase13Plan.md

## Alternative architecture
MSP may instead call Unsloth's OpenAI-compatible inference API directly.

This preserves MSP's deterministic orchestration and avoids relying on the model to choose an MCP tool.

Compare both architectures before committing.

## Important
The Unsloth-specific capabilities and permission boundaries must be verified against the installed version. This document describes project goals and proposed architecture, not a completed implementation.

---

## Codex review - October 23, 2026

These are comments and proposals for discussion, not approved architectural changes. I reviewed the root MSP code and current upstream Unsloth documentation. No application code, running services, or deployment settings were changed.

### Overall opinion

This is a reasonable direction: preserve MSP's retrieval quality while gaining persistent histories and a richer shared chat experience. The largest architectural risk is moving the search decision from MSP's planner to Studio's chat model. Keeping the retrieval pipeline intact does not necessarily preserve the behavior that made MSP perform better on short questions.

I recommend answering two questions independently: can Studio enforce the required permissions, and can its model reliably invoke MSP research when needed? A working model load or MCP connection establishes neither. Keep the existing MSP application as the baseline while testing both proposed architectures locally.

### Findings from the current MSP code

| Area | Confirmed code behavior | Consequence |
| --- | --- | --- |
| Retrieval boundary | `websearchMCP.py:run_search()` returns JSON with `search_results`, `fetched_pages`, and `fetch_debug`. | Reuse this pipeline behind a structured service boundary rather than rebuild search and ranking. |
| MCP implementation | No MCP server or tool registrations were found in `websearchMCP.py`; `mcp` is in requirements. | An actual server, transport, schema, authentication, and lifecycle still need implementation. |
| Orchestration | `ChatSession._run_query()` owns routing, contextual query rewriting, retrieval, summaries, answers, links, and history. | Wrapping only `run_search()` bypasses MSP's routing and follow-up interpretation. |
| Specialist sources | API adapters are selected by retrieved URLs; specialized slash commands bias or constrain searches. | Do not assume automatic specialist routing or dedicated weather/finance data APIs already exist. |
| Inference | `chat_once()` supports native Ollama and an OpenRouter chat-completions path. | Add an explicit Studio provider adapter; avoid overloading OpenRouter configuration to mean a different service. |
| Identity/history | `server.py` keeps sessions and jobs in memory; existing passkeys unlock site access. | This does not provide named accounts with persistent per-user histories. |
| Concurrent output | `run_chat_job()` redirects process-global stdout/stderr from separate job threads. | Per-session locks do not prevent different users' jobs overlapping. Investigate output mixing before reusing this for multiuser service. Return values and request-specific logs at the new boundary. |
| Configuration | Module import loads environment settings and requires prompts; models/settings include process-global state. | Separate retrieval configuration from answer-model configuration and review shared initialization before concurrent use. |
| Validation | Some adapter/workflow scripts make live requests and print results without assertions. | Useful manual probes, but not evidence of permissions, isolation, or routing correctness. |

The reported Ollama/Gemma runtime is treated as your setup description. Checked-in defaults and README examples do not establish the live model. I did not inspect the secret-bearing `.env`.

### Studio: evidence versus assumptions

I found a local installation under `C:\Users\Stan (Ely) K\.unsloth\studio`, with Python package metadata named `unsloth-2026.10.8.dist-info`. This identifies a Python package version, not necessarily the Desktop/backend build or effective permissions. Relevant Studio backend source was not located in the inspected installation paths. Account databases and credentials were not inspected; installed behavior remains unverified.

Current official material gives useful leads:

- Unsloth describes managed accounts with private folders, owner-granted model access, and restrictions on repository code. These are promising capabilities, but do not prove a one-tool allowlist. Its remote-access discussion also distinguishes HTTPS from restrictions on host execution. [Official security overview](https://unsloth.ai/blog/security).
- Studio consuming an external MSP MCP server differs from Studio exposing its own management MCP server. The latter includes training/model-management capabilities and is unnecessary for the proposed retrieval connection. [Upstream MCP documentation](https://github.com/unslothai/unsloth/blob/main/studio/MCP.md).
- Version differences matter: the current raw document retires Studio's old static MCP token in favor of account API keys. Search snapshots still showed older instructions. Verify the installed build before applying configuration examples. This concerns Studio's own MCP server, not our future MSP server. [Current raw documentation](https://raw.githubusercontent.com/unslothai/unsloth/main/studio/MCP.md).

Still unverified locally: chat ownership/persistence, external MCP registration and sharing, backend tool restrictions, inference endpoint compatibility, and ordinary users' ability to change shared model state.

### Architecture comparison and recommendation

| Option | Benefit | Cost or uncertainty |
| --- | --- | --- |
| A: Studio UI/model calls MSP MCP retrieval | Closest to the desired Studio chat/history/settings experience. | Studio's model decides when and how to research; permissions, follow-ups, citations, and tool-call reliability need proof. |
| B: MSP orchestrator calls Studio inference API | Preserves MSP's search decisions and evidence preparation. | Studio accounts and histories do not automatically become MSP UI features. Persistent identity/history work remains. |

My preference is to test B as the retrieval-quality control and A as the desired user experience. This is a proposed experiment, not a decision to change architecture. If A passes permission and quality checks, it fits the stated objective more closely.

Do not wrap MSP's complete chat workflow as the research tool: that would generate an answer inside the tool and then ask Studio to generate another. Also avoid having Studio decide to research and then MSP decide not to research. Assign one authority for the search decision in each architecture.

A restricted frontend with private Studio inference remains a fallback, but carries additional UI, identity, and persistence work and should require an explicit architectural decision.

### Proposed `research_current` contract

Keep the public input small:

- `question`: required original request with a server-enforced length limit.
- `context`: optional bounded dialogue for references such as "What about tomorrow?" No caller-selected history file.
- `strategy`: optional constrained enum, initially only values the implementation supports. General/news/weather/finance/wiki/arxiv/programming are candidates, not claims of existing automatic routing.

Do not accept commands, filesystem paths, arbitrary MCP configuration, caller-supplied credentials, or unrestricted URL-fetch instructions. Service-controlled limits and authenticated identity must govern access; a model-supplied user ID cannot authorize anything.

When invoked, the tool should retrieve. It can resolve context and select an approved strategy, but should not repeat the answer-versus-search decision. In B, MSP's outer planner retains that decision.

Proposed response shape:

```json
{
  "schema_version": "1",
  "request_id": "server-generated-id",
  "status": "ok",
  "query_used": "resolved search query",
  "retrieved_at": "UTC timestamp",
  "sources": [
    {
      "source_id": "S1",
      "title": "Source title",
      "url": "https://example.org/article",
      "published_at": null,
      "evidence": "Bounded extracted passage"
    }
  ],
  "warnings": [],
  "truncated": false
}
```

Define `partial`, `no_results`, `timeout`, and `error` statuses. Unknown publication dates stay unknown; retrieval time is separate. Return useful partial evidence with limitations rather than describing a failed lookup as successful research. Keep internal rejection diagnostics and raw exceptions in administrator logs.

Preserve the original question separately from the rewritten query so summaries and ranking can remain tied to user intent. Reserve context space for the system prompt, dialogue, tool schema, evidence, and answer. Character limits alone do not establish token fit. Make source/evidence caps administrator-controlled and report truncation. Start with extracted passages before adding summarization latency.

Test authenticated loopback Streamable HTTP if this installed Studio supports it. A narrowly configured stdio wrapper is another local option, with its command/environment controlled by the administrator. Ordinary users should need neither registration nor configuration rights.

### Security requirements translated into tests

Test with a normal account through backend requests as well as the UI:

| Attempt | Required result |
| --- | --- |
| Register/edit MCP server URLs, commands, or credentials | Backend denies it. |
| Invoke shell, Python, filesystem, generic web tools, or unapproved MCP tools | Denied, including direct API calls and altered saved-chat settings. |
| Use the approved MSP integration | Allowed without granting tool administration. |
| Access another user's conversation, export, or job by changing an ID | Denied; repeat after reconnect/restart. |
| Download/load/unload models, start training, or change shared limits | Denied unless deliberately granted to that role. |
| Change permitted personal generation settings | Bounded and isolated from other users. |
| Reuse expired/revoked credentials | Denied. |

Determine whether disabling built-in tools also disables external MCP. An all-tools-on/all-tools-off switch may not meet the requirements. Hiding controls or relying on prompts does not establish authorization.

MSP itself needs an outbound-network boundary: it fetches URLs from search results and follows redirects. Review all fetch paths, including metadata enrichment, so retrieval cannot reach loopback, LAN services, or link-local metadata endpoints. Validate destinations through redirects and connection establishment or enforce an appropriate egress policy; initial URL text checks alone are insufficient.

Treat retrieved pages as untrusted evidence. Exercise prompt-injection examples and verify that source text cannot change permissions or enable another tool. Keep inference/retrieval backends private to the application path. These checks implement this document's existing security requirements; no public-access changes are part of this review.

### Multiuser choices to settle

- **History ownership:** Studio owns conversations in A; MSP or another chosen application layer must own them in B. Define backup, restore, retention, export, and deletion. Avoid two independent authoritative transcripts.
- **Evidence history:** Decide whether follow-ups reuse stored evidence or refresh it. Retain retrieval timestamps so saved material is distinguishable from a fresh lookup.
- **Settings:** Initially make model and quantization selection administrator-only. Allow bounded personal generation parameters only if their scope is enforced. Shared model swaps can interrupt other users.
- **Capacity:** Several accounts can share a queue. Start with one active inference request until measurements justify concurrency; separately cap queued requests and retrieval workers.
- **Cancellation:** Define tool timeout, overall deadline, cancellation, and abandoned-request handling. A disconnected browser does not necessarily stop backend work.
- **Cloud use:** Decide whether online planning or fallback remains allowed. Local answer generation still sends research queries to external search providers.
- **Citations:** Studio must map answer citations to returned source IDs/URLs. MSP's current deterministic link appending does not automatically run when Studio generates the final answer. Appended links also do not prove individual claims are supported.

### Suggested evaluation and milestone sequence

Create roughly 30-50 fixed prompts: short current-info requests, stable questions that should not search, contextual follow-ups, explicit research requests, conflicting/stale sources, no results, and timeouts. Use recorded provider responses for repeatable retrieval comparisons and live queries for operational behavior.

Compare existing MSP, A, and B using the same exact model artifact/quantization where possible, comparable prompts/settings, and equal evidence budgets. Record unavoidable differences. The family name alone does not establish equivalent weights, templates, context, or thinking behavior.

Measure search-decision correctness, useful queries, relevant evidence, supported claims, valid citations, failure handling, stage/end-to-end latency, and peak memory. Include cold/warm runs and two simultaneous users. Agree on acceptable regression and response-time targets before judging results.

Proposed milestones, pending discussion:

1. **Capability inventory:** Record installed builds, runtime, hardware, model artifact, roles, inference endpoints, and tool-policy behavior. Deliver an evidence-backed capability matrix.
2. **Retrieval boundary:** Extract a structured retrieval service while preserving existing CLI/server behavior. It must return evidence without generating a final chat answer.
3. **Local prototypes:** Test one approved MCP tool and a separate Studio inference adapter; compare quality, latency, and permission gaps.
4. **Architecture decision/specification:** Assign identity, history, settings, citation, and cancellation ownership. Use the requested `Phase13Plan.md` style once that reference is available; it was not found in the inspected workspace.
5. **Multiuser implementation:** Enforce roles, ownership, persistence, limits, and retrieval egress restrictions. Verify isolation and restart/restore behavior.
6. **WAN readiness:** Demonstrate HTTPS/authentication, private backend ports, revocation, limits, backups, and rollback before enabling access.

### Questions for your review

The first five have the largest architectural impact:

1. If Studio cannot provide both strict tool permissions and MSP-level automatic routing, which takes priority: Studio UI/history or MSP orchestration? My preference is to preserve retrieval quality and the stated permission boundary.
2. Is the initial audience a few invited trusted people or a wider public service? How many accounts and simultaneous active chats should we support?
3. Must ordinary short questions automatically trigger research as reliably as MSP today, or is an explicit research toggle/command acceptable initially?
4. Which Desktop/Studio build, CPU/GPU, RAM/VRAM, and exact model file/quantization are you testing? The discovered Python package version does not answer all of this.
5. Which settings may ordinary users control: temperature, answer length, personal system prompt, model, or quantization? Can model/quantization remain administrator-only initially?
6. Must history sync across devices and survive restarts? What retention, backup, export, and deletion behavior do you want?
7. Which existing MSP features must survive: forced search, source links, verbose/prompt diagnostics, search-only commands, passkeys, and mobile sharing?
8. Are dedicated structured weather/finance APIs in scope, or should their existing search-based behavior remain? Is automatic specialist routing required now?
9. Must inference and planning both stay local? May the online planner/fallback remain available, and is there a paid-search budget?
10. What response time is acceptable for one user and a queued second user? What quality regression would disqualify Studio-driven MCP routing?
11. Should training, downloads, model management, and general tools remain privately available to you while ordinary users cannot access them?
12. Should planning documents move to a tracked root `plans/` directory? This file actually lives in `__pycache__/plans/`, is ignored by Git, and could be lost during cache cleanup. I appended here without relocating or force-adding it.

Suggested immediate next step: finish the local Studio smoke test, then verify ordinary-account tool restrictions and automatic research on a few short prompts. Those results will tell us whether the Studio-first experience is viable before substantial integration work.
