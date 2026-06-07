from __future__ import annotations

import io
import threading
from contextlib import asynccontextmanager, redirect_stderr, redirect_stdout
from pathlib import Path
from uuid import uuid4

from fastapi import Cookie, FastAPI, Response
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

from websearchMCP import ChatSession, preload_models

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"

sessions: dict[str, ChatSession] = {}
sessions_lock = threading.Lock()
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


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/new")
def new_chat(response: Response, msp_session: str | None = Cookie(default=None)) -> dict[str, str]:
    _, session = get_session(msp_session, response)
    session.history.clear()
    return {"status": "cleared"}


@app.post("/api/chat")
def chat(req: ChatRequest, response: Response, msp_session: str | None = Cookie(default=None)) -> JSONResponse:
    message = req.message.strip()
    if not message:
        return JSONResponse({"output": ""})

    _, session = get_session(msp_session, response)
    buffer = io.StringIO()
    with chat_lock:
        try:
            with redirect_stdout(buffer), redirect_stderr(buffer):
                session.handle_input(message)
        except Exception as exc:
            output = buffer.getvalue()
            if output and not output.endswith("\n"):
                output += "\n"
            output += f"[Server error] {type(exc).__name__}: {exc}\n"
            return JSONResponse({"output": output, "error": str(exc)}, status_code=200)
    return JSONResponse({"output": buffer.getvalue()})
