# Optional execution pilot — 2026-09-27

The isolated, default-disabled artifact execution module and reproducible pilot
are implemented. They are ready for optional integration, not for unattended
public execution. The locked test still exposes routing errors. No live Codex
execution was performed because the authorized deployment credentials contain
Soniox, Groq and Cartesia keys only, with no OpenAI/Codex credential.

## Delivered behavior

An async official SDK backend generates structured file plans under read-only
permissions; a trusted writer bounds and validates artifact paths/content and
checks task revisions before committing. A deterministic fake backend exercises
the same adapter. Session/turn idempotency prevents partial/final duplication;
explicit task cancel, replace/adjust and status are session-scoped. Ordinary
conversation and stop-speech never cancel background tasks. Terminal effects are
not rolled back. Shared voice graph/schema files are untouched. The SDK
integration is pinned to openai-codex 0.157.1, verified against installed public
Python signatures and mocked async transport contracts.

The SDK runtime's model catalog in a fresh isolated CODEX_HOME contains
`gpt-6-luna` with `low`, `medium`, `high`, `xhigh`, `max`, but not `none`.
The account probe returns no account. This establishes catalog support only,
not deployed account entitlement, successful inference, speed or price.
The backend checks the deployed catalog and fails closed on unsupported effort;
it does not substitute `minimal`, another model or a private credential.

## Dataset and protocol

80 routing examples: 64 self-authored bilingual cases (32 contrast families),
8 original public BFCL inputs and 8 explicitly derived BFCL cases. Public text
is download-only, pinned to Gorilla commit
`6ea57973c7a6097fd7c5915698c54c17c5b1b6c8`; only source IDs, derivation metadata,
labels and checksums are redistributed. The upstream repository has Apache-2.0
code licensing; separate dataset redistribution terms were not established, so
no raw or translated upstream text is vendored. ToolTalk and ToolSandbox were
reviewed as alternatives and are not imported. See DATASET_PLAN.md.

Fixed seed 20260927, family grouping: 24 reserved train, 30 dev, 26 locked-test.
All BFCL samples retain their evaluation role in locked-test, including linked
base/missing-function/missing-parameter variants. Current/past user text and
available capabilities are whitelisted; private initial state, gold call paths,
future clarifications and source labels are never sent to classifiers. Labels
are pilot author annotations, not independent human-reviewed Jev gold or an
upstream four-class benchmark. Ambiguities are documented, not hidden.

Both providers ran on the same IDs and model-visible input. Baseline then one
predeclared refined prompt ran on dev. Thresholds 0.65, 0.75 and 0.85 were scored
from cached dev probabilities; 0.75 was the lowest that removed the observed
Jev false dispatch without lowering execute recall. The same prompt and
threshold were locked for both providers before one locked-test run. No test
retuning followed. The baseline file hashes the self-only input file; refined
and locked runs hash the complete 80-example file. The actual dev sample IDs and
contents are identical (30 self-authored examples) across both prompt runs.
This is prompt/threshold tuning, not fine-tuning.

## Routing results

| Split / prompt | Provider | N | Route accuracy | Execute precision | Execute recall | Support accuracy | False dispatch rate | p50 complete decision |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| Dev baseline, .65 | Jev | 30 | 83.3% | 87.5% | 100% | 83.3% | 3.6% | 797 ms |
| Dev baseline, .65 | ScaleDown | 30 | 76.7% | 87.5% | 100% | 86.7% | 0% | 1928 ms |
| Dev refined, .65 | Jev | 30 | 96.7% | 87.5% | 100% | 96.7% | 3.6% | 796 ms |
| Dev refined, .65 | ScaleDown | 30 | 83.3% | 85.7% | 85.7% | 96.7% | 0% | 1771 ms |
| Locked refined, .75 | Jev | 26 | 80.8% | 75.0% | 92.3% | 80.8% | 5.9% | 792 ms |
| Locked refined, .75 | ScaleDown | 26 | 84.6% | 86.7% | 100% | 76.9% | 0% | 1797 ms |

