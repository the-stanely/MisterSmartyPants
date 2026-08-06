from __future__ import annotations

import io
import base64
import json
import os
import sys
import threading
import time
from contextlib import asynccontextmanager, redirect_stderr, redirect_stdout
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from fastapi import Cookie, FastAPI, HTTPException, Request, Response, status
from fastapi.encoders import jsonable_encoder
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel
from fido2.server import Fido2Server
from fido2.webauthn import (
    AttestedCredentialData,
    AuthenticatorAttachment,
    PublicKeyCredentialRpEntity,
    PublicKeyCredentialUserEntity,
    UserVerificationRequirement,
)

from websearchMCP import ChatSession, preload_models

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
PASSKEYS_FILE = BASE_DIR / "passkeys.json"
PASSKEY_CHALLENGE_SECONDS = 5 * 60
SESSION_COOKIE_MAX_AGE_SECONDS = int(os.getenv("SESSION_COOKIE_MAX_AGE_SECONDS", str(30 * 24 * 60 * 60)))
SESSION_COOKIE_SECURE = os.getenv("SESSION_COOKIE_SECURE", "0").strip().lower() in {"1", "true", "yes", "on"}

sessions: dict[str, ChatSession] = {}
session_locks: dict[str, threading.Lock] = {}
sessions_lock = threading.Lock()
jobs: dict[str, dict[str, object]] = {}
jobs_lock = threading.Lock()
preload_lock = threading.Lock()
not_found_lock = threading.Lock()
not_found_streaks: dict[str, int] = {}
blocked_until: dict[str, float] = {}
NOT_FOUND_BLOCK_THRESHOLD = 3
NOT_FOUND_BLOCK_SECONDS = 10 * 60


@asynccontextmanager
async def lifespan(app: FastAPI):
    with preload_lock:
        preload_models()
    yield


app = FastAPI(title="MisterSmartyPants", lifespan=lifespan)


class ChatRequest(BaseModel):
    message: str


class PasskeyResponse(BaseModel):
    credential: dict[str, object]



def server_log(message: str) -> None:
    timestamp = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S %Z%z")
    print(f"[{timestamp}] {message}", file=sys.__stdout__, flush=True)


def request_ip(request: Request) -> str:
    cf_ip = (request.headers.get("cf-connecting-ip") or "").strip()
    if cf_ip:
        return cf_ip
    forwarded_for = (request.headers.get("x-forwarded-for") or "").split(",", 1)[0].strip()
    if forwarded_for:
        return forwarded_for
    return request.client.host if request.client else "unknown"


@app.middleware("http")
async def block_repeated_not_found(request: Request, call_next):
    ip = request_ip(request)
    now = time.monotonic()
    with not_found_lock:
        until = blocked_until.get(ip, 0.0)
        if until > now:
            remaining = max(0, int(until - now))
            server_log(f"BLOCKED deny ip={ip} method={request.method} path={request.url.path} remaining={remaining}s")
            return JSONResponse({"error": "Temporarily blocked"}, status_code=status.HTTP_403_FORBIDDEN)
        if until:
            blocked_until.pop(ip, None)
            not_found_streaks.pop(ip, None)
            server_log(f"BLOCK expired ip={ip}")

    response = await call_next(request)
    status_code = response.status_code
    with not_found_lock:
        if status_code == status.HTTP_404_NOT_FOUND:
            streak = not_found_streaks.get(ip, 0) + 1
            not_found_streaks[ip] = streak
            server_log(f"REQUEST ip={ip} method={request.method} path={request.url.path} status={status_code} 404_streak={streak}")
            if streak >= NOT_FOUND_BLOCK_THRESHOLD:
                blocked_until[ip] = now + NOT_FOUND_BLOCK_SECONDS
                not_found_streaks[ip] = 0
                server_log(
                    f"BLOCK start ip={ip} duration={NOT_FOUND_BLOCK_SECONDS}s "
                    f"reason={NOT_FOUND_BLOCK_THRESHOLD}_consecutive_404s"
                )
        else:
            not_found_streaks.pop(ip, None)
            server_log(f"REQUEST ip={ip} method={request.method} path={request.url.path} status={status_code}")
    return response

def get_session(session_id: str | None, response: Response) -> tuple[str, ChatSession, threading.Lock]:
    if not session_id:
        session_id = uuid4().hex
    # Refresh expiry on activity and upgrade pre-existing session cookies to the
    # persistent form after deployment.
    response.set_cookie(
        "msp_session",
        session_id,
        max_age=SESSION_COOKIE_MAX_AGE_SECONDS,
        httponly=True,
        samesite="lax",
        secure=SESSION_COOKIE_SECURE,
    )
    with sessions_lock:
        session = sessions.get(session_id)
        if session is None:
            session = ChatSession(rich_output=False)
            sessions[session_id] = session
            session_locks[session_id] = threading.Lock()
        session_lock = session_locks.setdefault(session_id, threading.Lock())
    return session_id, session, session_lock


