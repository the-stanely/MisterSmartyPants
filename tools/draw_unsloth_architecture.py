"""Generate the editable integration SVG using only Python's standard library.

Run from any directory: python tools/draw_unsloth_architecture.py
Render the SVG to PNG with a browser or an SVG renderer for the README artifact.
"""
from html import escape
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
parts = ['''<svg xmlns="http://www.w3.org/2000/svg" width="1600" height="1100" viewBox="0 0 1600 1100">
<defs><marker id="arrow" markerWidth="10" markerHeight="10" refX="8" refY="4" orient="auto"><path d="M0,0 L8,4 L0,8" fill="none" stroke="#234769" stroke-width="1.5"/></marker></defs>
<rect width="1600" height="1100" fill="#ffffff"/>
<style>text{font-family:Segoe UI,Arial,sans-serif;fill:#14304d}.title{font-size:42px;font-weight:700}.heading{font-size:23px;font-weight:700}.body{font-size:19px}.label{font-size:17px;font-weight:600}.small{font-size:17px}</style>''']


def text(x, y, lines, css="body", line_height=29):
    for i, line in enumerate(lines):
        parts.append(f'<text x="{x}" y="{y+i*line_height}" class="{css}">{escape(line)}</text>')


def box(x, y, w, h, title, lines, fill, stroke):
    parts.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="15" fill="{fill}" stroke="{stroke}"/>')
    text(x+22, y+37, [title], "heading")
    text(x+22, y+72, lines)


def arrow(path, dashed=False):
    dash = ' stroke-dasharray="9 6"' if dashed else ''
    parts.append(f'<path d="{path}" fill="none" stroke="#234769" stroke-width="2.5" marker-end="url(#arrow)"{dash}/>')


text(40, 61, ["MisterSmartyPants + Unsloth Studio"], "title")
text(42, 99, ["Studio owns the chat. MSP orchestrates research. The loaded local model decides and answers."], "body")

box(35, 145, 440, 600, "Unsloth Studio · chat & history", [], "#eef6ff", "#a8cfee")
box(57, 207, 396, 149, "Browser chat", ["Owner or managed account", "Select the msp connector", "Local browser or Studio LAN access"], "#ffffff", "#a8cfee")
box(57, 388, 396, 151, "Studio backend", ["Account login, memory and chats", "Stores replies and source envelopes", "Sends history; manages trimming"], "#ffffff", "#a8cfee")
box(57, 573, 396, 140, "Per-account connector", ["OpenAI Chat Completions", "http://127.0.0.1:8081/v1", "Model: msp"], "#ffffff", "#a8cfee")
arrow("M255 356 V386")
arrow("M255 539 V571")

box(540, 145, 510, 600, "MisterSmartyPants · loopback :8081", [], "#eff9ef", "#a5cea9")
box(562, 207, 466, 149, "1  Reconstruct this chat", ["Restore controls and intact evidence", "Omit slash-command exchanges", "No MSP conversation database"], "#ffffff", "#a5cea9")
box(562, 388, 466, 116, "2  Existing search decision", ["Dialogue only → local model", "ANSWER skips new retrieval"], "#ffffff", "#a5cea9")
box(562, 537, 466, 176, "3  SEARCH: existing MSP pipeline", ["Query → search → initial ranking", "Fetch pages / source API extraction", "Select sources; optional summaries", "Prepared passages + provenance"], "#ffffff", "#a5cea9")
arrow("M795 356 V386")
arrow("M795 504 V535")
text(810, 526, ["SEARCH"], "small")
arrow("M453 630 H505 V280 H560")
text(478, 598, ["history"], "small")

box(1120, 145, 445, 340, "Unsloth Studio · inference :8888", [], "#fff4e8", "#e6bf99")
box(1142, 207, 401, 242, "Actual loaded local model", ["Example: Gemma 4 E4B GGUF", "Same model for decider + answer", "POST /v1/chat/completions", "Auto-select loaded local model", "Never msp or default", "No tools / provider recursion"], "#ffffff", "#e6bf99")
arrow("M1028 433 H1090 V300 H1140")
text(1057, 382, ["decide"], "small")

box(1120, 537, 445, 208, "4  Build the final answer", ["MSP sends dialogue + readable sources", "Studio runs answer inference", "MSP returns answer + source links", "Append only new source envelopes"], "#f4efff", "#c7b3ef")
arrow("M1028 625 H1118")
arrow("M1028 475 H1070 V565 H1118")
text(1045, 519, ["ANSWER"], "small")
arrow("M1340 537 V487")
text(1360, 515, ["answer inference"], "small")

arrow("M1342 745 V794 H255 V747", True)
text(460, 784, ["Answer + independently encoded source blocks → Studio saves them with this chat"], "label")

box(35, 832, 740, 214, "Evidence travels with the conversation", ["Uncompressed JSON → base64 HTML comments + SHA-256", "Next turn: decode intact blocks into dated prior-search context", "Damaged blocks are discarded independently; no shared cache", "Studio trimming can remove evidence; /evidence inspects survivors"], "#eef6ff", "#a8cfee")
box(800, 832, 765, 214, "Context, discovery & development limits", ["/v1/models advertises the loaded model’s active context window", "128K tested context; 32768-token maximum output allowance", "One active MSP request; buffered SSE; text chat only", "Diagnostic replies stay in Studio history but are omitted by MSP"], "#eff9ef", "#a5cea9")
text(40, 1080, ["Solid arrows: request flow     Dashed arrow: reply / evidence return     Both services run on the same host"], "small")
parts.append('</svg>')
(ROOT / "MisterSmartyPants-Unsloth-Diagram.svg").write_text("\n".join(parts), encoding="utf-8")
