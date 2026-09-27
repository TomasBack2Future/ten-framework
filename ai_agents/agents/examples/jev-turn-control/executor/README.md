# Optional artifact executor

For the P1 live call-scoped service (one call, one thread), deployment gates and
credential injection, see [CALL_SESSIONS.md](CALL_SESSIONS.md). The task-scoped
adapter below remains the offline evaluation/reference path.

Default **disabled**. This package does not change the shipping graph, controller,
providers or shared event schema. It requires Python 3.10+ for the offline core;
the optional official SDK is pinned in `requirements-sdk.txt`.

## Integration contract

The voice engine owns the `version: 1` observation envelope and speech lifecycle. Instantiate one
`Executor(backend, ExecutorConfig(...))` per worker. Import the package from the
example directory. After independently classifying an accepted turn:

```python
from executor.adapter import Executor, Request
from executor.bridge import Bridge
from executor.config import ExecutorConfig
from executor.sdk_backend import CodexBackend

executor = Executor(CodexBackend(), ExecutorConfig(enabled=False))
bridge = Bridge(executor)
# Run this in the existing worker event loop; submit returns without model wait.
task_id = await bridge.accept(Request(
    session_id=session_id, turn_id=turn_id, input_revision=input_revision,
    text=input_text, stable=True, route=route, support=support,
))
```

The host must supply session-bound IDs from accepted turns, not browser-selected
IDs. `route` is conversation / execute / clarify / task_control. `support` is
supported / missing_parameters / unsupported. A tool query is execute. Missing
capabilities remain execute/unsupported and never reach the backend. Partials
may be classified, but `stable=False` never executes. Same session+turn starts
once, even if final or delivery retries change the input revision. Corrections
use `bridge.accept(... route='task_control', action='adjust', task_id=...)` with
a strictly newer revision. Cancel and status similarly require explicit target.
Control action extraction remains the integrating voice application's job; this
module does not infer cancellation from arbitrary strings or cancel all tasks.

Drain `executor.events` independently of playback. Wrap type/session_id/payload
into the common v1 envelope. The host supplies `version=1`, `event_id`, `seq`,
`relative_time_ms`, top-level `input_revision` copied from the payload, and
`response_id=null` for task-only events. The voice schema owner must add the
`task.*` enum values before publishing these events; the bootstrap schema does
not already declare them. Emitted:
`task.started`, `task.completed`, `task.cancelled`, `task.error`; generic progress
can be represented by the running status. Payload: task_id, turn_id,
input_revision, status, summary, artifacts[{name,sha256,bytes}]. No reasoning,
raw SDK output, exception body, secret, shell command or absolute path is emitted.
Use `status` for task cards. If task results are spoken, check current voice
response/input generation before starting speech; an old task completion may
still update its card without interrupting newer conversation.

Do not hook task cancellation to `response.stop`, `flush`, stop playback or
speech interruption. Those stop speech only. Unrelated new turns do not fence
background work. `await executor.close()` belongs in worker shutdown.

Cancellation fences artifact commits before asking the SDK to interrupt, and
never rolls back completed effects. Internal cancellation generations are
separate from public input revisions, so cancel revision 1 then adjust revision
2 is valid. Per-task control locks serialize concurrent cancel/adjust requests;
a lower revision cannot overwrite a newer one. Cancellation means the local
commit fence is established; an SDK interrupt timeout/rejection cannot turn it
into an error or emit a second terminal event. Adjustment restarts generation in the same
task directory with existing artifact content, retaining task ID while replacing
the SDK thread ID. This is explicit cancel-and-replace, not native model steering.
Idempotency is worker-lifetime scoped: persistence/reconnect replay is not
implemented; allocate a new session after worker restart and do not replay tasks.

## Execution boundary

Only artifact creation/modification is allowed. SDK uses read-only sandbox,
deny-all approvals, disabled shell tool/web search and no inherited shell env.
A trusted Python writer accepts simple HTML/CSV/TXT/JSON basenames and bounded
content after a revision fence. Each plan is a complete desired artifact snapshot:
include unchanged files to retain them; previously managed files omitted from a
successful new plan are removed. An empty plan removes all managed artifacts.
Validation happens before writes, but filesystem I/O failure is not a transaction
rollback guarantee. No file plan runs as code. Use a dedicated
non-root container, clean CODEX_HOME, private work volume, no Docker socket,
kubeconfig, production credentials or other service-provider secrets. Never
mount the user's desktop Codex authentication. The only model credential is the
explicit executor OPENAI_API_KEY. Container enforcement is checked before SDK
calls; fake backend has no network.

