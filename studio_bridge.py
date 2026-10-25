"""Local Chat Completions facade for MSP; Studio remains the inference server.

This is a single-administrator integration prototype, not the multiuser service.
Studio owns the visible transcript. No stdout capture or process-wide provider
changes are used. Ordinary questions use MSP's run_query flow; slash commands
use its command handlers with Studio-specific controls adapted below.
"""
from __future__ import annotations

import hmac
import base64
import hashlib
import ipaddress
import io
import json
import logging
import os
import re
import threading
import time
from urllib.parse import urlsplit
from uuid import uuid4

import requests
from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

import websearchMCP as msp
from studio_evidence import (EvidenceState, MAX_MESSAGE_CHARS, MAX_REQUEST_CHARS,
                             pack_sources, unpack_sources)

logger = logging.getLogger(__name__)
MODEL_ID = "msp"
MODEL_ALIASES = frozenset({MODEL_ID, "msp-gemma"})
_pipeline_lock = threading.Lock()
_discovery_lock = threading.Lock()
_context_cache: tuple[tuple[str, str, str], float, int | None] | None = None
app = FastAPI(title="MSP Studio bridge", docs_url=None, redoc_url=None)


def authorize(request: Request, authorization: str | None = Header(default=None)) -> None:
    expected = os.getenv("MSP_BRIDGE_API_KEY", "").strip()
    if not expected:
        # Trust the socket peer, never forwarded headers or a supplied hostname.
        try:
            if request.client and ipaddress.ip_address(request.client.host).is_loopback:
                return
        except ValueError:
            pass
        raise HTTPException(403, "Keyless bridge access is restricted to loopback connections.")
    if not hmac.compare_digest((authorization or "").encode(), f"Bearer {expected}".encode()):
        raise HTTPException(401, "Invalid bridge API key", headers={"WWW-Authenticate": "Bearer"})


class Message(BaseModel):
    role: str
    content: str = Field(max_length=MAX_MESSAGE_CHARS)


class CompletionRequest(BaseModel):
    model: str
    messages: list[Message] = Field(min_length=1, max_length=200)
    stream: bool = False
    max_tokens: int | None = Field(default=None, ge=1, le=32768)
    # These are deliberately not passed into the existing decider prompts.
    temperature: float | None = Field(default=None, ge=0, le=2)
    top_p: float | None = Field(default=None, gt=0, le=1)
    tools: list[dict] | None = None
    tool_choice: str | dict | None = None


def studio_configuration() -> tuple[str, str]:
    """Use the same fixed, local inference destination for discovery and chat."""
    base = os.getenv("STUDIO_BASE_URL", "http://127.0.0.1:8888/v1").rstrip("/")
    parsed = urlsplit(base)
    bridge_port = int(os.getenv("MSP_BRIDGE_PORT", "8081"))
    if (parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}
            or parsed.username or parsed.password or parsed.query or parsed.fragment
            or parsed.path != "/v1" or (parsed.port or 80) == bridge_port):
        raise ValueError("STUDIO_BASE_URL must be a local HTTP /v1 URL on a different port from MSP.")
    return base, os.getenv("STUDIO_API_KEY", "").strip()


def loaded_studio_model(base: str, key: str) -> dict:
    """Resolve once per inference request; never select a provider or auto-load."""
    headers = {"X-MSP-Inference": "1"}
    if key:
        headers["Authorization"] = f"Bearer {key}"
    try:
        with requests.Session() as client:
            client.trust_env = False
            response = client.get(base.removesuffix("/v1") + "/api/inference/loaded-models",
                                  headers=headers, timeout=(1, 2), allow_redirects=False)
        if response.status_code != 200:
            raise ValueError(f"Studio loaded-model discovery returned HTTP {response.status_code}.")
        body = response.json()
    except (requests.RequestException, ValueError) as exc:
        if isinstance(exc, ValueError) and str(exc).startswith("Studio loaded-model"):
            raise
        raise ValueError("Studio loaded-model discovery unavailable; check Studio and its API key.") from None
    entries = body.get("data") if isinstance(body, dict) else None
    if not isinstance(entries, list):
        raise ValueError("Studio returned an invalid loaded-model list.")
    loaded = [entry for entry in entries if isinstance(entry, dict) and entry.get("loaded") is True]
    if not loaded:
        raise ValueError("No local model is loaded in Studio. Load one model before using MSP.")
    if len(loaded) != 1:
        raise ValueError("Multiple models are loaded in Studio. Leave exactly one local inference model loaded for MSP.")
    model = loaded[0].get("id")
    if not isinstance(model, str) or not model.strip() or model == "default" or "msp" in model.lower():
        raise ValueError("Studio must report a real loaded local model, not default or an MSP provider.")
    return loaded[0]


