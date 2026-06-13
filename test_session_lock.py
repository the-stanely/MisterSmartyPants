from __future__ import annotations

import websearchMCP


def test_session_starts_unlocked_without_passwords(monkeypatch) -> None:
    monkeypatch.setattr(websearchMCP, "UNLOCK_PASSWORDS", ())

    session = websearchMCP.ChatSession(rich_output=False)

    assert session.locked is False


def test_session_unlocks_with_configured_password(monkeypatch, capsys) -> None:
    monkeypatch.setattr(websearchMCP, "UNLOCK_PASSWORDS", ("alpha", "beta"))
    session = websearchMCP.ChatSession(rich_output=False)

    assert session.locked is True
    assert session.handle_input("/unlock beta") is True

    output = capsys.readouterr().out
    assert "[System] Unlocked." in output
    assert session.locked is False


def test_locked_session_rejects_regular_input(monkeypatch, capsys) -> None:
    monkeypatch.setattr(websearchMCP, "UNLOCK_PASSWORDS", ("alpha",))
    session = websearchMCP.ChatSession(rich_output=False)

    assert session.handle_input("hello") is True

    output = capsys.readouterr().out
    assert "[System] Locked. Use /unlock <password>." in output
    assert session.locked is True


def test_preserve_markdown_line_breaks_skips_code_fences() -> None:
    source = "first line\nsecond line\n\n```text\ncode line\n```\nafter"

    rendered = websearchMCP.preserve_markdown_line_breaks(source)

    assert "first line  \nsecond line  " in rendered
    assert "```text\ncode line\n```" in rendered
    assert rendered.endswith("after  ")


def test_search_force_command_runs_full_pipeline_with_force_flag(monkeypatch) -> None:
    monkeypatch.setattr(websearchMCP, "UNLOCK_PASSWORDS", ())
    calls = []

    def fake_run_query(self, query: str, force_search: bool = False) -> None:
        calls.append((query, force_search))

    monkeypatch.setattr(websearchMCP.ChatSession, "run_query", fake_run_query)
    session = websearchMCP.ChatSession(rich_output=False)

    assert session.handle_input("/search-force current AI news") is True

    assert calls == [("current AI news", True)]


def test_search_force_command_requires_query(monkeypatch, capsys) -> None:
    monkeypatch.setattr(websearchMCP, "UNLOCK_PASSWORDS", ())
    session = websearchMCP.ChatSession(rich_output=False)

    assert session.handle_input("/search-force") is True

    output = capsys.readouterr().out
    assert "[System] Usage: /search-force <query>" in output
