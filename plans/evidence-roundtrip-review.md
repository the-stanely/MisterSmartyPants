# Evidence in Studio history: findings and isolated probe

## Objective

Retain MSP's selected source evidence in Studio's account-owned conversation
history and return it to MSP on later turns, avoiding another history database
and any need to infer ownership from editable user labels.

No Studio settings, user databases, or installed application files were changed.
The original review added an opt-in synthetic diagnostic command. Real search
answers now include evidence payloads. See the implementation update below.

## Findings

Implementation update: the user confirmed the synthetic Studio transport tests
pass. The bridge now carries uncompressed, independently checksummed source
envelopes, restores them for final answers, and provides `/evidence` and
`/evidence show` for inspecting the supplied chat's retained passages. It preserves
the existing decider flow and does not create an evidence database. Transfer
limits and real-source UI verification steps are documented in
[studio-bridge-test.md](studio-bridge-test.md#real-source-evidence-and-inspection).
The proposal later in this review records the earlier investigation.

The installed Studio 2026.10.8 backend and upstream frontend were inspected.

- Chat messages have content and metadata fields in persistent storage. However,
  storing arbitrary response metadata there and replaying it to a custom provider
  is not an automatic part of the inspected adapter.
- The custom Chat Completions proxy relays ordinary content chunks. It strips
  Studio UI-control frames and fields from provider streams, so imitating an
  internal tool-result card is not a supported integration path.
- The frontend converts received assistant text to text parts, and its history
  serializer reconstructs assistant content from those text parts. The inspected
  replay sanitizer removes search-image tokens and inline audio payloads; it
  does not generally strip HTML comments.
- The visible answer is rendered separately as Markdown. A bounded encoded
  evidence envelope in an HTML comment is therefore a promising carrier that
  should remain in raw history while being absent from the rendered answer.
  This is an interoperability experiment, not a documented hidden-metadata API.
- Reasoning content is not a suitable carrier: it is rendered as thinking and
  its replay depends on model/reasoning settings. Evidence is not model reasoning.

Relevant source paths:

- `studio/backend/routes/chat_history.py`: `ChatMessage` content and metadata.
- `studio/backend/core/inference/external_provider.py`: custom-provider stream relay.
- `studio/backend/core/inference/sse_control_frames.py`: provider control-frame sanitization.
- `studio/frontend/src/features/chat/api/chat-adapter.ts`: assistant serialization,
  `sanitizeAssistantReplayText`, and streamed text extraction.
- `studio/frontend/src/components/assistant-ui/markdown-text.tsx`: rendered Markdown.

## Test using Studio itself

Restart the MSP bridge. In a disposable MSP-provider chat:

1. Send `/evidence-test seed`.
2. Confirm the answer displays normally without a visible `MSP_EVIDENCE_PROBE_V1`
   comment or encoded block.
3. Send `/evidence-test check`. Expect `PASS`.
4. Reload/reopen that chat and check again. This tests history persistence.
5. Restart the bridge and check again. The probe keeps no server state, so a
   successful result must come from US-supplied history.
6. Start another chat and send `/evidence-test check` without seeding it.
   Expect `NOT RECEIVED`. Repeat from another US account.
7. If available, fork the seeded chat and check the fork; evidence in common
   ancestry should follow the fork. Later branch-specific payloads should not
   appear in the other branch.
8. Finally test long-context trimming/compaction. Do not assume arbitrary comments
   survive those operations even if ordinary follow-ups work.

The seed contains a version, random nonce, and a fixed synthetic excerpt. It uses
no inference, no search, no real evidence, and no account credentials. The check
reads only earlier assistant messages from the current request and validates the
encoded JSON. User/system-message copies are ignored. It does not identify or
authenticate a user and is not a persistent evidence store.

## If the probe passes

The candidate implementation would:

1. Capture the evidence block that MSP already appends to its internal history.
2. Package it in a bounded versioned envelope attached to the returned answer.
3. Let Studio store that raw assistant message under its existing user/chat ownership.
4. On the next turn, extract envelopes from assistant history, remove the carrier
   text, and reconstruct MSP's ordinary prior-evidence context at the matching turn.
5. Preserve the existing separation: the decider sees dialogue without evidence,
   while final answer generation can use earlier evidence.

This could remove the need for separate user IDs, conversation IDs, and an MSP
database for ordinary history continuity: the evidence would travel with its
actual conversation and branch. It would inherit Studio's context-retention limits.

Before using real evidence, define payload limits, malformed-envelope behavior,
source timestamps, whether to carry cumulative versus per-turn evidence, and a
safe decoding format. Do not deserialize executable objects. If compression is
used, enforce a decoded-size ceiling. A hidden comment is not encryption or a
privacy boundary: raw copies, exports, shares, or another model/provider may see it.

If Studio removes the envelope, or reliable persistence requires a first-class
metadata field, a deliberate Studio adapter change is the cleaner fallback.
Do not write directly to Studio's SQLite files or misuse user-wide memory for
conversation-specific evidence.