def _fetch_context_window(base: str, key: str) -> int | None:
    entry = loaded_studio_model(base, key)
    meta = entry.get("meta")
    for value in (entry.get("max_model_len"),
                  meta.get("n_ctx") if isinstance(meta, dict) else None,
                  entry.get("context_length"), entry.get("context_window")):
        if type(value) is int and value > 0:
            return value
    return None


def studio_context_window() -> int | None:
    global _context_cache
    try:
        base, key = studio_configuration()
    except ValueError:
        return None
    cache_key = (base, "loaded", hashlib.sha256(key.encode()).hexdigest())
    with _discovery_lock:
        if _context_cache is not None:
            identity, expires, value = _context_cache
            if identity == cache_key and time.monotonic() < expires:
                return value
        try:
            value = _fetch_context_window(base, key)
        except (requests.RequestException, ValueError):
            # Never include response bodies, credentials, or exception strings.
            logger.warning("Studio context discovery unavailable; omitting the context window")
            value = None
        _context_cache = (cache_key, time.monotonic() + (30 if value is not None else 5), value)
        return value


class StudioInference:
    def __init__(self, request: CompletionRequest):
        self.base, self.key = studio_configuration()
        self.model = loaded_studio_model(self.base, self.key)["id"]
        msp.LLM_MODEL_CONTEXT.set(self.model)
        self.request = request

    def __call__(self, messages, *, num_predict=None, think=None) -> str:
        payload = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "max_tokens": num_predict if num_predict is not None else (self.request.max_tokens or msp.OLLAMA_NUM_PREDICT),
            "temperature": msp.OLLAMA_TEMPERATURE if num_predict is not None or self.request.temperature is None else self.request.temperature,
            "top_p": msp.OLLAMA_TOP_P if num_predict is not None or self.request.top_p is None else self.request.top_p,
            "enable_thinking": False if think is None else think,
        }
        headers = {"X-MSP-Inference": "1"}
        if self.key:
            headers["Authorization"] = f"Bearer {self.key}"
        # Disable proxy inheritance and redirects: credentials stay on the exact
        # configured loopback endpoint. No retries can duplicate MSP workflows.
        with requests.Session() as client:
            client.trust_env = False
            response = client.post(self.base + "/chat/completions", json=payload,
                                   headers=headers, timeout=(5, msp.OLLAMA_TIMEOUT_SECONDS),
                                   allow_redirects=False)
        if response.status_code != 200:
            raise RuntimeError(f"Studio inference returned HTTP {response.status_code}")
        obj = response.json()
        content = obj["choices"][0]["message"]["content"]
        if not isinstance(content, str) or not content.strip():
            raise ValueError("Studio returned no answer text.")
        msp.LLM_MODEL_CONTEXT.set(self.model)
        return content.strip()


@app.get("/health")
def health():
    return {"status": "ok", "service": "MSP Studio bridge", "model": MODEL_ID}


@app.get("/v1/models", dependencies=[Depends(authorize)])
def models():
    model = {"id": MODEL_ID, "object": "model", "created": 0, "owned_by": "msp"}
    context = studio_context_window()
    if context is not None:
        # Studio's custom-provider compaction probes max_model_len, whereas the
        # model-list schema also understands context_length for display.
        model.update(max_model_len=context, context_length=context)
    return {"object": "list", "data": [model]}


