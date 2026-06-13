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


def test_search_force_command_sets_forced_mode(monkeypatch, capsys) -> None:
    monkeypatch.setattr(websearchMCP, "UNLOCK_PASSWORDS", ())
    session = websearchMCP.ChatSession(rich_output=False)

    assert session.handle_input("/search-force") is True

    output = capsys.readouterr().out
    assert "[System] Search forced. Search decider will be bypassed." in output
    assert session.search_enabled is True
    assert session.search_forced is True


def test_search_on_and_off_clear_forced_mode(monkeypatch) -> None:
    monkeypatch.setattr(websearchMCP, "UNLOCK_PASSWORDS", ())
    session = websearchMCP.ChatSession(rich_output=False)
    session.search_forced = True

    assert session.handle_input("/search-on") is True
    assert session.search_enabled is True
    assert session.search_forced is False

    session.search_forced = True
    assert session.handle_input("/search-off") is True
    assert session.search_enabled is False
    assert session.search_forced is False


def test_fetched_html_error_reason_detects_cloudflare_footer() -> None:
    html = """
    <html><head><title>Attention Required! | Cloudflare</title></head>
    <body>
      <script>footer-ip-reveal");document.getElementById("cf-footer-ip")</script>
      Cloudflare Ray ID: abc123
    </body></html>
    """

    assert websearchMCP.fetched_html_error_reason(html) == "Cloudflare footer"


def test_fetched_html_error_reason_detects_common_server_errors() -> None:
    html = "<html><head><title>502 Bad Gateway</title></head><body>nginx</body></html>"

    assert websearchMCP.fetched_html_error_reason(html) == "server error page"


def test_fetched_page_quality_rejects_extracted_challenge_text() -> None:
    page = {
        "content": (
            "Checking if the site connection is secure. Cloudflare Ray ID abc123. "
            "Please enable JavaScript and cookies to continue. " * 8
        )
    }

    ok, reason = websearchMCP.fetched_page_quality(page)

    assert ok is False
    assert "boilerplate marker" in reason
