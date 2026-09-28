# Jev demo over RTC

An additional `jev-demo-rtc` service; the existing `jev-turn-control` WebSocket service, image, deployment and evidence volume are not modified. Native graph startup, browser audio, real interruption behavior and rollout are separate acceptance gates; see below.

## Architecture

The RTC graph follows `../demo/tenapp/property.json` and its cascade controller's `flush` command. It reuses the unchanged Jev/ASR/LLM/TTS pipeline from `../jev-turn-control/scripts/run_graph.py`, replacing only the transport node and the playback-feedback adapter. Agora carries microphone input and assistant audio. A loopback WebSocket carries events and controls only; the public gateway rejects PCM and browser playback acknowledgments.

The browser uses the same workflow UI assets, session controls and hidden unlimited gesture. Ordinary sessions expire after five minutes. Session IDs create separate `jev-rtc-<id>` channels, with browser UID 1001 and agent UID 1002. Tokens are generated and renewed on the server for that exact channel and UID. The certificate never goes to the browser. App ID: `518383bde9d44172961da1595e982189`.

## Interruption contract

1. Jev cancels the active reply and its generator/TTS, using the existing reducer.
2. The RTC transport invalidates the reply and drops queued PCM before awaiting any SDK command.
3. It sends `flush`, then explicit audio `unpublish`, serializing both with outgoing frames. Failure prevents another reply from publishing.
4. A new reply explicitly publishes before its first 10 ms PCM frame. Old response PCM and delayed old stop requests cannot affect it.
5. The browser handles `user-unpublished` and resubscribes after `user-published`; it does not hold a PCM buffer.

The installed `agora_rtc =0.23.9-t1` manifest exposes `flush`, `publish`, and `unpublish` with an `audio` property. Its native libraries load and its graph connects to the RTC channel in a local container smoke test. The command sequence and browser tail behavior still need live audio acceptance; manifest and startup checks alone cannot prove that audio already in the network jitter buffer is silent.

Server emission is not confirmed remote playback. RTC progress is explicitly `confirmed=false`, and uses a conservative server-emission estimate with a 250 ms allowance. It cannot mark a reply fully played. This allowance is a prototype estimate, not a measured network guarantee. Real interruption tests must quantify browser residual audio and ensure old audio cannot restart.

## Install and local launch

Use a Linux TEN runtime environment with network access. From this directory:

```sh
task install
export AGORA_APP_CERTIFICATE_FILE=/absolute/private/path/.secret/agora
# Supply JEV_API_KEY, SONIOX_API_KEY, GROQ_API_KEY, CARTESIA_API_KEY server-side.
python3 scripts/run_local.py
```

The locked npm dependencies install with `npm ci`. The Docker build uses the pinned WS runtime image and adds the RTC native extension; `scripts/start.sh` supplies the native Agora SDK library path. A local container reached the RTC control `ready` event with real server credentials and a session-specific channel.

## Validation

```sh
python3 -m unittest discover -s tests -v
cd web
npm test
npm run check
```

The offline tests cover pacing, old-response fencing, delayed flush vs new publish, fail-closed flush, natural drain, real reducer stop release, channel isolation, browser join/publish/subscribe, renewal, cleanup and late callbacks. Mock SDK tests do not establish actual RTC network behavior.

## Independent deployment

`deploy/demo.yaml` creates only `jev-demo-rtc` Deployment/Service/Ingress and `jev-demo-rtc-evidence` PVC in the existing namespace. Its hostname is `jev-demo-rtc.hipaa-poc.agoralab.co`, TLS secret is `jev-demo-rtc-tls`, and credential secret is `jev-demo-rtc-agora` for the certificate; provider keys are read-only from the existing `jev-provider-keys` Secret. `deploy/acme.yaml` and `deploy/acme-auth.sh` provide a separate HTTP-01 challenge route for this host. These resources must be provisioned independently; no command should update the WS resources.

Build `Dockerfile` with an immutable, known-good `WS_IMAGE` base and `REVISION`. This packages unchanged provider/runtime dependencies into a separate RTC image. The build refuses to proceed without a resolved lockfile. The independent GitHub Actions workflow tests and publishes the RTC image on the feature branch. Deploy an immutable image digest only after:

- Native graph starts and both identities join the expected isolated RTC channel.
- Live microphone → ASR → Jev → LLM → RTC speech works over HTTPS.
- Mid-reply interruption proves flush/unpublish, queue discard, no stale tail, and publish/resubscribe on the next reply.
- Natural completion, repeated interruptions, mute/unmute, microphone off, reconnect, token renewal, five-minute expiry and hidden unlimited mode pass.
- At least two simultaneous sessions are isolated, with no browser PCM media path.
- Existing WS health/revision and deployment/PVC identity remain unchanged before and after deployment.

Until these pass, this is an implementation checkpoint, not a deployed RTC service.
