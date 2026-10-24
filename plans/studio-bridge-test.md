# Local Studio / MSP interface test

For a fresh installation, follow the [Unsloth setup guide](../docs/unsloth-setup.md).
The [architecture description](../docs/unsloth-architecture.md) explains the request
and evidence flows. This document retains the detailed development/test notes.

Latest regression status (2026-10-24): **133 passed** across `test_studio_evidence.py`,
`test_studio_bridge.py`, `test_session_lock.py` and `test_openrouter.py`. The two
baseline failures mentioned in earlier entries below are now resolved: native
Ollama requests send `OLLAMA_REQUEST_KEEP_ALIVE`, and console/browser handling
includes `/yahoo-sports`. The checksum-corruption test also now mutates the
checksum at its exact position rather than occasionally changing the marker.

This implements the agreed routing: Studio chat -> MSP decider/retrieval ->
Studio local Gemma inference -> MSP answer -> Studio chat. It is a local,
single-administrator prototype. The existing MSP CLI and HTTP server keep their
configured providers; the bridge uses a request-scoped inference override.

## Configuration

Keep Gemma loaded in Studio. In Studio's API settings, enable keyless inference
access for this local test. This is separate from the Studio user login; keep the
login enabled. An earlier unauthenticated `/v1/models` probe returned 401, so the
keyless setting needs to be enabled before the no-key inference test will work.

Append the entries from `studio-bridge.env.example` to the existing untracked
`.env`. Preserve all existing MSP prompts, search settings, and decider settings.
`SEARCH_DECIDER=planner` and `SEARCH_DECIDER=ollama` both use the Studio adapter;
the Python decider is rejected for this prototype. The active decider's prompt
and decision parsing remain unchanged. Existing planner failure fallback also
remains unchanged: a failed planner can select the direct-answer path.

- `MSP_BRIDGE_API_KEY`: leave blank for keyless loopback calls. Set a value only
  if you want the bridge to require a bearer key, including for local callers.
- `STUDIO_API_KEY`: leave blank when Studio keyless inference access is enabled.
  A configured value is still supported if you later choose authenticated inference.
- `STUDIO_MODEL`: the exact local Gemma identifier returned by Studio's model API.
- `STUDIO_BASE_URL`: Studio's local inference API, normally `http://127.0.0.1:8888/v1`.

No credentials are needed for the keyless local setup. Do not select `msp`, `msp-gemma`, or `default` as
`STUDIO_MODEL`. Do not point `STUDIO_BASE_URL` at the bridge. The adapter rejects
the bridge port, nonlocal URLs, default/MSP model identifiers, and redirects.
It sends no tool definitions or provider-selection options to Studio.

To list Studio models after enabling keyless inference:

```powershell
Invoke-RestMethod -Uri 'http://127.0.0.1:8888/v1/models'
```

An environment variable set only in PowerShell is overridden if the same variable
exists in `.env`, because existing MSP configuration uses dotenv override mode.
Configure the final values consistently in `.env` before launching.

## Start and connect

```powershell
.\run-studio-bridge.ps1
```

The script starts one worker on loopback port 8081. In Studio's custom provider
connection enter:

| Setting | Value |
| --- | --- |
| Name | MSP local test |
| API type | OpenAI Chat Completions |
| Base URL | `http://127.0.0.1:8081/v1` |
| API key | Leave blank; if Studio requires a value, use `local-test` (ignored in keyless mode) |
| Model | `msp` (display name may be MSP) |

Disable Studio tools/MCP for this provider; MSP controls research. If Studio
does not discover the model, enter the ID manually. Verify the final request URL
is `/v1/chat/completions`; base-URL suffix behavior still needs a live UI test.
Select this custom provider for chat, leaving local Gemma loaded for inference.
Do not configure Studio's inference API to route `STUDIO_MODEL` to this provider.