False dispatch is execute + supported + stable on a non-actionable example.
Locked Jev numerator/denominator is 1/17; ScaleDown is 0/17. This small sample
cannot establish a production safety bound. Route metrics include partials,
while dispatch metrics exclude them. No provider errors occurred. Jev performs
two questions in one request; ScaleDown performs two concurrent requests and
latency covers both. Token usage is recorded where returned; USD cost is null
because reliable per-run billing was not available. Full confusion matrices
and per-example scores are in results/*.summary.json and *.jsonl.

Failure audit (labels frozen): both providers treated two BFCL mental-task
examples (triangle arithmetic, translation) as execute/unsupported rather than
conversation. Jev routed one in-progress page adjustment as new execution,
which is the false-dispatch case, and missed one parameter clarification route.
ScaleDown confused an English stop-reading request with task control, despite
classifying support as unsupported. The task-control action/target must remain
explicit at the host boundary; raw classification alone is not cancellation
authority. The test lacks enough cases to estimate all control subtypes well.

## Execution and streaming

12 sandbox tasks cover HTML headings, CSV sums and JSON counts. All 12 fake
fixtures passed independent assertions on actual files; model completion text
was never the success oracle. These fixture-backed results validate lifecycle
and artifact validation, not natural-language task solving by Codex.

Streaming fixture: 20 duplicate deliveries produced 0 duplicate starts;
0 stale artifact commits after cancel; stop-speech preserved background task.
Measured task cancellation about 0.14 ms, first feedback about 0.39 ms, completion
about 52 ms (fake delay 50 ms). These are local orchestration timings, not model
or audio latency. Acoustic stop latency remains unmeasured; Full-Duplex-Bench
and integrated Soniox/Groq/Cartesia voice tests remain a later phase.

Three-arm harness uses identical 12 tasks × 3 accepted turns, same fake backend,
artifact writer and prior context. Each task has greeting, explanation-only,
and actionable turns. Real Jev/ScaleDown classification was used; fake execution
returns a known fixture for the actionable turn and an empty plan for the other
two. This stub intentionally contains no model intelligence.

| Arm | Backend calls | Verified task terminals | All turn assertions | Mean turn total latency |
|---|---:|---:|---:|---:|
| Every accepted turn | 36 | 12/12 | 36/36 | 13 ms |
| Jev + same fake | 12 | 12/12 | 36/36 | 877 ms |
| ScaleDown + same fake | 12 | 12/12 | 36/36 | 1881 ms |

Routing reduces fake dispatch count and adds latency in this fixture. No claim
that Jev improves real Codex total latency, cost or success follows. The
`--backend codex` harness is implemented but blocked on a dedicated authorized
credential. An account-enabled bounded real run is necessary before making a
model or architecture recommendation. GPT-6 Luna low is a configured candidate,
not an empirically established fastest option.

## Verification and delivery boundaries

- 14 local unittest cases passed, including official SDK call shape and active
  interruption. Core regression covers disabled/partial/unsupported input,
  duplicate delivery, cross-session controls, cancel-before-start, inflight
  cancellation, no rollback of completed output, speech independence,
  cancel-and-adjust, late result fencing, timeout/caps, invalid path plans and
  classifier input projection.
- Ubuntu x86_64 independent checkout and no-network public TEN build container:
  Black formatting/check, Pylint 10.00/10, 12 core tests and 12 sandbox terminal
  assertions passed. SDK transport tests ran locally against pinned SDK; the
  no-network Ubuntu check did not install/invoke the optional SDK.
- No C++ runtime rebuild, shared graph edit, production deployment, credential
  transfer, official-upstream push or main merge. The shipping voice MVP stays
  independent. Task cards and speech result hook are documented for the Web
  integration owner; they are not claimed integrated here.

Known MVP limits: in-memory idempotency (new session required after restart),
no durable job recovery, cancel-and-replace rather than native steer, task-level
not detailed tool progress, operator-provisioned isolation required, artifact
contents untrusted and only downloadable/sandbox-previewable. Automated live
purchases, external messaging and production shell operations are out of scope.

Official references: [Codex SDK](https://learn.chatgpt.com/docs/codex-sdk),
[App server](https://learn.chatgpt.com/docs/app-server),
[Jev API](https://docs.typesafe.ai/api),
[BFCL V3](https://gorilla.cs.berkeley.edu/blogs/13_bfcl_v3_multi_turn.html),
[BFCL leaderboard](https://gorilla.cs.berkeley.edu/leaderboard),
[tau-Voice architecture](https://github.com/sierra-research/tau2-bench/blob/main/src/tau2/voice/README.md).
