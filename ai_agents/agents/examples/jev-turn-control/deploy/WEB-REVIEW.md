# Web and deployment review

Baseline: public TEN Framework ca00160c79d277a6179b5bd7af3c585db4c8f3db.
Reviewed `websocket-example/frontend/src/lib/audioUtils.ts`,
`hooks/useAudioPlayer.ts`, `manager/websocket.ts`, `frontend/server.js`,
`tenapp/property.json`, and `main_python/extension.py`.

Reusable: PCM16 mono/base64 envelopes, getUserMedia and Web Audio transport,
WebSocket data/cmd/audio separation, same-origin WebSocket reverse proxy.
The new small browser client preserves these public wire conventions.

Missing in the reference: active AudioBufferSource cancellation, response-id
fencing, playback acknowledgments, reconnect snapshots, decision observations,
access control and session budgets. Its recorder uses ScriptProcessor; this
example uses an AudioWorklet with 20 ms chunks. Its main controller treats ASR
final as permission to answer and is not reused. The standard Agora playground
requires an additional RTC credential/transport and does not provide cursor
acknowledgments; the WebSocket example is a smaller fit for this single graph.

The official WebSocket extension needed three bounded changes: whitelist
browser control/playback/mock-ASR data; broadcast jev_event; read audio metadata
through the TEN JSON property API (the old string getter returns a tuple and
could silently lose response identifiers). No arbitrary browser TEN commands.

UI uses textContent for all provider/user text. No chain-of-thought is displayed.
Playback cursor subtracts browser-reported latency from scheduled AudioContext
time, but remains an estimate. Word timestamps improve retained text only when
available. A new response starts only after response.started; snapshots do not
restart old audio. Session settings apply on the next session, not hot updates.

Gateway: one concurrent session, five-minute hard limit, access-code login with
HttpOnly/SameSite cookie, same-origin HTTP and WSS, bounded messages and input,
allowlisted configuration, process termination on end/timeout. All API keys are
server-side environment variables. No kubeconfig is mounted into the pod or CI.
The optional execution adapter remains disabled and receives no cluster rights.

TLS is dedicated to jev-demo.hipaa-poc.agoralab.co in namespace ten-jev-demo.
The cluster has Kong but no cert-manager CRDs. A bounded HTTP-01 challenge
service issued a Let's Encrypt certificate. Renewal is a manual operational
step before 2026-12-26; this repository does not claim automatic renewal.

A web-only preview image replays clearly marked fixtures without TEN or vendors.
The full runtime image is separately built and tested before live deployment.
Do not describe fixture replay as a successful voice call.
