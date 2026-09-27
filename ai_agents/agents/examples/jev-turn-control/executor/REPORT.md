# Reviewed executor pilot — 2026-09-27

Seven independently reviewed defects are fixed in the default-disabled executor.
See REVIEW_RESPONSE.md for each finding, its implementation and regression test.
The source remains isolated under executor/; no graph, Web or deployment code
is changed. This is a reviewable fix, not a merge/deployment approval.

## Corrected execution behavior

Private cancellation generations are separate from public input revisions.
Cancel revision 1 followed by adjust revision 2 is valid. Per-task control locks
serialize overlapping changes and prevent revision regression. Cancellation
establishes the local commit fence and emits one cancelled terminal; SDK interrupt
failure or context cleanup failure cannot replace it with error. It does not
promise rollback or remote interruption acknowledgement.

Artifact plans now specify the complete desired file set. Retained files must
be included; omitted previously managed files are removed after the plan is
validated and its new files written. An empty plan removes managed artifacts.
Filesystem I/O failure is not a transaction rollback guarantee. Task cancellation
still leaves completed side effects intact; partial ASR and speech-stop do not
start/cancel tasks. Execution remains limited to bounded local artifacts through
an official async SDK read-only plan and trusted writer.

## Evaluation validity correction

The old holdout claim is withdrawn: translated/semantic variants were split
across dev and locked-test. All old reports, observations and checksums are
retained unmodified under historical-v1/ for audit. The old 80.8% / 84.6%
26-example figures must not be presented as independent holdout performance.

The explicit family audit groups 32 source scripts into 17 authored semantic
families and preserves source IDs. Current bookkeeping is 28 train, 22 dev,
30 regression-test (14 authored + 16 BFCL), but **all 80 samples are exposed**.
Reassigning them does not produce new unseen evidence. Labels were not changed
in response to predictions. A truly fresh holdout requires independently
collected new families and a new frozen manifest.

A new paired regression over all 80 uses the same refined prompt and .75
threshold, frozen before rerunning. No further tuning occurred. Selection locks
now bind dataset SHA256, prompt SHA256, variant, threshold and exposure boundary.
Non-dev CLI calls require that lock; omitted options load from it and conflicting
options fail before credential reads/API calls. The locked-test path rejects
legacy/exposed metadata. These are regression results, not generalization scores:

| Provider | N | Route accuracy | Execute precision | Execute recall | Support accuracy | False dispatch | p50 full decision |
|---|---:|---:|---:|---:|---:|---:|---:|
| Jev | 80 | 92.5% | 88.9% | 97.0% | 92.5% | 1/60 (1.67%) | 767 ms |
| ScaleDown | 80 | 88.75% | 91.2% | 93.9% | 91.25% | 0/60 | 1746 ms |

Both saw identical inputs/IDs; no provider errors. Raw scores and complete
confusion matrices are in results/regression-paired.jsonl and its summary.
Only current/past context and capabilities reach the classifier, never gold,
future turns or private task state. USD costs remain unknown. A Jev wrong
new-task dispatch for an in-progress adjustment remains; these scores still
do not justify enabling unattended public execution.

## Corrected ablation and filesystem evidence

The original fake comparison conflated no side effects with correct routing.
It now records terminal_state_success and dispatch_policy_success separately,
plus unexpected_dispatch/missed_dispatch. Combined success requires both.
A router that always dispatches explanation turns fails this assertion even
when a fake executor returns no files.

The corrected local run replays the original paired Jev/ScaleDown observations
(no new provider calls) through the current artifact writer. Each arm has the
same 12 tasks, 3 accepted turns per task and fixture backend:

| Arm | Calls | Terminal state assertions | Dispatch gate assertions | Combined success | Unexpected dispatch |
|---|---:|---:|---:|---:|---:|
| Every accepted turn | 36 | 36/36 | 12/36 | 12/36 | 24 |
| Jev + fake | 12 | 36/36 | 36/36 | 36/36 | 0 |
| ScaleDown + fake | 12 | 36/36 | 36/36 | 36/36 | 0 |

The all-accepted arm deliberately delegates every turn, so failing this specific
dispatch gate does not prove a live model would perform an unwanted side effect.
Separate terminal assertions keep that distinction visible. Historical routing
time plus new fixture timing is a replay, not fresh end-to-end latency. No live
Codex success/cost/speed benefit is claimed.

12 sandbox fixtures pass real HTML/CSV/JSON file assertions. Streaming fixture
checks zero duplicate starts after 20 repeats, no stale writes after cancel,
and preserved tasks on speech-stop. Cancellation/feedback timings are fake local
orchestration measurements, not model or acoustic latency. Full-Duplex-Bench
and integrated Soniox/Groq/Cartesia voice timing remain the voice phase.

## Verification and live boundary

23 local tests pass, including SDK interrupt timeout, RPC rejection and context
exit failures. All 20 stdlib core/evaluation tests run via `task test-core`;
`task test` adds 3 SDK contract tests using installed openai-codex 0.157.1 and
injected transport. Black check and Pylint 10.00/10 passed. Independent Ubuntu Python 3.10
validation in a no-network public TEN build container passed all 20 core tests
and 12 sandbox terminal assertions, with no unhandled cleanup exception.

The SDK catalog probe from the original run listed GPT-6 Luna low, not none,
in an isolated home with no account. This is catalog evidence only, not deployed
account entitlement. No authorized OpenAI/Codex credential has been provided,
so real executor and real three-arm validation remain blocked. No unrelated
private credential is used and no production permission is added.

The 16 BFCL cases are download-only, pinned with source IDs/checksums and separate
original/derived labels. Public dataset text is not redistributed based solely
on code licensing. ToolTalk, ToolSandbox and tau-Voice suitability/licensing
notes remain in DATASET_PLAN.md. The result is not a BFCL leaderboard score or
real customer-call benchmark.

Final merge/deployment is gated by Grok re-review of the exact new SHA and the
user's coordinated integration process. The Web owner must run the expanded
`task test-core` rather than only the original adapter test file.

## Narrow re-review P3: complete decision-spec lock

The prompt-only checksum omitted criteria and model selection. The v2 lock now
binds the effective instructions, both criteria sets, model/request settings,
input projection, label/tie order, threshold and timeout. Router requests use
the same detached spec that is hashed. Conflicting configuration fails before
key access or API calls; future observations include the digest and provider
model/compression selection. ScaleDown server defaults remain explicitly unknown.

`results/regression-selection.json` and every previous observation/summary remain
byte-identical. The separate `regression-selection.v2.json` is a prospective,
source-reconstructed migration from 9b510fc, not a runtime attestation for old
results. No paid evaluation was rerun. New tests cover criteria/model/instruction
and request-setting drift, snapshot/request binding, legacy rejection and
tampered specs. Validation: 26 local tests and 23 Ubuntu Python 3.10 offline core
tests, plus formatting and pylint. Merge/deployment still requires narrow review
of the new exact commit.