@app.get("/api/session")
def session_status(response: Response, msp_session: str | None = Cookie(default=None)) -> dict[str, bool]:
    _, session, session_lock = get_session(msp_session, response)
    with session_lock:
        return {"has_server_context": bool(session.history), "locked": session.locked}


def base64url_encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def base64url_decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def passkey_rp_id(request: Request) -> str:
    configured = os.getenv("PASSKEY_RP_ID", "").strip().lower()
    if configured:
        return configured
    return request.url.hostname or "localhost"


def passkey_server(request: Request) -> Fido2Server:
    rp_id = passkey_rp_id(request)
    return Fido2Server(PublicKeyCredentialRpEntity(id=rp_id, name="MisterSmartyPants"))


def load_passkeys(rp_id: str) -> list[AttestedCredentialData]:
    if not PASSKEYS_FILE.exists():
        return []
    try:
        records = json.loads(PASSKEYS_FILE.read_text(encoding="utf-8"))
        credentials = []
        for record in records:
            if record.get("rp_id") != rp_id:
                continue
            credential, remaining = AttestedCredentialData.unpack_from(base64url_decode(record["credential"]))
            if remaining:
                raise ValueError("Passkey credential has trailing data.")
            credentials.append(credential)
        return credentials
    except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        raise RuntimeError(f"Cannot read passkey store: {exc}") from exc


def save_passkey(rp_id: str, credential: AttestedCredentialData) -> None:
    records: list[dict[str, str]] = []
    if PASSKEYS_FILE.exists():
        records = json.loads(PASSKEYS_FILE.read_text(encoding="utf-8"))
    encoded = base64url_encode(bytes(credential))
    if not any(record.get("credential") == encoded for record in records):
        records.append({"rp_id": rp_id, "credential": encoded})
        temporary = PASSKEYS_FILE.with_suffix(".tmp")
        temporary.write_text(json.dumps(records, indent=2) + "\n", encoding="utf-8")
        temporary.replace(PASSKEYS_FILE)


@app.get("/")
def index() -> FileResponse:
    response = FileResponse(STATIC_DIR / "index.html")
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    return response


@app.get("/favicon.ico")
def favicon() -> FileResponse:
    return FileResponse(STATIC_DIR / "favicon.ico")


@app.get("/manifest.webmanifest")
def web_app_manifest() -> FileResponse:
    return FileResponse(STATIC_DIR / "manifest.webmanifest", media_type="application/manifest+json")


@app.get("/icon-192.png")
def icon_192() -> FileResponse:
    return FileResponse(STATIC_DIR / "icon-192.png", media_type="image/png")


@app.get("/icon-512-maskable.png")
def icon_512_maskable() -> FileResponse:
    return FileResponse(STATIC_DIR / "icon-512-maskable.png", media_type="image/png")


@app.get("/robots.txt")
def robots() -> FileResponse:
    return FileResponse(STATIC_DIR / "robots.txt", media_type="text/plain")


@app.get("/sitemap.xml")
def sitemap() -> FileResponse:
    return FileResponse(STATIC_DIR / "sitemap.xml", media_type="application/xml")


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


def set_passkey_challenge(session: ChatSession, kind: str, state: object) -> None:
    challenges = getattr(session, "passkey_challenges", {})
    challenges[kind] = (time.monotonic() + PASSKEY_CHALLENGE_SECONDS, state)
    session.passkey_challenges = challenges


def take_passkey_challenge(session: ChatSession, kind: str) -> object:
    challenge = getattr(session, "passkey_challenges", {}).pop(kind, None)
    if challenge is None or challenge[0] < time.monotonic():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Passkey request expired. Try again.")
    return challenge[1]


@app.post("/api/passkey/register/options")
def passkey_register_options(request: Request, response: Response, msp_session: str | None = Cookie(default=None)) -> dict[str, object]:
    _, session, session_lock = get_session(msp_session, response)
    with session_lock:
        if session.locked:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Unlock with your password before adding a passkey.")
        rp_id = passkey_rp_id(request)
        options, state = passkey_server(request).register_begin(
            PublicKeyCredentialUserEntity(id=b"mistersmartypants", name="MisterSmartyPants", display_name="MisterSmartyPants"),
            credentials=load_passkeys(rp_id),
            user_verification=UserVerificationRequirement.REQUIRED,
            authenticator_attachment=AuthenticatorAttachment.PLATFORM,
        )
        set_passkey_challenge(session, "register", state)
        return {"publicKey": jsonable_encoder(dict(options.public_key))}