CONTROL_SETTINGS = {
    "/search-off": {"search_enabled": False, "search_forced": False},
    "/search-on": {"search_enabled": True, "search_forced": False},
    "/search-force": {"search_enabled": True, "search_forced": True},
    "/llm-off": {"llm_enabled": False},
    "/llm-on": {"llm_enabled": True},
    "/prompt-off": {"prompt_debug": False},
    "/prompt-on": {"prompt_debug": True},
    "/verbose-off": {"verbose_output": False},
    "/verbose-on": {"verbose_output": True},
}
STUDIO_HELP = """## MSP commands for Studio

### Search only (no answer LLM)

- `/search <query>` — general search
- `/serper <query>` — Google through configured Serper
- `/arxiv <query>`, `/wiki <query>`, `/hn <query>`, `/stack <query>`
- `/weather <city, state>`, `/news <query>`, `/finance <query>`, `/stocks <query>`
- `/yahoo-sports <query>`

### Chat controls

- `/search-on`, `/search-off`, `/search-force` — control research for this chat
- `/llm-on`, `/llm-off` — enable/skip the final answer model
- `/prompt-on`, `/prompt-off` — show/hide inference prompts in replies
- `/verbose-on`, `/verbose-off` — show/hide pipeline details in replies
- `/llm-reload` — reload the bridge's Studio connection settings from `.env`

### Inspection and testing

- `/decider <prompt>` — show the decider's decision/query without searching
- `/user [username]` — show/check the user label received through Studio memory
- `/evidence` — list retained sources and context sizes
- `/evidence show` — also display the full retained source passages
- `/evidence-test seed|check` — test hidden-text round trips using synthetic evidence
- `/?` or `/help` — show this list

Settings apply to this chat while Studio includes its command history.

Create/manage chats and control scrolling in Studio's UI.
Lock and unlock commands are not used here.
"""


def session_from_transcript(messages: list[Message]) -> msp.ChatSession:
    """Rebuild chat controls without replaying searches, inference or reloads.

    Chat Completions supplies no reliable Studio thread identity. Deriving state
    from this request's transcript avoids shared/IP-based session settings.
    """
    session = msp.ChatSession(rich_output=False)
    session.locked = False
    session.prompt_debug = False
    session.llm_enabled = True
    session.bridge_evidence = EvidenceState()
    session.bridge_wire_chars = sum(len(message.content) for message in messages)
    omit_reply = False
    for message in messages:
        if message.role == "assistant":
            content, sources = session.bridge_evidence.restore(message.content)
        else:
            content = unpack_sources(message.content)[0]
            sources = []
        message = Message(role=message.role, content=content)
        if message.role == "user":
            command = message.content.strip().lower()
            omit_reply = command.startswith("/")
            if command in CONTROL_SETTINGS:
                for name, value in CONTROL_SETTINGS[command].items():
                    setattr(session, name, value)
            if omit_reply:
                continue
        elif message.role == "assistant" and omit_reply:
            continue
        turns = {}
        for source in sources:
            turns.setdefault(source["turn_id"], []).append(source)
        for turn_sources in turns.values():
            formatted = msp.format_search_data_for_prompt(json.dumps({
                "fetched_pages": [source["source"] for source in turn_sources]}))
            session.history.append({"role": "system", "content":
                "Prior web search context:\n"
                f"Retrieved at: {turn_sources[0]['retrieved_at']} (archived evidence, not a new lookup).\n" + formatted})
        session.history.append(message.model_dump())
    if session.bridge_evidence.damaged or session.bridge_evidence.over_limit:
        session.history.append({"role": "system", "content":
            "MSP evidence retention note:\nSome earlier evidence blocks were damaged or exceeded size limits "
            "and were not restored. Do not assume their source passages are available."})
    return session


