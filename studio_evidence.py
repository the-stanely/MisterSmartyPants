"""Bounded, uncompressed source envelopes carried by Studio assistant history.

SHA-256 detects accidental damage; it is not a signature or an identity check.
Each source is independently recoverable. There is no database or shared cache.
"""
from __future__ import annotations

import base64
from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import json
import re
from urllib.parse import urlsplit
from uuid import uuid4

MAX_SOURCE_BYTES = 64 * 1024
MAX_TURN_BYTES = 256 * 1024
MAX_RESTORED_BYTES = 1024 * 1024
MAX_MESSAGE_CHARS = 1024 * 1024
MAX_REQUEST_CHARS = 2 * 1024 * 1024
PREFIX = "<!-- MSP_EVIDENCE_V1:"
_BLOCK = re.compile(r"<!-- MSP_EVIDENCE_V1:([0-9a-f]{64}):([A-Za-z0-9+/=]+) -->")
_SOURCE_KEYS = {"title", "url", "content", "published", "author", "extractor"}
_PAYLOAD_KEYS = {"v", "turn_id", "source_index", "source_count", "retrieved_at", "question", "query", "source"}


def valid_payload(payload: object) -> bool:
    if not isinstance(payload, dict) or set(payload) != _PAYLOAD_KEYS:
        return False
    if type(payload["v"]) is not int or payload["v"] != 1:
        return False
    if not isinstance(payload["turn_id"], str) or not re.fullmatch(r"[0-9a-f]{32}", payload["turn_id"]):
        return False
    index, count = payload["source_index"], payload["source_count"]
    if type(index) is not int or type(count) is not int or not 1 <= index <= count <= 5:
        return False
    if any(not isinstance(payload[k], str) or len(payload[k]) > 4096 for k in ("question", "query")):
        return False
    if not isinstance(payload["retrieved_at"], str) or len(payload["retrieved_at"]) > 64:
        return False
    try:
        if datetime.fromisoformat(payload["retrieved_at"]).utcoffset() is None:
            return False
    except ValueError:
        return False
    source = payload["source"]
    if (not isinstance(source, dict) or not {"title", "url", "content", "extractor"} <= source.keys()
            or not source.keys() <= _SOURCE_KEYS or any(not isinstance(v, str) for v in source.values())):
        return False
    if not source["content"].rstrip().endswith("[END EXCERPT]"):
        return False
    if source["extractor"] != "trafilatura" and not source["extractor"].endswith("-api"):
        return False
    try:
        url = urlsplit(source["url"])
        if url.scheme not in {"http", "https"} or not url.hostname or url.username or url.password:
            return False
    except ValueError:
        return False
    # Prevent damaged/forged source boundaries from breaking MSP's formatter.
    if re.search(r"^(?:BEGIN|END) SOURCE \d+\s*$", source["content"], flags=re.M):
        return False
    return True


def pack_sources(pages: list[dict], question: str, query: str) -> tuple[str, int]:
    """Return carriers for this search only, plus the number not retained."""
    pages = pages[:5]
    turn_id = uuid4().hex
    retrieved_at = datetime.now(timezone.utc).isoformat()
    blocks = []
    skipped = 0
    used = 0
    for index, page in enumerate(pages, 1):
        source = {key: str(page.get(key) or "") for key in _SOURCE_KEYS if key in page}
        payload = {"v": 1, "turn_id": turn_id, "source_index": index,
                   "source_count": len(pages), "retrieved_at": retrieved_at,
                   "question": question[:4096], "query": query[:4096], "source": source}
        raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        if not valid_payload(payload) or len(raw) > MAX_SOURCE_BYTES or used + len(raw) > MAX_TURN_BYTES:
            skipped += 1
            continue
        digest = hashlib.sha256(raw).hexdigest()
        blocks.append(f"{PREFIX}{digest}:{base64.b64encode(raw).decode('ascii')} -->")
        used += len(raw)
    return "\n\n".join(blocks), skipped


