# Dedicated demo operations

Only namespace `ten-jev-demo` is managed. The existing Kong gateway is reused;
no existing application, Service, or Ingress is changed. No cluster identity is
mounted into the pod. The image runs as UID 1000 with dropped capabilities.

## Release

The fork-only `Jev demo` workflow runs web checks/tests/format, builds the small
preview image, and builds a separate full TEN runtime image. A real native
WebSocket mock graph must pass in `--network none` before the runtime is
published to `ghcr.io/tomasback2future/jev-turn-control:<full commit SHA>`.
Pull requests cannot publish and never receive cluster credentials. Inherited
upstream release workflows are removed only from this demo branch.

Use an immutable registry digest, not `latest`:

```bash
export KUBECONFIG=/path/to/operator.kubeconfig
bash deploy/deploy.sh sha256:<verified-digest> live
curl -fsS https://jev-demo.hipaa-poc.agoralab.co/healthz
```

`/healthz` returns mode and source revision; it proves the gateway is ready.
A voice acceptance probe must separately exercise the graph and providers.
The cluster has no suitable dedicated Actions runner/short-lived identity yet.
Deployment is an explicit local operator action; no privileged kubeconfig is
uploaded to GitHub. CI does not imply automated cluster deployment.

Required existing Secrets (only in this namespace):

- `jev-provider-keys`: `SONIOX_API_KEY`, `GROQ_API_KEY`, `CARTESIA_API_KEY`, `JEV_API_KEY`.
- `jev-demo-access`: `JEV_ACCESS_CODE` (shared demo access code).
- `jev-demo-tls`: dedicated TLS certificate/key.

Provider secrets enter only the live pod environment. The public web-only
preview and mock runtime need no provider credentials. The login cookie lasts
one hour; each session has a five-minute hard deadline and only one concurrent
visitor. Access code retrieval is an operator action:

```bash
kubectl -n ten-jev-demo get secret jev-demo-access -o jsonpath='{.data.JEV_ACCESS_CODE}' | base64 --decode
```

Never paste provider keys into the demo. The visible prompt field only overrides
the start-decision rubric and applies to the next session. Backchannel defaults
off. The optional executor is disabled; stop playback does not cancel a task.

## Rollback

End any active demo session, then:

```bash
kubectl -n ten-jev-demo rollout undo deployment/jev-demo
kubectl -n ten-jev-demo rollout status deployment/jev-demo --timeout=120s
```

Or run `deploy.sh` with a previously verified runtime digest and mode. Deployment
strategy is Recreate because the demo owns one fixed internal WebSocket port.
Rollback must recheck `/healthz` and an authenticated snapshot. Do not delete the
namespace, Secrets, or shared Kong gateway as a rollback operation.

## TLS renewal

Kong supports WSS; upstream read/write timeouts are 360 seconds. This cluster
has no cert-manager CRDs. The dedicated certificate initially expires
2026-12-26. Renewal is manual; no automatic-renewal claim is made.

Apply `deploy/acme.yaml`, then use Certbot HTTP-01 with
`--manual-auth-hook "$PWD/deploy/acme-auth.sh"` and the exact demo domain.
Keep Certbot account, work, and private-key files outside Git. Update only
`jev-demo-tls` using `kubectl create secret tls ... --dry-run=client -o json |
kubectl -n ten-jev-demo apply -f -`. Verify with normal certificate validation;
never use `curl -k` as an acceptance check. Scale the challenge deployment to
zero when finished; retain the route for the next renewal.

## Debug sessions and observations

After authenticating, click **TURN CONTROL LAB** 10 times, with no gap over two
seconds, to disable the session expiry for this page. If connected, the server
clears the active expiry timer; if disconnected, the next call carries the debug
flag. Reloading resets the gesture. Authentication, single visitor, size/rate and
playback backpressure limits remain. Normal calls still expire after five minutes.

The runtime writes bounded JSONL observations to `JEV_EVENT_LOG_DIR` (default
`/tmp/jev-observations`): up to 10 session files, 2 MiB each, mode 0600. Records carry
build revision/session/response IDs and ASR/decision/timer/generation-error/playback/
alignment events. Text is redacted by default; set `JEV_EVENT_LOG_TEXT=1` only for
an authorized transcript investigation. Credentials are always redacted. No audio
is recorded. Files survive graph process exits, but are **not durable across Pod
replacement**: export needed evidence before rollout. No HTTP log-download endpoint
is exposed. A storage/backpressure cap emits `observation.limit` instead of growing
unbounded. Export through authorized namespace-scoped `kubectl exec`/`cp` only.

`JEV_TRUST_PROXY=1` uses validated `X-Real-IP` for failed-login limits. Enable only
behind an ingress that overwrites this header. The dedicated khipaa Kong config was
verified to set `X-Real-IP $remote_addr`; the manifest opts in. Direct local runs
ignore forwarded headers. Successful logins do not consume the failure allowance.

The gateway sends `ready` only after the TEN WebSocket is connected. The microphone
stays disabled during warmup; early control messages are bounded/queued and early
PCM gets an explicit error. Disconnect sends stop and the last known cursor before
closing upstream. The browser also resends its final stopped cursor after reconnect,
and the engine can repair a timed-out old response without changing the new one.

Every image build downloads and SHA256-checks the pinned runtime package before
`tman install` uses that verified cache. Publication is not deployment. Review and
merge all scoped PRs, build the merged release SHA, pin the image digest, then deploy
once after release approval. Existing demo stays unchanged during this process.
