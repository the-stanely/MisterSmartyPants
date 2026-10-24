# Set up Unsloth Studio with MisterSmartyPants

This guide configures the development integration tested with Studio 2026.10.8
on Windows. Studio provides accounts, chat history and local model inference;
MSP provides its existing decision and research pipeline. Menu labels can differ
between Studio versions. Start with both services on the same Windows computer.

See the [architecture description](unsloth-architecture.md) and
[integration diagram](../MisterSmartyPants-Unsloth-Diagram.png).

## 1. Install and check Studio

Install Studio using the [official Unsloth installation instructions](https://github.com/unslothai/unsloth#installation).
The upstream Windows installer and launch commands are:

```powershell
irm https://unsloth.ai/install.ps1 | iex
unsloth studio
```

If already installed, keep the working installation. Open Studio, download/load
the desired local Gemma GGUF model and send a normal on-device chat message.
The tested model is `unsloth/gemma-4-E4B-it-GGUF`; use the actual ID your
installation advertises, including its spelling and capitalization.

In the loaded model's settings (gear icon), set its active context window to
the size your hardware can support. We tested **131072 tokens (128K)**. A model's
advertised native capacity does not prove it is loaded with that window; confirm
the active window through MSP discovery in step 5. A larger window can require
more memory. Keep this local model loaded even after selecting MSP for chat.

## 2. Enable Studio inference access

In Studio settings, find the API/API keys and Remote & LAN controls. For a local
single-account test, enable **Keyless API access → Chat and inference**, if
available. Otherwise create a Studio inference API key. Managed-account or
remote-access configurations may require a key even for local requests.

The Studio login password and inference API key are different credentials.
MSP needs the inference key only when Studio requires it. Do not use the login
password as an API key. Leave Studio's account login enabled.

List the available models from PowerShell, using the actual Studio port:

```powershell
# Keyless Studio inference:
Invoke-RestMethod 'http://127.0.0.1:8888/v1/models' | ConvertTo-Json -Depth 6

# If Studio requires a key, read it without printing it:
$studioCredential = Get-Credential -UserName 'studio-api' -Message 'Enter the Studio API key as the password'
$studioHeaders = @{ Authorization = 'Bearer ' + $studioCredential.GetNetworkCredential().Password }
Invoke-RestMethod 'http://127.0.0.1:8888/v1/models' -Headers $studioHeaders | ConvertTo-Json -Depth 6
Remove-Variable studioCredential, studioHeaders
```

Use the ID of the actual loaded local model, not the MSP connector or `default`.

## 3. Prepare MSP

From the repository root, install/update MSP's environment:

```powershell
.\install.ps1
```

For a new checkout only, copy `.env.example` to `.env`. If `.env` already exists,
keep it and its search configuration/prompts. Add or update the entries from
[`studio-bridge.env.example`](../studio-bridge.env.example):

```dotenv
MSP_BRIDGE_PORT=8081
MSP_BRIDGE_API_KEY=
STUDIO_BASE_URL=http://127.0.0.1:8888/v1
STUDIO_API_KEY=
STUDIO_MODEL=unsloth/gemma-4-E4B-it-GGUF
```

Replace `STUDIO_MODEL` with the exact ID from step 2. Put the Studio inference key
in `STUDIO_API_KEY` if required; otherwise leave it blank. Do not commit `.env`.
Ensure `SEARCH_DECIDER=planner` (or the existing supported `ollama` decider mode).
The Python decider is unsupported by this bridge. The Studio inference override
uses the selected local model for the decider and final answer; existing routing
prompts and decision flow stay in effect. Retrieval and optional summarization
continue to follow MSP's existing configuration.

The two key settings serve opposite directions:

| Setting | Used for |
| --- | --- |
| `STUDIO_API_KEY` | MSP calling Studio's local inference API on port 8888. |
| `MSP_BRIDGE_API_KEY` | Studio calling MSP on port 8081. Blank allows loopback callers; optional key enforcement is independent of Studio login. |

Configure values in `.env`: the launcher loads it in override mode. Setting a
different value only in a PowerShell environment variable may not take effect.
The original MSP web server and Ollama server are not required for this path.
MSP still needs its normal retrieval dependencies and search-provider credentials
where configured.

## 4. Start the MSP bridge and connect Studio

Keep Studio running. Open another PowerShell terminal in the MSP repository:

```powershell
.\run-studio-bridge.ps1
```

Leave that terminal running. In Studio's provider/connector settings, add a
connection with these values:

| Studio field | Value |
| --- | --- |
| Name | MisterSmartyPants (any descriptive name) |
| API type | **OpenAI Chat Completions** |
| Base URL | `http://127.0.0.1:8081/v1` |
| API key | Blank when `MSP_BRIDGE_API_KEY` is blank; if the UI requires text, `local-test` is ignored in keyless mode. Otherwise enter the matching bridge key. |
| Model ID | `msp` |
| Max Tokens limit | **32768** (maximum output allowance, not total context size) |

Enable/select `msp` in chat. Refresh discovery or enter the model ID manually if
needed. The legacy ID `msp-gemma` is still accepted for existing chats. Disable
Studio tools/MCP for this provider; MSP handles research. Choose Chat Completions,
not Responses or System One (decisions).

**Avoid a routing loop:** Studio chat selects `msp`, but MSP's `STUDIO_MODEL`
must identify the real on-device Gemma. `STUDIO_BASE_URL` must point to Studio
on 8888, never back to MSP on 8081. Do not unload Gemma when selecting the connector.

## 5. Verify discovery and chat

With the bridge key blank:

```powershell
Invoke-RestMethod 'http://127.0.0.1:8081/health'
Invoke-RestMethod 'http://127.0.0.1:8081/v1/models' | ConvertTo-Json -Depth 6
```

If you configured a bridge key, send it as a bearer header for `/v1/models`, using
the credential-reading pattern from step 2 with the **bridge** key. Health checks
only that MSP is running. Discovery should list `msp`; when Studio reports the
loaded model's active window it also includes `max_model_len` and `context_length`.
For 128K both should be **131072**. Missing context metadata means discovery could
not verify the window, not that the window is unlimited. Bridge discovery caches
successes for 30 seconds; Studio's own cache can delay display further.

In a new Studio chat selecting `msp`:

1. Send `/?` to check the connection and supported commands.
2. Send `/verbose-on`, then a simple stable question. Check the decision and answer.
3. Ask a current weather/news question. Check that MSP searches and cites sources.
4. Send `/evidence`. Expect source dates and context-size information.
5. Send `/search-off`, then ask about a detail from those sources. This checks reuse
   without fresh research. Re-enable with `/search-on` afterward.
6. Reopen the chat and repeat `/evidence`. Start a new chat and expect zero retained
   sources. Repeat under another account if testing managed users.

Use `/evidence show` when you need the complete passages. Studio stores diagnostic
replies too, so repeated full reports can consume substantial context. MSP removes
slash-command exchanges before inference, but Studio can still count them for
trimming. Token estimates currently describe restored MSP history, not Studio's
exact token usage. The incoming Studio character count includes encoded payloads
and reflects only history sent after any Studio trimming.

## 6. Accounts and LAN clients

Studio owns user login, account permissions and conversation storage. In the tested
installation, each managed user needed their own MSP connector configuration;
repeat step 4 in that account and enable/allow `msp` as applicable. Do not assume
the owner's connection automatically appears for every account.

Use Studio's **Remote & LAN** settings for browser access from another computer.
The browser connects to the Studio host, while Studio's backend calls MSP on
that host's loopback interface. The connector URL remains
`http://127.0.0.1:8081/v1`, not the browser computer's address. Keep MSP bound to
loopback; opening port 8081 to LAN clients is not required. The integration assumes
Studio and MSP share a host network; containers/WSL with separate networking need
an adapted deployment and are outside this tested recipe.

Optional memory diagnostic: enable **Use memory in chats** and add
`MSP_USER_ID=yourname` to that account's memory notes. `/user yourname` should
report a match. This is an editable diagnostic label, not authentication, and is
not needed for evidence retention. Evidence follows the actual conversation.

## Troubleshooting and routine operation

| Symptom | Check |
| --- | --- |
| Connector cannot connect | Studio and the bridge are running; connector uses port 8081 with `/v1`, correct API type and matching bridge key if configured. |
| Studio returns 401 / MSP returns an inference error | `STUDIO_API_KEY` matches Studio's inference key, or keyless chat/inference is enabled and permitted for the current account setup. |
| `Set STUDIO_MODEL ... not default or an MSP provider` | Use the real loaded model ID from Studio's `/v1/models`. |
| Busy / HTTP 429 | The prototype runs one MSP pipeline at a time; retry after the other request finishes. |
| Missing/stale context window | Verify the loaded model's active window, API access and exact ID; allow discovery caches to expire. |
| `/evidence` shows no sources | A successful normal research turn must occur after this feature was installed. Old chats, raw slash-search results, or trimmed-away payloads may have no evidence. |
| Long search times out in Studio | The bridge buffers responses until complete and sends no heartbeat. Review provider timeout and retrieval timing. |

After changing Studio connection/model variables in `.env`, `/llm-reload` reloads
them and clears discovery cache; it does not load a model. Restart the bridge for
code changes or port changes. Stop it with Ctrl+C. Studio's on-device chat works
independently when the bridge is stopped.

The development bridge supports text Chat Completions, buffered SSE, and one
active request. It does not implement attachments, Responses, tool calls or exact
token accounting. See [development test notes](../plans/studio-bridge-test.md)
for transport bounds, commands and test history.
