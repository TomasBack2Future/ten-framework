# Turn control session configuration (v1)

Server loads the `turn_control` node property once per session. No hot config
updates: restart the session to change settings. The UI may expose only
`turn.enabled`, `start.enabled`, `stop.enabled`, `backchannel.enabled`.
`turn.enabled=false` bypasses semantic classification and uses the bounded
silence timer. `start.enabled=false` holds indefinitely by explicit choice.
Stop means the USER reclaims the floor; assistant proactive interruption is
not implemented and has no `barge_in` switch.

Canonical defaults and range validation live in extension `config.py`.
Unknown keys/types fail startup. Provider: `mock` or `jev`, model `jev-latest`,
endpoint `https://api.typesafe.ai/v1/systemone`, secret_env `JEV_API_KEY`.
Only the server resolves that environment variable; never return node properties
or secrets to a browser. ScaleDown is an offline compression comparison only.
No provider retries in the latency-sensitive path; timeout 800 ms, failure_policy
`bounded_wait` (clarify at the maximum wait) or `hold` (explicit fail closed).
Per-judgment `start.prompt`, `stop.prompt`, `backchannel.prompt` override only
that rubric. Probabilities are provider outputs; mock output is labeled mock.

Scheduling: merge_ms 80, min_interval_ms 120, max_wait_ms 5000, max_inflight 1.
One in-flight request finishes; one overwritten latest-input mailbox replaces
an unbounded queue. No cancel/restart on partial. Revision/response epoch reject
obsolete results. The absolute wait deadline is anchored to the first pending
input and cannot be extended by subsequent partial/final events.

Waits: answer 250 ms; clarify 900; continuation 1400; explicit_wait 4000;
ignore 1800. Timers are invalidated by new input, stop, pause or disconnect.
At a bounded deadline, answer starts an answer; incomplete/wait starts a brief
clarification; ignore consumes the input without speaking. Final alone grants
no start permission. Agent EOS is ignored.

Backchannel defaults off. Allowed phrases `["Mm-hmm.", "I see."]`, cooldown
5000 ms, result validity 600 ms, threshold .8. It never starts while a main
response or stop acknowledgment is active. Stop threshold .65; start .6.

Observation enabled, include_text false, buffer_limit 256 (range 16–4096).
Text fields are redacted by default. `state.snapshot` reconstructs UI state and
must NEVER replay actions. Relative times use server monotonic elapsed ms.
Event retention is bounded; seq gaps on reconnect are normal. Demo-only
synthetic fixtures explicitly opt in to raw text.

Playback: stop_ack_timeout_ms 500; chars_per_second 14; context_responses 12.
Cancellation sends TTS flush and a response.cancelled observation immediately;
client MUST stop all scheduled sources for that response and reply with its
last actually played cursor. New output waits for the acknowledgment or bounded
timeout. A timeout is confirmed=false. Provider word alignment + browser cursor
retains fully heard words; fallback character-rate truncation is clearly an
estimate. Neither reports sample-exact knowledge of what a human heard.

## Browser transport

Use official websocket_server envelopes, extended by the Web owner:
- observation: `{type:"data",name:"jev_event",data:<v1 event>}`
- feedback: `{type:"data",name:"jev_playback",data:{response_id,played_ms,stopped,completed}}`
- control: `{type:"data",name:"jev_control",data:{action:"snapshot"|"stop"|"pause"|"resume"}}`
- synthetic text injection: `{type:"data",name:"jev_asr",data:{text,final,segment_id}}`
  (demo mock/replay only; live uses TEN asr_result).
- audio: `{type:"audio",audio:<PCM16 base64>,metadata:{response_id,...}}`

`configure` is rejected; allowlisted toggles belong in the server session start
endpoint. Client must fence response IDs, clear on cancel, report played_ms
periodically and with stopped=true after cancellation, completed=true on drained
playback. Output generation complete is NOT playback complete. Upon reconnect,
request snapshot and never resume old audio. Single WS client per demo session.

## Public provider graph

Planned overseas chain: Deepgram ASR → this extension → openai_llm2 → this
extension → ElevenLabs TTS → this extension (response fence + metadata) → WS.
Keys: DEEPGRAM_API_KEY, OPENAI_API_KEY, ELEVENLABS_TTS_KEY, JEV_API_KEY.
Default offline graph needs no keys. Real speech is unverified until keys and a
microphone/playback session exercise the complete graph.
