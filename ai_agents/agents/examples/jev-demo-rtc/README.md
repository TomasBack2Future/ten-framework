# Jev demo over RTC — integration in progress

An additional `jev-demo-rtc` service; the existing `jev-turn-control` WebSocket service, image, deployment and evidence volume are not modified. This integration is not yet accepted for deployment: dependency resolution, native extension contract checks, real channel audio and interruption acceptance remain required.

## Architecture

The RTC graph follows `../demo/tenapp/property.json` and its cascade controller's `flush` command. It reuses the unchanged Jev/ASR/LLM/TTS pipeline from `../jev-turn-control/scripts/run_graph.py`, replacing only the transport node and the playback-feedback adapter. Agora carries microphone input and assistant audio. A loopback WebSocket carries events and controls only; the public gateway rejects PCM and browser playback acknowledgments.

The browser uses the same workflow UI assets, session controls and hidden unlimited gesture. Ordinary sessions expire after five minutes. Session IDs create separate `jev-rtc-<id>` channels, with browser UID 1001 and agent UID 1002. Tokens are generated and renewed on the server for that exact channel and UID. The certificate never goes to the browser. App ID: `518383bde9d44172961da1595e982189`.

## Interruption contract

1. Jev cancels the active reply and its generator/TTS, using the existing reducer.
2. The RTC transport invalidates the reply and drops queued PCM before awaiting any SDK command.
3. It sends `flush`, then explicit audio `unpublish`, serializing both with outgoing frames. Failure prevents another reply from publishing.
4. A new reply explicitly publishes before its first 10 ms PCM frame. Old response PCM and delayed old stop requests cannot affect it.
5. The browser handles `user-unpublished` and resubscribes after `user-published`; it does not hold a PCM buffer.

The upstream demo proves use of `flush`, but does not by itself prove the installed extension's unpublish behavior. The public demo pins `agora_rtc =0.23.9-t1`; this version's command semantics and real Web SDK callbacks MUST be checked before release. A different locally cached `0.26.0-rc3` manifest exposes flush/publish/unpublish and `flush_by_unpub`, but is not evidence that the public pinned version has identical behavior. This integration does not guess a value for `flush_by_unpub`.

Server emission is not confirmed remote playback. RTC progress is explicitly `confirmed=false`, and uses a conservative server-emission estimate with a 250 ms allowance. It cannot mark a reply fully played. This allowance is a prototype estimate, not a measured network guarantee. Real interruption tests must quantify browser residual audio and ensure old audio cannot restart.

## Install and local launch

Use a Linux TEN runtime environment with network access. From this directory:

```sh
task install
# The first npm resolution must produce web/package-lock.json; review and commit
# that lock before any release build. Later release builds use npm ci.
export AGORA_APP_CERTIFICATE_FILE=/absolute/private/path/.secret/agora
# Supply JEV_API_KEY, SONIOX_API_KEY, GROQ_API_KEY, CARTESIA_API_KEY server-side.
python3 scripts/run_local.py
```

`task install` and native runtime launch have NOT been verified in the restricted development environment. The RTC Web SDK and token-library pinned versions also require package resolution and signature verification.

## Validation

```sh
python3 -m unittest discover -s tests -v
cd web
npm test
npm run check
```

The offline tests cover pacing, old-response fencing, delayed flush vs new publish, fail-closed flush, natural drain, real reducer stop release, channel isolation, browser join/publish/subscribe, renewal, cleanup and late callbacks. Mock SDK tests do not establish actual RTC network behavior.

## Independent deployment

`deploy/demo.yaml` creates only `jev-demo-rtc` Deployment/Service/Ingress and `jev-demo-rtc-evidence` PVC in the existing namespace. Its hostname is `jev-demo-rtc.hipaa-poc.agoralab.co`, TLS secret is `jev-demo-rtc-tls`, and credential secret is `jev-demo-rtc-credentials`. These must be provisioned independently; no command should update the WS resources.

Build `Dockerfile` with an immutable, known-good `WS_IMAGE` base and `REVISION`. This packages unchanged provider/runtime dependencies into a separate RTC image. The build deliberately refuses to proceed without a resolved lockfile. Resolve and verify the public RTC package, build on Linux, then deploy an immutable image digest only after:

- Native graph starts and both identities join the expected isolated RTC channel.
- Live microphone → ASR → Jev → LLM → RTC speech works over HTTPS.
- Mid-reply interruption proves flush/unpublish, queue discard, no stale tail, and publish/resubscribe on the next reply.
- Natural completion, repeated interruptions, mute/unmute, microphone off, reconnect, token renewal, five-minute expiry and hidden unlimited mode pass.
- At least two simultaneous sessions are isolated, with no browser PCM media path.
- Existing WS health/revision and deployment/PVC identity remain unchanged before and after deployment.

Until these pass, this is an implementation checkpoint, not a deployed RTC service.
