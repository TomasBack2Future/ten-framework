# Decision workstream evidence — 2026-09-27

## Source and isolation

- Public baseline: ca00160c79d277a6179b5bd7af3c585db4c8f3db.
- Bootstrap: 9f0d29cdbf20b924612a5c35cb76672185bc5537.
- Independent checkout: ten_env:/root/CodeBase/ten-jev-decision.
- Independent container: ten-jev-decision, no published ports.
- TEN runtime/Python binding: 0.11.73; no C++ core modification.
- Web bridge is the Web workstream's c9ab488, cherry-picked as 92772d7.

## Verification boundary

The native offline graph loads, routes commands and data, starts a mock response,
cancels it and processes a played cursor. A real WebSocket process test sends
synthetic input through the public transport, receives tagged PCM and confirms
stop -> playback acknowledgment -> listening snapshot. Unit coverage exercises
continuous partials, revision/epoch fences, invalidated timers, stop priority,
heard-context truncation, backchannel conflicts/cooldown, pause/resume,
disconnect and bounded retention. See tests and the current test report.

Three local live synthetic cases called Jev and ScaleDown on the same inputs.
Jev observed 748.7/290.6/329.2 ms; ScaleDown compression observed
2364.4/948.9/1441.9 ms. Compressed inputs were sent to Jev for the paired labels.
These are tiny connectivity samples from the local client, not a benchmark or
khipaa latency estimate. Raw synthetic results: fixtures/live-jev-scaledown.json.

Local live voice probe succeeded: Groq openai/gpt-oss-20b generated a short
answer; Cartesia sonic-3 generated 46,068 bytes of PCM16 mono 16kHz and four
word-timestamp messages; Soniox stt-rt-v3 emitted partials and the correct final
transcription. The earlier llama-3.3-70b-versatile default returned
model_not_found for the supplied account and was replaced by the tested model.

The actual live TEN graph on ten_env received Soniox partial/final transcription,
but Groq returned HTTP 403 Forbidden from that host and Jev failed there.
The same credentials worked from the local client. Overseas end-to-end
validation belongs to the Web workstream's khipaa integration record; this
workstream does not claim that a successful isolated API probe is a successful
human voice conversation.

## Reproducibility and known constraints

Use openai==1.109.1, httpx==0.28.1 and websockets==15.0.1 for this public-source
snapshot. Unpinned openai resolved to a newer package using httpx2 while the
extension imports httpx. The Web workstream owns installation/image fixes.
Local tman links may require a missing ten_ai_base schema-path fallback in
agents/ten_packages/system; do not copy or change vendor business source.

Base observations redact text. The protected demo runner opts into text for
subtitles and input inspection; keep access restricted and do not use real
customer recordings. Retention is bounded in memory. No API keys, real customer
audio, or commercial code are committed.

## Final local checks and integrated overseas evidence

18 tests passed in 1.94s, including the real native WebSocket graph.
Black, Pylint 10/10, four tman schemas and Python compilation passed.
The Web workstream reported a successful khipaa public HTTPS/WSS live synthetic
loop on integrated commit 5a0dba4: Soniox partial/final, Jev probability results
(65–98ms in that small sample), Groq text, five Cartesia audio frames,
manual stop, simulated 200ms playback feedback and final snapshot.
No provider_error was observed. The integration record and subsequent deployed
revision are owned by https://github.com/TomasBack2Future/ten-framework/pull/1.
This is not microphone or human-listening acceptance.
