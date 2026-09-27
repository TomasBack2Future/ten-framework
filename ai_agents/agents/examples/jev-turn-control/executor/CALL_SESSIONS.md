# Optional P1 call sessions

One voice call owns one executor session, one SDK process and one Codex thread.
Different requests in that call use serial turns on the same thread; they do not
create new threads. Different calls never share a thread or artifact directory.
The existing task-scoped adapter is retained for the frozen evaluation fixtures;
the live optional path uses `call_session.py` and `service.py` instead.

The voice graph forwards each final ASR segment once, with the input revision and
bounded playback-confirmed history. Partials never execute. Final is permission
to synchronize executor input, NOT permission for the voice agent to speak.
The executor receives conversation too, but is instructed to change artifacts
only for explicit artifact requests. Its shell/web tools are disabled and the
SDK sandbox is read-only; a bounded trusted writer applies validated file plans.
This P1 is an artifact assistant, not an arbitrary code execution service.

The voice-side mailbox returns immediately and sends HTTP requests in a separate
task. The main brain receives a quoted status snapshot with its normal prompt
and continues talking while work runs. Completed relevant results are announced
only after voice playback and pending user input settle, and only when the
result revision still matches current input. Plain conversation does not create
an extra spoken notification. Results never directly enter TTS or pretend to be
new user utterances. Speech stop/pause do not cancel executor work.

Inputs received during a model turn queue in order (8 pending at each boundary).
This version deliberately does not use experimental live steering. A newer
accepted input fences old artifact commits; the next turn receives authoritative
current artifact contents and the same conversation thread. The assistant is
instructed to preserve unfinished authorized work across conversational updates.
An explicit spoken cancellation enters that queue and fences older output; it
is not a guarantee that an already running model stops billing immediately.
Ending the call closes the SDK process, interrupts outstanding work and deletes
the private artifact directory. Completed effects are not transactionally rolled
back on filesystem failure. Artifacts are not served publicly by this API.

## Switches and credentials

There are two independent gates, both default off:

1. Operator: `JEV_CODEX_ENABLED=true` on the voice host AND executor service.
2. User: check **Codex artifacts (next call)** before connecting. This maps to
   session setting `executor.enabled=true`; it cannot override the operator gate.

Disabled calls create no executor client connection, read no OpenAI credential,
and require no SDK/CLI in the voice image. Browser requests cannot configure a
service URL, token, model or credential. The existing P0 deployment script does
not apply the optional manifest.

Build the separate image from the executor directory:

```sh
docker build -t <executor-image>:<git-sha> executor/
```

It pins `openai-codex==0.157.1`, including its CLI runtime, and runs as UID 10001.
For Kubernetes, review `deploy/executor.yaml`, replace its image with an immutable
digest, create `jev-codex-credentials` (`api-key`) and `jev-executor-access`
(`token`, at least 32 random characters) out of band. Set the executor gate true
and replicas to exactly 1. On the voice Deployment set:

```text
JEV_CODEX_ENABLED=true
JEV_EXECUTOR_URL=http://jev-executor:8080
JEV_EXECUTOR_TOKEN=<from jev-executor-access Secret>
```

Inject `OPENAI_API_KEY` ONLY into the executor from its separate Secret. Never
bake it into an image or mount desktop auth. The SDK logs in once per call;
CODEX_HOME and work directories live in private memory-backed volumes. The
service token is for host-to-executor authorization, not an OpenAI credential.
Ingress NetworkPolicy allows only the voice workload; no public Ingress exists.
Use an approved outbound proxy/policy for provider egress in the target cluster.
There is no claim that the supplied ingress policy restricts egress.

To disable for future calls, turn off the operator gate and restart the voice
host; disable/scale down the executor after active calls drain. The UI checkbox
is session-start-only. This is not a live administrative kill switch.

## Failure and lifetime contract

P1 is a single-replica, in-memory session service. Recreate updates terminate
active sessions. No sticky routing, durable replay or cross-Pod resume is
claimed. An unknown session returns 404; the client reports unavailable and does
not create a replacement thread. A failed/ambiguous SDK turn makes that call's
executor unavailable. Voice remains usable. Start a new call to recover.

Per replica: 8 calls, 8 pending inputs/call, 256 accepted inputs/call, 60-second
model timeout, 15-minute idle input TTL. Polling does not extend TTL. Limits and
network failures are explicit errors, not silently dropped input or retries.
Duplicate identical revisions are acknowledged once; conflicting/stale revisions
are rejected. Recent model plans are not a source of truth for committed files.

Private API (all except health require Bearer service token):
`POST /sessions`, `POST /sessions/{id}/inputs`, `GET /sessions/{id}`, and
`DELETE /sessions/{id}`. Input schema is exactly `input_revision`, `text`,
`context`. POST acknowledges queue admission with 202, never model completion.
Status exposes bounded summaries, revision and artifact metadata, not raw SDK
errors, reasoning, auth or host paths.

## Validation boundary

Offline tests cover session reuse/isolation, sequential input, stale write
fences, duplicate admission, bounds, close/error/restart behavior, API auth,
disabled mode, nonblocking voice and result prompt/history semantics. SDK tests
inject transport responses; they do not establish paid model behavior or account
entitlement. No live credential or deployment is part of this PR.