`Dockerfile` builds the optional call-session service; it is not deployed by default. Do not expose SDK
app-server publicly. Use readonly root filesystem, dedicated writable /work,
resource limits, no service-account token and outbound model-only network policy
when the infrastructure owner enables it. The module is not a multi-tenant
sandbox service. Serve artifact downloads as attachments, or HTML inside a
sandboxed iframe without scripts/same-origin, with restrictive CSP; do not insert
model-produced HTML into the host UI. Artifacts are untrusted.

## Reproduce

From the example directory, with `gh` already authenticated:

```sh
python3 -m unittest discover -s executor/tests -p test_adapter.py -v
python3 -m executor.build_dataset --cache executor/.downloads \
  --output executor/.routing.jsonl --manifest /tmp/bfcl-manifest.json
python3 -m executor.sandbox --output /tmp/sandbox-fake.jsonl
```

Optional SDK tests/probe (never borrows desktop auth): install the pinned SDK,
then `python3 -m unittest discover -s executor/tests -v` and
`python3 -m executor.probe --output /tmp/codex-probe.json`.
Run `task format`, `task check`, `task lint`, `task test` from executor/. The SDK
must be installed for all tests; core tests have no third-party dependencies.

For paired routing, supply secret *file paths*, never literal keys:

```sh
python3 -m executor.evaluate --dataset executor/.routing.jsonl --split dev \
  --variant baseline --jev-key /secure/jev-key --scaledown-key /secure/scaledown-key \
  --output /tmp/dev-baseline.jsonl
```

The existing 80 pilot examples are all exposed. Their original holdout claim
was withdrawn after semantic-family review (see DATASET_PLAN.md). For future paired regression runs, use the v2 selection file and regenerated
`.routing.jsonl` whose hash must match:

```sh
python3 -m executor.evaluate --dataset executor/.routing.jsonl --split regression \
  --selection-lock executor/results/regression-selection.v2.json \
  --jev-key /secure/jev-key --scaledown-key /secure/scaledown-key \
  --output /tmp/regression-paired.jsonl
```

Non-dev runs require a selection lock; omitted variant/threshold are read from
it. The complete decision spec binds effective instructions, route/support
rubrics, model selection, request settings, input projection, threshold and
timeout; requests are built from that same frozen snapshot. Conflicts fail
before key reads/API calls. Future rows and summaries record the spec hash and
provider model/compression selection, including unknown server defaults.
Legacy prompt-only locks are audit-only and rejected; the separate v2 migration
records known source configuration prospectively, without changing or attesting
historical observations. ScaleDown omits model/compression selectors, so its
resolved server settings cannot be pinned or inferred. `locked-test` additionally requires unseen-holdout metadata on both
the lock and samples; legacy/exposed pilot data is rejected. A new holdout must
be collected independently; regrouping or relabeling these samples is not enough.

`python3 -m executor.ablation --backend fake ...` runs the same 12 sandbox tasks
with three accepted turns through all-accepted / Jev / ScaleDown arms. Supply the
two `--*-key` paths and `--output`. `--backend codex` uses the same model/tool/file
context and real terminal-state assertions, but requires the dedicated container
and executor credential. Fake runs only validate the comparison machinery; they
cannot establish Codex success, speed, cost savings or a routing benefit.

See DATASET_PLAN.md, data/bfcl-manifest.json, results/*.jsonl and REPORT.md.

Reviewed CI: `task test-core` runs all 23 stdlib core/evaluation tests without
SDK installation; `task test` runs all 23 including the SDK contracts. The
ablation now reports terminal_state_success and dispatch_policy_success
separately; unexpected dispatch fails combined success even if no file changed.
To replay historical paired routing observations without new paid requests:

```sh
python3 -m executor.ablation --backend fake \
  --cached-decisions executor/results/historical-v1/ablation-fake.jsonl \
  --output /tmp/ablation-corrected.jsonl
```

Replayed route timings are historical observations combined with current fake
execution timing, not a new end-to-end model latency measurement.