The connector advertises `msp` regardless of the underlying local model. The old
`msp-gemma` ID remains accepted for existing connections/chats, but is not listed
in discovery. To adopt the new name, restart the bridge, edit the Studio connection,
refresh its model list (or enter `msp` manually), and enable/select `msp`. Update
managed users' model allowlists to include `msp` where applicable. Keep the old ID
enabled in Studio if existing chats still reference it. `STUDIO_MODEL` continues
to name the actual local inference model; no inference/model-load settings change.

`GET /health` checks only that the bridge is running. Loopback
`GET /v1/models` advertises its model and discovers the configured local model's
active context from Studio's `/api/inference/loaded-models`. It reports that
capacity as `max_model_len` (used by US's custom-provider context discovery) and
`context_length` (model-list metadata). Native/training capacity and unrelated or
unloaded models are not used. The lookup does not load a model or run inference.

Discovery uses the same validated Studio URL/model/API key as inference. Successful
lookups are cached for 30 seconds and unsuccessful lookups for 5 seconds. If Studio
is unavailable, unauthorized, unconfigured, or reports no active window, discovery
still lists `msp` but omits context metadata rather than guessing or retaining
a stale capacity. `/llm-reload` also clears the bridge's discovery cache. US has its
own discovery cache of about a minute, so capacity changes may take roughly 90
seconds to propagate through both caches.

After restarting the bridge, inspect the advertised window using:

```powershell
Invoke-RestMethod http://127.0.0.1:8081/v1/models | ConvertTo-Json -Depth 5
```

If bridge-key authentication is configured, supply its bearer key for that request.
For the Gemma instance configured with 128K, expect `max_model_len: 131072`.
This is the total context window, independent of the 32768-token output allowance.
`/health` does not check inference, and context discovery does not prove that an
inference request will succeed.

## Smoke checks

1. Ask a stable question. Expect MSP's normal decider then Gemma answer, with no
   retrieval if the decider chooses ANSWER.
2. Ask a current-information question. Confirm a SEARCH decision, normal MSP
   retrieval/ranking, and a source-linked answer in Studio.
3. Ask a contextual follow-up. Confirm the transcript reaches the decider and
   its resolved query retains the subject/location.
4. Start a new chat and verify the previous chat's dialogue is absent.
5. Verify discovery works with the bridge key blank. If testing optional key
   enforcement, set a bridge key, restart, and verify an incorrect key is rejected.
   Stop the bridge with Ctrl+C;
   Studio's ordinary on-device chat should remain usable.

Watch the bridge terminal for pipeline decisions/timing. It currently prints
answers and may print query/source diagnostics using MSP's existing behavior;
use non-sensitive smoke prompts. Do not publish this endpoint or its terminal log.

## Prototype limits

- Text chat only; Responses, attachments, tool calls,
  structured output, usage accounting, and true token streaming are not implemented.
- Streaming requests receive a buffered SSE answer after completion. There are
  no interim heartbeat events; long retrieval may hit Studio's provider timeout.
- Studio supplies the conversation each request, including evidence carried in
  assistant HTML comments. The bridge restores intact source passages for final
  answers without keeping a separate persistent history. The decider sees dialogue.
- One request runs at a time; overlapping requests return 429. This is not a
  per-user identity/isolation implementation. Keyless access trusts local processes;
  MSP does not inherit or verify Studio's user login. Without a configured bridge
  key, nonloopback socket peers are denied. The launcher disables forwarded-header
  processing so clients cannot claim a local address. Keep this service on loopback;
  do not expose it through a public proxy. Optional bridge-key authentication remains
  independent of the existing MSP UI password/passkeys.
- Studio temperature/top-p apply to final answers; MSP's explicit
  decider/summary token budgets and sampling settings are preserved. Other unimplemented provider settings are
  ignored. A requested answer token cap is bounded to 32768. Set the Studio
  connection's Max Tokens limit to 32768 to match. This is an output allowance,
  not a total context limit; evidence and dialogue also consume model context.
- The fixed model ID, port check, no-tools payload, and loop-detection header are
  guards; correct Studio routing must still be confirmed with the live model.
- No installation, Studio account, model-load, WAN, or firewall settings are changed.

## Offline validation

```powershell
.\.venv\Scripts\python.exe -m pytest test_studio_bridge.py test_openrouter.py test_session_lock.py -q
```

Bridge tests exercise the actual MSP decision/answer flow with simulated Studio
responses and search results, including routing guards, links, transcript scope,
buffered SSE, busy handling, and failure cleanup. They do not establish live UI or
inference compatibility.

Initial validation: 36 passed and two pre-existing failures in the combined
command above. Both failures were also reproduced with `websearchMCP.py` loaded
from unchanged `HEAD`: the Ollama `keep_alive` expectation and the Yahoo Sports
slash-command expectation in `test_openrouter.py`. They are outside this bridge
change. All bridge and session-lock tests passed.

The keyless update adds coverage for IPv4/IPv6 loopback access, rejection of
nonlocal peers and spoofed forwarded headers, optional key enforcement, and a
complete simulated request with no Authorization header sent to Studio.

## Slash commands in Studio

Type `/?` or `/help` into the MSP-provider chat for the available commands.
Search-only commands, `/decider`, search/LLM switches, prompt display, and verbose
output use the existing MSP handlers. `/yahoo-sports` is also available in the
bridge. Search-only results and command acknowledgements are returned as assistant
messages without an answer-model call.

The connector excludes `/new`, `/focus-on`, and `/focus-off`: create/manage chats
and control scrolling in Studio. These commands are not listed in connector help
and return an unknown-command response if submitted. Historical `/new` messages
do not clear supplied dialogue; Studio owns conversation context. The bridge has
no lock/unlock flow. Original MSP CLI/server commands remain unchanged.
Local bridge access still follows the loopback/optional-key policy;
the bridge does not independently verify Studio user identities.

| Command | Studio behavior |
| --- | --- |
| `/search-on`, `/search-off`, `/search-force` | Control research for subsequent turns in this chat. |
| `/llm-on`, `/llm-off` | Enable/skip final answer generation; the decider may still run. |
| `/prompt-on`, `/prompt-off` | Include/omit inference prompts in replies. |
| `/verbose-on`, `/verbose-off` | Include/omit MSP pipeline text in replies. |
| `/llm-reload` | Reload Studio connection variables from `.env`; takes effect on subsequent inference calls. Does not load models or reload OpenRouter. |
| `/user [username]` | Report/check the user label received through this account's Studio memory. Diagnostic only; does not set identity. |
| `/evidence` | List the current chat's restored sources, dates, checksums and discarded-block counts. No inference or search. |
| `/evidence show` | Also display the full restored source passages for verification. |

Control settings are reconstructed from user command messages in the supplied
transcript. Earlier commands are never re-executed: replay cannot trigger a
search, inference call, or configuration reload. Control commands and their
acknowledgements are excluded from LLM dialogue. Search-command exchanges are
also excluded; use normal research questions when the answer should participate
in subsequent dialogue. No global/IP-based chat settings or persistent session
store is introduced. If Studio truncates/removes command history, the bridge can
no longer reconstruct those switches; reissue the desired command. A new Studio
chat starts with the configured defaults.

`/prompt-on` uses a request-scoped output sink, as does verbose/command output.
The bridge does not redirect global stdout/stderr or capture other requests'
output. Prompt and verbose replies are visible to Studio and saved in its chat
history; turn them off before sharing chats containing private context.

The planner's `/decider` result now uses its already-provided query directly,
avoiding a redundant query-builder inference call. Other decider modes still
build a query when needed.

Slash-command validation: 65 bridge/session tests passed. A live in-process test
against the running Studio Gemma endpoint returned `/decider` ANSWER in 439 ms;
a transcript containing `/search-off` then returned the requested answer without
running the decider. This validates the updated bridge code against Studio
inference, not Studio's handling of slash input in its chat UI. Restart the bridge
and use `/?` in Studio to test that final UI path. The two previously documented
baseline OpenRouter-suite failures remain outside this change.

## Per-account memory user-ID test

In each US account, open Chat settings, enable **Use memory in chats**, and save
a plain line in the memory editor, replacing `stan` with that account's test label:

```text
MSP_USER_ID=stan
```

Restart the bridge after this code update. In that account's MSP-provider chat:

```text
/user
/user stan
```

The first reports the incoming label. The second reports MATCH or MISMATCH against
the expected label. It does not set the label from the command argument. Try the
same steps in a second account with another label, then reopen both accounts'
chats and repeat. The diagnostic makes no inference/search calls and works without
a configured Studio model. It inspects only `MSP_USER_ID` lines inside Studio's
`<agents_md>` wrapper in system messages; ordinary dialogue and unwrapped system
labels are ignored. Conflicting/invalid markers are reported instead of choosing
an identity. No memory contents beyond the ID are returned and nothing is stored.

This is an editable memory label, not an authenticated US account ID. It is not
used for authorization or evidence storage. It also does not identify a chat.
The test verifies whether account memory reaches MSP; it does not yet establish
cross-user access control or hidden-evidence persistence.

## Real source evidence and inspection

Each successful ordinary research turn appends only that turn's prepared source
passages and provenance in independently encoded `MSP_EVIDENCE_V1` HTML comments.
Payloads use uncompressed UTF-8 JSON encoded as base64 with SHA-256 checksums.
Follow-ups restore them as dated prior-search context, without sending the carrier
or restored passages to the decider. Follow-ups without new research do not copy
the old payload again. Studio stores and replays these comments with its chat.
MSP adds no evidence database, user mapping or shared evidence cache.

After restarting the bridge, ask a normal research question, then use `/evidence`
and `/evidence show`. Ask a follow-up with `/search-off` to check reuse. Reopen the
chat and repeat; a new chat should report zero sources. Old answers created before
this feature have no payload. The diagnostic inspects only history Studio actually
sent, so it cannot detect a completely removed research turn. A partially retained
turn reports its missing source count when at least one block survives.

Both commands also report the current supplied context: exact character counts
for incoming Studio history (including encoded carriers), reconstructed MSP
history, and its evidence versus dialogue/other-context portions. A rough token
estimate uses four characters per token; it does not use Gemma's tokenizer.
The loaded model's context window is obtained through the existing cached Studio
discovery hook, or reported unavailable. These counts exclude the current command,
MSP answer instructions, chat-template overhead and reply tokens, so they are not
an exact inference prompt size or a measure of remaining capacity. They describe
only the history Studio sent, after any trimming it has already performed.

The bridge rejects damaged blocks individually and preserves other intact sources.
Limits are 64 KiB decoded per source, 256 KiB per new research turn, and 1 MiB of
restored payloads per request. At most five selected sources are carried per turn.
Oversized outgoing sources produce a visible retention note; `/evidence` reports
damaged or over-limit incoming blocks. Request limits are 1 MiB characters per
message and 2 MiB characters total, separate from model token capacity. These
connector transfer limits are separate from the original MSP CLI history cap.

Studio/model context trimming can still remove evidence. Base64 expands text and
also consumes model context on Studio's side; it is not compression or encryption.
Checksums detect damage, not authorship. Full passages displayed by `/evidence show`
become visible chat content, including in exports. Command replies are omitted
from subsequent LLM dialogue, preventing this diagnostic from duplicating context.

Validation: 118 offline evidence, bridge and session tests passed, covering source
round trips, independent recovery after truncation, schema/checksum rejection,
limits, duplicate handling, history isolation, streaming diagnostics and separation
between decider dialogue and answer evidence. Real source retention still needs
the same Studio UI reopening check that passed for the synthetic transport probe.
