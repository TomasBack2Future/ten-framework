# Jev turn-control bootstrap

An isolated, offline-testable foundation built on the public TEN Framework.
This is a loading and graph-routing skeleton, not a functioning voice agent.
No vendor credentials, private packages, or commercial graph are used.

## Baseline and layout

- Public repository: `https://github.com/TEN-framework/ten-framework.git`
- Baseline main: `ca00160c79d277a6179b5bd7af3c585db4c8f3db` (0.11.73).
- App and independent graph: `tenapp/manifest.json`, `tenapp/property.json`.
- Independent extension: `../../ten_packages/extension/jev_turn_control_python`.
- `main.py` is the public `packages/core_apps/default_app_python/main.py`
  from that exact baseline. Its Apache 2.0 license is preserved here.
- `tests/conftest.py` is the public default Python extension test fixture
  from the same baseline, under its Apache 2.0 license.
- Runtime and Python bindings are pinned to `=0.11.73` and installed by tman.
  This uses official binary packages; it does not rebuild the C/C++ runtime.

## Reproduce on Ubuntu x86_64

Prerequisites: Git, GitHub CLI, Docker, unzip, SHA256 tools. The official
`ten_agent_build:0.7.14` image supplies Python 3.10, uv, Task, Black and Pylint.
Use a new destination; never reuse another project's checkout or container.
A sparse clone is sufficient (expand it when adding provider integrations):

```bash
git clone --depth 1 --filter=blob:none --no-checkout --branch main \
  https://github.com/TEN-framework/ten-framework.git ten-jev-hackathon
cd ten-jev-hackathon
git sparse-checkout init --cone
git sparse-checkout set docs/ai docs/code-of-conduct tools/pylint \
  packages/core_apps/default_app_python packages/core_extensions/default_extension_python \
  ai_agents/agents/scripts
# For an exact historical baseline, fetch and check out the SHA above.
# For new work, fetch origin/main and record its actual SHA before branching.
git checkout main
git switch -c chore/jev-oss-bootstrap
```

The files in this branch must also be present (the branch has not been pushed).
For an already bootstrapped checkout, use:

```bash
bash ai_agents/agents/examples/jev-turn-control/scripts/bootstrap-container.sh
# Seed the exact public runtime artifact to avoid slow-link tman timeouts:
bash ai_agents/agents/examples/jev-turn-control/scripts/prefetch-runtime.sh
docker exec -e TMAN=/workspace/.bootstrap/tools/ten_manager/bin/tman \
  -w /workspace/ai_agents/agents/examples/jev-turn-control \
  ten-jev-bootstrap bash -lc 'task install && task build && task check && task smoke'
```

`task install` uses uv for a project virtual environment, pinned pytest, and
the official Python runtime dependencies (`namedthreads==1.0`, `uvloop==0.22.1`).
The test runner is pytest 9.0.2; inherited support libraries come from the
official image. No host Python packages are installed. `task build` compiles Python sources;
`task check` runs Black, repository Pylint rules and tman JSON validation.
Generated packages, tools, logs and virtual environments are ignored by Git.
`prefetch-runtime.sh` downloads from the same official S3 URL returned by the
public registry, verifies SHA256, and seeds only this container's tman cache.
It supports partial-file resume; rerun it after a timeout. The default tman
registry remains unchanged. The official CN endpoint timed out during setup
and is not configured as a fallback.

To prove smoke needs no network after installing dependencies:

```bash
docker run --rm --network none \
  --mount "type=bind,src=$PWD,dst=/workspace" \
  -w /workspace/ai_agents/agents/examples/jev-turn-control \
  --entrypoint bash ghcr.io/ten-framework/ten_agent_build:0.7.14 \
  -lc 'task smoke'
```

## Official template regression

`task official-smoke` copies the baseline official Python app into
`.bootstrap/official-app`, installs the public default Python extension from
this checkout and runs its unchanged `test_basic.py` hello-world command test.
Run it inside the dedicated container after `task install`. It uses the same
public 0.11.73 runtime and has a bounded timeout.

## Run and stop

```bash
docker exec -it -w /workspace/ai_agents/agents/examples/jev-turn-control \
  ten-jev-bootstrap task run
# Ctrl-C stops this app. Stop the dedicated development container when idle:
docker stop ten-jev-bootstrap
```

No ports are published. The graph opens no provider connection or listener.
`task run` prints `JEV_EXTENSION_READY stage=bootstrap_only` and waits.
`task smoke` starts real native TEN runtime tests, checks the graph's node,
adds the official tester node and connection, sends `jev_ping` and verifies its
nonce and stage. A separate subprocess test starts the unmodified shipping
graph, waits for addon readiness, sends SIGTERM and requires clean exit.
Tests have bounded timeouts and clean up their child process.
Success: `JEV_GRAPH_ROUNDTRIP_PASS`, `JEV_APP_LIFECYCLE_PASS`, and passing pytest.

## Current interface

`jev_ping` is only a diagnostics command. Request: `nonce: string`.
Result: OK, the same nonce, and `stage: "bootstrap_only"`.
It grants no permission to answer or play audio. No audio/media endpoint is
implemented, and the separate web test tool has not been modified.

## Future integration boundary (design constraints, not implemented)

- Input: timestamped PCM frames replayed at real time; Tencent interim/final
  ASR events; monotonic timer events; playback cursor acknowledgements.
- Jev owns answer-start and output-stop decisions. Neither ASR final nor agent
  EOS is the sole answer permission. Silence may trigger clarification.
- Carry session, turn/input revision and response generation identifiers.
  New input fences out stale responses and actively cancels generation.
  Do not introduce a one-shot `prepare_response` permission round trip.
- Qwen Plus (DashScope) is the main model. Other small models start disabled.
  Keep ScaleDown as an explicit option in every later comparison.
- MiniMax WebSocket provides streaming TTS. Voice selection remains pending.
- Stopping requires canceling generation, draining playback queues, and a
  playback-cursor acknowledgement. A cancel acknowledgement does not mean
  sound has stopped. TTS alignment and cursor retain only played text.
- Backchannel is a later configurable capability, not a bootstrap dependency.
- Define/version the transport protocol with the separate browser tool before
  implementing its adapter. No browser-facing port or endpoint exists yet.

## Next work

1. Specify public event schemas and deterministic turn/version reducer tests.
2. Add timer-driven clarification, fencing and cancellation regression cases.
3. Implement provider adapters using public SDKs/APIs and user-supplied keys.
4. Add realtime replay, playback cursor and TTS alignment integration tests.
5. Compare full-duplex behavior with ScaleDown on/off using public recordings.

All new skeleton code was independently written against public TEN APIs.
The repository root LICENSE contains additional conditions; the copied public
app template has its own Apache 2.0 license. No license is inferred for private
code because no private source has been used. No publication is performed.