def context_size_report(session: msp.ChatSession) -> str:
    """Measure this request's history without invoking inference or a tokenizer."""
    total = sum(len(message["content"]) for message in session.history)
    evidence_chars = sum(len(message["content"]) for message in session.history
                         if message["role"] == "system"
                         and message["content"].startswith("Prior web search context:\n"))
    window = studio_context_window()
    return (
        "Current supplied context (message text only):\n\n"
        f"Studio history received: {session.bridge_wire_chars:,} characters, including encoded evidence.\n\n"
        f"MSP restored history: {total:,} characters (~{(total + 3) // 4:,} tokens, rough estimate).\n\n"
        f"Restored evidence: {evidence_chars:,} characters; dialogue and other context: {total - evidence_chars:,} characters.\n\n"
        + (f"Loaded model context window: {window:,} tokens.\n\n" if window else
           "Loaded model context window: unavailable.\n\n")
        + "Token estimate uses 4 characters per token, not the model tokenizer. "
        "Excludes the current command, MSP answer instructions, chat-template overhead and reply tokens; "
        "this is not an exact inference prompt size or remaining capacity."
    )


def memory_user_report(session: msp.ChatSession, expected: str) -> str:
    """Inspect memory text deterministically; never assign or authenticate an ID."""
    username_pattern = r"[A-Za-z0-9_.@-]{1,128}"
    if expected and not re.fullmatch(username_pattern, expected):
        return "Usage: /user [username] (1–128 letters, digits, underscores, dots, @ or hyphens)."
    identifiers: set[str] = set()
    invalid = False
    for message in session.history:
        if message["role"] != "system":
            continue
        # Studio composes account memory inside <agents_md>. Ignore ordinary
        # dialogue, command arguments and unrelated system-prompt labels.
        for block in re.findall(r"<agents_md>\s*(.*?)\s*</agents_md>", message["content"], flags=re.S):
            for line in block.splitlines():
                if not re.match(r"\s*MSP_USER_ID\b", line):
                    continue
                match = re.fullmatch(r"\s*MSP_USER_ID\s*=\s*(" + username_pattern + r")\s*", line)
                if match:
                    identifiers.add(match[1])
                else:
                    invalid = True
    note = "This is an editable memory label, not an authenticated identity. No user setting was changed."
    if invalid:
        return "Invalid MSP_USER_ID marker in Studio memory. Use one plain line such as MSP_USER_ID=stan.\n\n" + note
    if len(identifiers) > 1:
        return "Conflicting MSP_USER_ID markers received in Studio memory. Keep one consistent user label.\n\n" + note
    if not identifiers:
        return ("No MSP_USER_ID marker received through Studio memory. In this account's Chat settings, "
                "enable Use memory in chats and save a plain line such as MSP_USER_ID=stan, then retry.\n\n" + note)
    actual = next(iter(identifiers))
    result = f"Memory user ID: `{actual}`."
    if expected:
        result += "\n\n" + (f"MATCH: received the expected user ID `{expected}`." if actual == expected
                                 else f"MISMATCH: expected `{expected}`, but memory supplied `{actual}`.")
    return result + "\n\n" + note


def evidence_roundtrip_probe(messages: list[Message], mode: str) -> str:
    """Opt-in wire-format experiment, using synthetic text and no server store.

    A successful check proves the raw assistant message reached this request.
    It does not prove visual hiding, long-context retention, or confidentiality.
    """
    if mode == "seed":
        payload = {
            "schema": "msp-evidence-probe-v1", "nonce": uuid4().hex,
            "excerpt": "The calibration lantern is violet.",
        }
        encoded = base64.b64encode(json.dumps(payload, separators=(",", ":")).encode()).decode()
        return (
            "Synthetic evidence probe added. Send `/evidence-test check` next. "
            "The encoded comment below should be invisible in the rendered answer. "
            "No real search evidence or private information is included.\n\n"
            f"<!-- MSP_EVIDENCE_PROBE_V1:{encoded} -->"
        )
    if mode not in {"", "check"}:
        return "Usage: /evidence-test seed|check"
    found = 0
    for message in messages:
        if message.role != "assistant":
            continue
        for encoded in re.findall(r"<!-- MSP_EVIDENCE_PROBE_V1:([A-Za-z0-9+/=]{1,4096}) -->", message.content):
            try:
                payload = json.loads(base64.b64decode(encoded, validate=True))
                if (isinstance(payload, dict) and payload.get("schema") == "msp-evidence-probe-v1"
                        and re.fullmatch(r"[0-9a-f]{32}", str(payload.get("nonce", "")))
                        and payload.get("excerpt") == "The calibration lantern is violet."):
                    found += 1
            except (ValueError, UnicodeError):
                continue
    if found:
        return (f"PASS: recovered synthetic evidence from {found} earlier assistant message block(s). "
                "Studio returned the encoded text to MSP in this request. "
                "This is a transport test, not evidence storage or user authentication.")
    return ("NOT RECEIVED: no valid evidence probe found in earlier assistant messages. "
            "Run /evidence-test seed in this chat first. If you already did, Studio may have "
            "removed or excluded the comment from the context it sent.")


