# Optional artifact executor

Default **disabled**. This package does not change the shipping graph, controller,
providers or shared event schema. It requires Python 3.10+ for the offline core;
the optional official SDK is pinned in `requirements-sdk.txt`.

## Integration contract

The voice engine owns the `jev.v1` envelope and speech lifecycle. Instantiate one
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
into the common v1 envelope (timestamp and sequence owned by host). Emitted:
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
never rolls back completed effects. Adjustment restarts generation in the same
task directory with existing artifact content, retaining task ID while replacing
the SDK thread ID. This is explicit cancel-and-replace, not native model steering.
Idempotency is worker-lifetime scoped: persistence/reconnect replay is not
implemented; allocate a new session after worker restart and do not replay tasks.

## Execution boundary

Only artifact creation/modification is allowed. SDK uses read-only sandbox,
deny-all approvals, disabled shell tool/web search and no inherited shell env.
A trusted Python writer accepts simple HTML/CSV/TXT/JSON basenames and bounded
content after a revision fence. No file plan runs as code. Use a dedicated
non-root container, clean CODEX_HOME, private work volume, no Docker socket,
kubeconfig, production credentials or other service-provider secrets. Never
mount the user's desktop Codex authentication. The only model credential is the
explicit executor OPENAI_API_KEY. Container enforcement is checked before SDK
calls; fake backend has no network.

`Dockerfile` is a build recipe, not a deployed service. Do not expose SDK
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

Repeat once with `--variant refined`, select only from dev, save selection, then
run one `--split locked-test --variant refined --threshold 0.75`. Stored final
results are already consumed; changing the prompt requires a new holdout.
The scorer reports raw four-way confusion plus support and dispatch metrics.

`python3 -m executor.ablation --backend fake ...` runs the same 12 sandbox tasks
with three accepted turns through all-accepted / Jev / ScaleDown arms. Supply the
two `--*-key` paths and `--output`. `--backend codex` uses the same model/tool/file
context and real terminal-state assertions, but requires the dedicated container
and executor credential. Fake runs only validate the comparison machinery; they
cannot establish Codex success, speed, cost savings or a routing benefit.

See DATASET_PLAN.md, data/bfcl-manifest.json, results/*.jsonl and REPORT.md.