@app.post("/api/passkey/register/verify")
def passkey_register_verify(request: Request, payload: PasskeyResponse, response: Response, msp_session: str | None = Cookie(default=None)) -> dict[str, str]:
    _, session, session_lock = get_session(msp_session, response)
    with session_lock:
        if session.locked:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Session is locked.")
        try:
            auth_data = passkey_server(request).register_complete(take_passkey_challenge(session, "register"), payload.credential)
            if auth_data.credential_data is None:
                raise ValueError("Authenticator returned no credential data.")
            save_passkey(passkey_rp_id(request), auth_data.credential_data)
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Passkey registration failed: {exc}") from exc
    return {"status": "registered"}


@app.post("/api/passkey/unlock/options")
def passkey_unlock_options(request: Request, response: Response, msp_session: str | None = Cookie(default=None)) -> dict[str, object]:
    _, session, session_lock = get_session(msp_session, response)
    with session_lock:
        rp_id = passkey_rp_id(request)
        credentials = load_passkeys(rp_id)
        if not credentials:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="No passkey is registered for this site.")
        options, state = passkey_server(request).authenticate_begin(
            credentials=credentials,
            user_verification=UserVerificationRequirement.REQUIRED,
        )
        set_passkey_challenge(session, "unlock", state)
        return {"publicKey": jsonable_encoder(dict(options.public_key))}


@app.post("/api/passkey/unlock/verify")
def passkey_unlock_verify(request: Request, payload: PasskeyResponse, response: Response, msp_session: str | None = Cookie(default=None)) -> dict[str, str]:
    _, session, session_lock = get_session(msp_session, response)
    with session_lock:
        try:
            passkey_server(request).authenticate_complete(
                take_passkey_challenge(session, "unlock"), load_passkeys(passkey_rp_id(request)), payload.credential
            )
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Passkey verification failed.") from exc
        session.locked = False
        session.search_enabled = True
        session.search_forced = False
    return {"status": "unlocked"}


@app.post("/api/new")
def new_chat(response: Response, msp_session: str | None = Cookie(default=None)) -> dict[str, str]:
    _, session, session_lock = get_session(msp_session, response)
    with session_lock:
        session.history.clear()
    return {"status": "cleared"}


class LiveJobBuffer(io.TextIOBase):
    def __init__(self, job_id: str, publish_live: bool) -> None:
        super().__init__()
        self.job_id = job_id
        self.publish_live = publish_live
        self.parts: list[str] = []
        self.lock = threading.Lock()

    def writable(self) -> bool:
        return True

    def write(self, text: str) -> int:
        if not text:
            return 0
        with self.lock:
            self.parts.append(text)
            output = "".join(self.parts)
        if self.publish_live:
            with jobs_lock:
                job = jobs.get(self.job_id)
                if job is not None:
                    job["output"] = output
        return len(text)

    def flush(self) -> None:
        return None

    def getvalue(self) -> str:
        with self.lock:
            return "".join(self.parts)


def concise_output(output: str) -> str:
    marker = "[Assistant]"
    if marker not in output:
        return output
    return output.rsplit(marker, 1)[1].lstrip("\r\n")

def run_chat_job(job_id: str, session: ChatSession, session_lock: threading.Lock, message: str) -> None:
    buffer = LiveJobBuffer(job_id, publish_live=session.verbose_output)
    error: str | None = None
    with session_lock:
        try:
            with redirect_stdout(buffer), redirect_stderr(buffer):
                session.handle_input(message)
        except Exception as exc:
            output = buffer.getvalue()
            if output and not output.endswith("\n"):
                buffer.write("\n")
            buffer.write(f"[Server error] {type(exc).__name__}: {exc}\n")
            error = str(exc)

    with jobs_lock:
        job = jobs.get(job_id)
        if job is not None:
            job["done"] = True
            output = buffer.getvalue()
            job["output"] = output if session.verbose_output else concise_output(output)
            job["error"] = error

@app.post("/api/chat")
def chat(req: ChatRequest, response: Response, msp_session: str | None = Cookie(default=None)) -> dict[str, object]:
    message = req.message.strip()
    if not message:
        return {"done": True, "output": ""}

    session_id, session, session_lock = get_session(msp_session, response)
    job_id = uuid4().hex
    with jobs_lock:
        jobs[job_id] = {"session_id": session_id, "done": False, "output": "", "error": None}

    thread = threading.Thread(target=run_chat_job, args=(job_id, session, session_lock, message), daemon=True)
    thread.start()
    return {"job_id": job_id, "done": False}


@app.get("/api/chat/{job_id}")
def chat_status(job_id: str, msp_session: str | None = Cookie(default=None)) -> JSONResponse:
    if not msp_session:
        return JSONResponse({"error": "Job not found"}, status_code=status.HTTP_404_NOT_FOUND)

    with jobs_lock:
        job = jobs.get(job_id)
        if job is None or job.get("session_id") != msp_session:
            return JSONResponse({"error": "Job not found"}, status_code=status.HTTP_404_NOT_FOUND)
        return JSONResponse({"done": job["done"], "output": job["output"], "error": job["error"]})