def dispatch(session: msp.ChatSession, text: str) -> str | None:
    parts = text.split(maxsplit=1)
    command = parts[0].lower()
    argument = parts[1] if len(parts) > 1 else ""
    text = command + (" " + argument if argument else "") if text.startswith("/") else text
    if command in {"/?", "/help"}:
        return STUDIO_HELP
    if command == "/user":
        return memory_user_report(session, argument.strip())
    if command == "/evidence":
        if argument not in {"", "show"}:
            return "Usage: /evidence [show]"
        return context_size_report(session) + "\n\n" + session.bridge_evidence.report(full=argument == "show")
    if command in {"/lock", "/unlock"}:
        return "MSP lock/unlock commands are not used through Studio. Access is managed by Studio and the local bridge."
    if command == "/llm-reload":
        if argument:
            return "Usage: /llm-reload"
        from dotenv import load_dotenv
        load_dotenv(override=True)
        global _context_cache
        with _discovery_lock:
            _context_cache = None
        return "Studio connection settings reloaded from .env. They apply to the next inference request; no model was loaded or unloaded."
    if command == "/yahoo-sports":
        if not argument.strip():
            return "Usage: /yahoo-sports <query>"
        session.run_search_only(argument.strip(), "site:sports.yahoo.com")
        return None
    if text.startswith("/"):
        allowed = set(CONTROL_SETTINGS) | {
            "/decider", "/search", "/serper", "/arxiv", "/wiki", "/hn", "/stack",
            "/weather", "/news", "/finance", "/stocks",
        }
        if command not in allowed:
            return f"Unknown MSP command: {command}\n\n{STUDIO_HELP}"
        if command in CONTROL_SETTINGS and argument.strip():
            return f"Usage: {command}"
        session.handle_input(text)
        return None
    return session.run_query(text)