def unpack_sources(text: str) -> tuple[str, list[tuple[dict, str, int]], int]:
    """Strip recognized carriers, recover intact sources, discard damaged ones.

    A missing terminator consumes only up to the next source's opening marker,
    so trimming one source does not prevent recovery of later intact sources.
    """
    positions = [m.start() for m in re.finditer(re.escape(PREFIX), text)]
    clean = []
    recovered = []
    damaged = 0
    cursor = 0
    for number, start in enumerate(positions):
        boundary = positions[number + 1] if number + 1 < len(positions) else len(text)
        close = text.find("-->", start, boundary)
        end = close + 3 if close >= 0 else boundary
        clean.append(text[cursor:start])
        cursor = end
        if end - start > 4 * ((MAX_SOURCE_BYTES + 2) // 3) + 128:
            damaged += 1
            continue
        match = _BLOCK.fullmatch(text[start:end])
        if not match:
            damaged += 1
            continue
        try:
            raw = base64.b64decode(match[2], validate=True)
            if len(raw) > MAX_SOURCE_BYTES or hashlib.sha256(raw).hexdigest() != match[1]:
                damaged += 1
                continue
            payload = json.loads(raw)
            if not valid_payload(payload):
                damaged += 1
                continue
            recovered.append((payload, match[1], len(raw)))
        except (ValueError, UnicodeError, RecursionError):
            damaged += 1
    clean.append(text[cursor:])
    return "".join(clean).strip(), recovered, damaged


@dataclass
class EvidenceState:
    entries: list[dict] = field(default_factory=list)
    damaged: int = 0
    over_limit: int = 0
    duplicates: int = 0
    total_bytes: int = 0
    _seen: dict[tuple[str, int], str] = field(default_factory=dict)

    def restore(self, text: str) -> tuple[str, list[dict]]:
        clean, recovered, damaged = unpack_sources(text)
        self.damaged += damaged
        added = []
        for payload, digest, size in recovered:
            identity = (payload["turn_id"], payload["source_index"])
            if identity in self._seen:
                if self._seen[identity] == digest:
                    self.duplicates += 1
                else:
                    self.damaged += 1
                continue
            if self.total_bytes + size > MAX_RESTORED_BYTES:
                self.over_limit += 1
                continue
            self._seen[identity] = digest
            self.total_bytes += size
            self.entries.append(payload)
            added.append(payload)
        return clean, added

    def report(self, full: bool = False) -> str:
        turns = {entry["turn_id"] for entry in self.entries}
        lines = [f"Retained evidence: {len(self.entries)} source block(s) across {len(turns)} research turn(s).",
                 f"Discarded damaged blocks: {self.damaged}. Over size limit: {self.over_limit}. "
                 f"Duplicate blocks ignored: {self.duplicates}."]
        if not self.entries:
            lines.append("No source evidence was restored from this request's chat history. "
                         "Earlier answers created before evidence retention have no payload.")
        for number, entry in enumerate(self.entries, 1):
            source = entry["source"]
            digest = self._seen[(entry["turn_id"], entry["source_index"])]
            lines.extend(["", f"{number}. {source['title']}", f"URL: {source['url']}",
                          f"Retrieved: {entry['retrieved_at']}",
                          f"Published: {source.get('published') or 'unknown'}",
                          f"Excerpt size: {len(source['content'])} characters. SHA-256: {digest[:12]}."])
            if full:
                lines.extend(["", source["content"]])
        for turn in turns:
            entries = [entry for entry in self.entries if entry["turn_id"] == turn]
            expected = max(entry["source_count"] for entry in entries)
            if len(entries) < expected:
                lines.extend(["", f"A research turn retained {len(entries)} of {expected} source blocks; "
                              "the others were omitted, damaged, or removed from context."])
        lines.extend(["", "Archived evidence is not a fresh lookup. This reports only evidence present in "
                      "the history Studio supplied; wholly removed turns cannot be detected."])
        return "\n\n".join(lines)
