from __future__ import annotations

import io
import sys
import threading
import time
from contextlib import asynccontextmanager, redirect_stderr, redirect_stdout
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from fastapi import Cookie, FastAPI, Request, Response, status
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

from websearchMCP import ChatSession, preload_models

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"

sessions: dict[str, ChatSession] = {}
sessions_lock = threading.Lock()
jobs: dict[str, dict[str, object]] = {}
jobs_lock = threading.Lock()
chat_lock = threading.Lock()
not_found_lock = threading.Lock()
not_found_streaks: dict[str, int] = {}
blocked_until: dict[str, float] = {}
NOT_FOUND_BLOCK_THRESHOLD = 3
NOT_FOUND_BLOCK_SECONDS = 10 * 60


@asynccontextmanager
async def lifespan(app: FastAPI):
    with chat_lock:
        preload_models()
    yield


app = FastAPI(title="MisterSmartyPants", lifespan=lifespan)


class ChatRequest(BaseModel):
    message: str



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

def get_session(session_id: str | None, response: Response) -> tuple[str, ChatSession]:
    if not session_id:
        session_id = uuid4().hex
        response.set_cookie("msp_session", session_id, httponly=True, samesite="lax")
    with sessions_lock:
        session = sessions.get(session_id)
        if session is None:
            session = ChatSession(rich_output=False)
            sessions[session_id] = session
    return session_id, session


@app.get("/")
def index() -> FileResponse:
    response = FileResponse(STATIC_DIR / "index.html")
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    return response


@app.get("/favicon.ico")
def favicon() -> FileResponse:
    return FileResponse(STATIC_DIR / "favicon.ico")


@app.get("/robots.txt")
def robots() -> FileResponse:
    return FileResponse(STATIC_DIR / "robots.txt", media_type="text/plain")


@app.get("/sitemap.xml")
def sitemap() -> FileResponse:
    return FileResponse(STATIC_DIR / "sitemap.xml", media_type="application/xml")


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/new")
def new_chat(response: Response, msp_session: str | None = Cookie(default=None)) -> dict[str, str]:
    _, session = get_session(msp_session, response)
    session.history.clear()
    return {"status": "cleared"}


class LiveJobBuffer(io.TextIOBase):
    def __init__(self, job_id: str) -> None:
        super().__init__()
        self.job_id = job_id
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

def run_chat_job(job_id: str, session: ChatSession, message: str) -> None:
    buffer = LiveJobBuffer(job_id)
    error: str | None = None
    with chat_lock:
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
            job["output"] = buffer.getvalue()
            job["error"] = error

@app.post("/api/chat")
def chat(req: ChatRequest, response: Response, msp_session: str | None = Cookie(default=None)) -> dict[str, object]:
    message = req.message.strip()
    if not message:
        return {"done": True, "output": ""}

    session_id, session = get_session(msp_session, response)
    job_id = uuid4().hex
    with jobs_lock:
        jobs[job_id] = {"session_id": session_id, "done": False, "output": "", "error": None}

    thread = threading.Thread(target=run_chat_job, args=(job_id, session, message), daemon=True)
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