def run_pipeline(req: CompletionRequest) -> str:
    if req.model not in MODEL_ALIASES:
        raise HTTPException(404, f"Unknown model. Select {MODEL_ID}.")
    if req.tools or req.tool_choice not in (None, "none", "auto"):
        raise HTTPException(400, "Disable Studio tools for this provider; MSP owns research.")
    if any(msg.role not in {"system", "user", "assistant"} for msg in req.messages):
        raise HTTPException(400, "Only text system/user/assistant messages are supported.")
    if req.messages[-1].role != "user" or not req.messages[-1].content.strip():
        raise HTTPException(400, "The final message must be a nonempty user request.")
    if sum(len(msg.content) for msg in req.messages) > MAX_REQUEST_CHARS:
        raise HTTPException(413, "Conversation exceeds the local prototype limit.")
    if msp.SEARCH_DECIDER == "python":
        raise HTTPException(503, "This Studio prototype requires an LLM decider: planner or ollama.")
    # MSP has shared ranking/model state: serialize the prototype, with bounded
    # admission rather than accumulating requests in an unbounded work queue.
    if not _pipeline_lock.acquire(blocking=False):
        raise HTTPException(429, "MSP is processing another request. Try again shortly.")
    output = io.StringIO()
    output_token = msp.OUTPUT_CONTEXT.set(output)
    token = None
    try:
        text = unpack_sources(req.messages[-1].content)[0].strip()
        if not text:
            raise HTTPException(400, "The request has no text outside evidence carriers.")
        parts = text.split(maxsplit=1)
        if parts[0].lower() == "/evidence-test":
            # Inspect the original wire history: normal session reconstruction
            # omits slash-command exchanges, including this probe's seed reply.
            return evidence_roundtrip_probe(req.messages[:-1], parts[1].strip() if len(parts) > 1 else "")
        session = session_from_transcript(req.messages[:-1])
        # Commands which do not infer also work before model configuration.
        if not text.startswith("/") or text.split()[0].lower() == "/decider":
            try:
                provider = StudioInference(req)
            except ValueError as exc:
                raise HTTPException(503, str(exc)) from exc
            token = msp.CHAT_PROVIDER_CONTEXT.set(provider)
        answer = dispatch(session, text)
        captured = output.getvalue().strip()
        if text.startswith("/"):
            return answer or captured or "Command completed."
        if not session.llm_enabled:
            visible = captured or "Final answer model is disabled. Use /llm-on to enable it."
            return attach_turn_evidence(session, visible, text)
        if answer is None:
            raise RuntimeError("MSP did not produce an answer; inspect the local pipeline log.")
        if session.verbose_output or session.prompt_debug:
            if captured and answer and captured.endswith(answer):
                diagnostics = captured[:-len(answer)].rstrip()
                # Studio renders Markdown: plain newlines collapse into spaces.
                # Preserve diagnostic line breaks and start the answer paragraph
                # separately, keeping the answer's own Markdown unchanged.
                answer = msp.preserve_markdown_line_breaks(diagnostics) + "\n\n" + answer
            else:
                answer = captured or answer
        return attach_turn_evidence(session, answer, text)
    finally:
        if token is not None:
            msp.CHAT_PROVIDER_CONTEXT.reset(token)
        msp.OUTPUT_CONTEXT.reset(output_token)
        _pipeline_lock.release()


def attach_turn_evidence(session: msp.ChatSession, answer: str, question: str) -> str:
    """Append only newly retrieved prepared sources, never cumulative history."""
    if not session.last_search_result:
        return answer
    data = msp.parse_search_data_for_prompt(session.last_search_result)
    pages = [page for page in data["fetched_pages"] if msp.is_prompt_source(page)][:5]
    carriers, skipped = pack_sources(pages, question, session.last_search_query or question)
    if skipped:
        answer += f"\n\nMSP evidence note: {skipped} source block(s) could not be retained within transfer limits."
    return answer + ("\n\n" + carriers if carriers else "")


@app.post("/v1/chat/completions", dependencies=[Depends(authorize)])
def completions(req: CompletionRequest, x_msp_inference: str | None = Header(default=None)):
    if x_msp_inference:
        raise HTTPException(508, "Inference request routed back to MSP; check Studio routing.")
    try:
        answer = run_pipeline(req)
    except HTTPException:
        raise
    except Exception:
        logger.exception("MSP bridge request failed")
        return JSONResponse(status_code=502, content={"error": {
            "message": "MSP/Studio processing failed. Inspect the bridge terminal log.",
            "type": "upstream_error", "code": "msp_pipeline_failed"}})
    common = {"id": "chatcmpl-" + uuid4().hex, "created": int(time.time()), "model": req.model}
    if not req.stream:
        return {**common, "object": "chat.completion", "choices": [{"index": 0,
                "message": {"role": "assistant", "content": answer}, "finish_reason": "stop"}]}

    def events():
        # Buffered SSE compatibility, not token streaming. Research and answer
        # finish before headers; errors can therefore still use HTTP status codes.
        for delta, finish in [({"role": "assistant", "content": answer}, None), ({}, "stop")]:
            yield "data: " + json.dumps({**common, "object": "chat.completion.chunk",
                    "choices": [{"index": 0, "delta": delta, "finish_reason": finish}]}) + "\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(events(), media_type="text/event-stream")
