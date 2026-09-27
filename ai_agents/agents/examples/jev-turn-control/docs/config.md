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

Overseas chain: Soniox ASR → this extension → openai_llm2 (Groq) → this
extension → Cartesia TTS → this extension (response fence + metadata) → WS.
Keys: SONIOX_API_KEY, GROQ_API_KEY, CARTESIA_API_KEY, JEV_API_KEY.
Default offline graph needs no keys. Real speech is unverified until keys and a
microphone/playback session exercise the complete graph.


Defaults verified with synthetic live requests: Soniox stt-rt-v3, Groq
openai/gpt-oss-20b (the tested key cannot access llama-3.3-70b-versatile),
Cartesia sonic-3 / voice a0e99841-438c-4a64-b679-ae501e7d6091, PCM16 mono 16kHz,
enable_words=true. Models/voice can be changed via SONIOX_MODEL, GROQ_MODEL,
CARTESIA_MODEL, CARTESIA_VOICE_ID at server start. All endpoints are overseas.
Soniox final tokens are committed ASR segments, not a user turn boundary.
Cartesia words arrive as word/start_ms/duration_ms and accumulate per response.
`response.text` carries generated text (no reasoning), `response.audio_completed`
means generation drained; browser reports completion only after its sources drain.
The protected demo runner opts in to include_text; base extension stays redacted.
`stop.max_wait_ms=800` conservatively yields if high-frequency input prevents
any current stop judgment from applying. Supported short acknowledgments that
have a current continue judgment do not trigger this fallback.

## Conversation memory and voice prompt

`voice.prompt` overrides the default voice assistant prompt (max 2000 characters).
The default describes the actual TEN → Soniox → Jev turn decisions → Groq →
Cartesia path, answers briefly in the user's language, asks at most one question,
and explicitly has no search, booking, filesystem or executor capability.
The official OpenAI-compatible adapter receives one `request.prompt` system message,
followed by all retained user/assistant messages and the current user input.
`context.request` records message counts/revision, never an API key.

History no longer silently evicts the oldest message every 12 entries. Completed
playback commits full text only after LLM completion, TTS completion, nonempty audio
and a matching browser drain cursor. This remains a browser estimate, not acoustic
proof. Stops use Cartesia word times normalized by the first PCM frame timestamp;
without alignment the character estimate remains marked. Late stop ACKs/word times
can repair retained old replies without reactivating them. Backchannels do not enter
main history. `playback.context_responses` now bounds late-correction response records,
not the conversation message window. New calls start fresh; reconnect within the
10-second grace keeps the same call. End call destroys memory.

## Optional background compression

Default **off**, independent of turn/start/stop/backchannel settings. Enable in the
session panel or set `compression.enabled` on the controller. Compression never
blocks foreground speech or grants permission to start speaking.

| Setting | Default | Meaning |
|---|---:|---|
| `enabled` | false | Run background memory jobs |
| `trigger_chars` | 8000 | Soft trigger, configurable 1000–24000 |
| `keep_turns` | 3 | Preserve recent user turns and their replies verbatim (1–12) |
| `threshold` | 0.7 | Minimum Jev compress probability |
| `prompt` | built in | Jev compress/retain rubric override, max 2000 chars |
| `summary_prompt` | built in | Groq summary instructions override, max 2000 chars |
| `timeout_ms` | 10000 | Total decision + summary deadline (1000–30000) |
| `cooldown_ms` | 30000 | Minimum interval between attempts |
| `max_summary_chars` | 4000 | Reject oversized/empty/nonshrinking summaries |
| `max_chars` | 48000 | Hard history+summary capacity; reserve 24000 for each answer |
| `max_messages` | 128 | Hard retained-message capacity |

A job snapshots old history with a context revision. Jev chooses compress/retain;
Groq summarizes only user messages and fully browser-confirmed assistant replies.
Interrupted assistant estimates are excluded from summaries even with word times,
since late alignment may still revise them. Names, constraints and pending requests
must be preserved without inferring diagnoses/gender or attributing assistant
suggestions to the user. Recent turns remain unchanged. New history/late corrections
invalidate stale results. Provider failures/timeouts keep original history. At the
hard capacity the controller emits `context.capacity` and stops adding replies;
the UI asks for a new call rather than silently forgetting facts.

Events: `context.decision` (started/completed), `context.summary` (started),
`context.applied`, `context.stale`, `context.failed`, `context.capacity` and
`context.request`. Summarization is lossy and remains opt-in; provider-level fixed
cases are not a guarantee for arbitrary conversations.
