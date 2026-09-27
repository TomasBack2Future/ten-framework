# Approved baseline integration

Parents: Web repair `2eb3bf08dc0d606d9a584a81d4a219016e770db0` and public bootstrap `060cc9535356a76afa9158452186961c2405e44b`. Bootstrap contains approved Executor `8988272c1621690c96d279cf36b2373a3d3e81c4` and Decision `ad6c2f94f04ac734f170fc22beeab7c9f3fd981d`. No deployment is part of this merge.

## Conflict resolution

The independent/cherry-picked histories produced 25 conflicted files. Resolution:

- All 16 conflicted Executor files (`DATASET_PLAN.md`, `README.md`, `REPORT.md`, `Taskfile.yml`, `ablation.py`, `adapter.py`, `build_dataset.py`, `data/bfcl-manifest.json`, `data/run-manifest.json`, `data/self_authored.jsonl`, `evaluate.py`, `results/sandbox-fake.jsonl`, `results/streaming-fake.json`, `routing.py`, `sdk_backend.py`, `tests/test_sdk.py`) take the approved Executor tree. The **entire executor subtree** is byte-identical to `8988272c`, including moved historical data and spec-lock v2.
- `engine.py` combines both sources using the pre-memory/pre-scheduling engine `55dcfb4` as the content ancestor. The two overlapping hunks normalize input whitespace before consumed-segment deduplication, and preserve deeply copied history plus the older-context summary in the classifier snapshot.
- `tests/test_engine.py` combines both regression sets. The request-context test keeps the assertion that the current user is appended after request construction, but replaces its obsolete two-message rolling-history assumption with retention of every preceding user turn. Added a cross-feature test for a whitespace-normalized consumed partial followed by an identical final.
- `docs/config.md` combines both configuration descriptions. `docs/VERIFICATION.md` takes the approved Decision branch's historical verification record; those historical counts are not the current suite count.
- `scripts/run_graph.py`, `scripts/validate_live.py`, and extension `config.py`, `extension.py`, `provider.py` retain Web's voice/compression/settings, origin/readiness, timestamp, cancellation, and privacy fixes.

## Source comparison and checks

An AST comparison verifies `schedule`, `complete_decision`, `mark_applied`, `tick`, `pause`, and `resume` exactly match approved Decision methods. Web's `start`, `stop`, `output`, `heard`, `align`, `audio`, `playback`, `begin_compression`, and `complete_compression` methods are unchanged. Extension/config/provider/memory, graph runner, live validator, smoke environment, Web subtree and OpenAI adapter remain byte-identical to `2eb3bf0`.

Integrated native TEN suite: **54 passed**; Black, Pylint 10/10 and schemas passed. Web: **16 passed** on Ubuntu. Executor validation uses its unchanged `task check`, `task lint`, `task test-core`, and `task test`; SDK tests require the pinned `openai-codex==0.157.1` from requirements-sdk.txt. CI executes the native graph, Python suite and all stdlib Executor suites without credentials/network.

The separate ID repair in `2eb3bf0` fixes the real POST /api/session response `{id, expires_at}`. Connect cleanup, End and pagehide all send `{session_id: session.id}`; /api/end rejects missing/invalid IDs and treats a valid stale ID as an idempotent no-op. Tests cover a lost S1 cleanup response, same-cookie S2 creation, then stale cleanup/pagehide, plus actual browser handler bodies and recovery. This supersedes the flawed mock shape in the earlier ba461b2 review record.
