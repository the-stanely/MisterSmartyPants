"""Source transport integrity, recovery and retention limits."""
import base64
import hashlib
import json

import pytest

import studio_evidence as evidence


def page(number=1):
    return {"title": f"Source {number}", "url": f"https://example.org/{number}",
            "extractor": "trafilatura", "content": f"Station café-{number}. [END EXCERPT]"}


def carrier(payload):
    raw = json.dumps(payload).encode()
    return f"{evidence.PREFIX}{hashlib.sha256(raw).hexdigest()}:{base64.b64encode(raw).decode()} -->"


def test_uncompressed_unicode_roundtrip_and_provenance():
    blocks, skipped = evidence.pack_sources([page(), page(2)], "Question", "Query")
    clean, recovered, damaged = evidence.unpack_sources("Answer\n" + blocks)
    assert clean == "Answer" and skipped == damaged == 0
    assert len(recovered) == 2
    first, second = [item[0] for item in recovered]
    assert first["source"] == page()
    assert first["turn_id"] == second["turn_id"]
    assert first["question"] == "Question" and first["query"] == "Query"
    assert first["retrieved_at"]
    encoded = blocks.split("\n\n")[0].split(":")[-1].split()[0]
    assert json.loads(base64.b64decode(encoded))["source"] == page()


@pytest.mark.parametrize("damage", ["checksum", "missing_close", "truncated"])
def test_independent_recovery(damage):
    blocks, _ = evidence.pack_sources([page(), page(2)], "q", "q")
    first, second = blocks.split("\n\n")
    if damage == "checksum":
        index = len(evidence.PREFIX)
        first = first[:index] + ("f" if first[index] != "f" else "a") + first[index + 1:]
    elif damage == "missing_close":
        first = first[:-3]
    else:
        first = first[:100]
    clean, recovered, damaged = evidence.unpack_sources("Answer\n" + first + "\n" + second)
    assert clean == "Answer" and damaged == 1
    assert [item[0]["source"] for item in recovered] == [page(2)]


@pytest.mark.parametrize("field,value", [("v", 2), ("source_count", True),
    ("retrieved_at", "yesterday"), ("question", 12)])
def test_checksummed_invalid_schema_is_discarded(field, value):
    blocks, _ = evidence.pack_sources([page()], "q", "q")
    payload = evidence.unpack_sources(blocks)[1][0][0]
    payload[field] = value
    assert evidence.unpack_sources(carrier(payload)) == ("", [], 1)


def test_deduplication_and_request_isolation():
    blocks, _ = evidence.pack_sources([page()], "q", "q")
    state = evidence.EvidenceState()
    state.restore(blocks)
    state.restore(blocks)
    assert len(state.entries) == 1 and state.duplicates == 1
    assert "café-1" not in state.report()
    assert "café-1" in state.report(full=True)
    assert evidence.EvidenceState().entries == []


def test_limits_and_partial_turn_reporting(monkeypatch):
    blocks, _ = evidence.pack_sources([page(), page(2)], "q", "q")
    size = evidence.unpack_sources(blocks)[1][0][2]
    monkeypatch.setattr(evidence, "MAX_RESTORED_BYTES", size)
    state = evidence.EvidenceState()
    state.restore(blocks)
    assert len(state.entries) == 1 and state.over_limit == 1
    assert "1 of 2" in state.report()
    monkeypatch.setattr(evidence, "MAX_SOURCE_BYTES", 10)
    assert evidence.pack_sources([page()], "q", "q") == ("", 1)
    assert evidence.unpack_sources(blocks)[2] == 2


def test_turn_budget_skips_sources_independently(monkeypatch):
    blocks, _ = evidence.pack_sources([page()], "q", "q")
    size = evidence.unpack_sources(blocks)[1][0][2]
    monkeypatch.setattr(evidence, "MAX_TURN_BYTES", size)
    blocks, skipped = evidence.pack_sources([page(), page(2)], "q", "q")
    assert skipped == 1 and len(evidence.unpack_sources(blocks)[1]) == 1
