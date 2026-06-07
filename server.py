from __future__ import annotations

import io
import threading
from contextlib import asynccontextmanager, redirect_stderr, redirect_stdout
from pathlib import Path
from uuid import uuid4

from fastapi import Cookie, FastAPI, Response, status
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


@asynccontextmanager
async def lifespan(app: FastAPI):
    with chat_lock:
        preload_models()
    yield


app = FastAPI(title="MisterSmartyPants", lifespan=lifespan)


class ChatRequest(BaseModel):
    message: str


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


def run_chat_job(job_id: str, session: ChatSession, message: str) -> None:
    buffer = io.StringIO()
    error: str | None = None
    with chat_lock:
        try:
            with redirect_stdout(buffer), redirect_stderr(buffer):
                session.handle_input(message)
        except Exception as exc:
            output = buffer.getvalue()
            if output and not output.endswith("\n"):
                output += "\n"
            output += f"[Server error] {type(exc).__name__}: {exc}\n"
            buffer = io.StringIO(output)
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
