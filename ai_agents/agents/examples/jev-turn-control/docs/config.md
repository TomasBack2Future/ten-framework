# Turn control session configuration (v1)

Server loads the `turn_control` node property once per session. No hot config
updates: restart the session to change settings. The UI exposes allowlisted
provider/profile choices, feature switches and bounded prompt/memory options.
Executor availability is additionally gated by the operator configuration.
`turn.enabled=false` bypasses semantic classification and uses the bounded
silence timer. `start.enabled=false` holds indefinitely by explicit choice.
Stop means the USER reclaims the floor; assistant proactive interruption is
not implemented and has no `barge_in` switch.

Canonical defaults and range validation live in extension `config.py`.
Unknown keys/types fail startup. Live providers are `jev` (default), `sd` and
`sd_jev`; `mock` is reserved for synthetic transport. The tuned candidate pins
Jev to `jev-1.13.0`; baseline preserves `jev-latest`. Only the server resolves
`JEV_API_KEY` / `SCALEDOWN_API_KEY`; never return credentials to a browser.
See [decision modes](../DECISION_MODES.md) for full instructions, criteria,
thresholds, baseline comparison and provider-specific endpoints.
No provider retries in the latency-sensitive path; timeout 800 ms, failure_policy
`bounded_wait` (clarify at the maximum wait) or `hold` (explicit fail closed).
Per-judgment `start.prompt`, `stop.prompt`, `backchannel.prompt` override only
that rubric. Probabilities are provider outputs; mock output is labeled mock.

Scheduling: merge_ms 80, min_interval_ms 120, max_wait_ms 5000, max_inflight 1.
One in-flight request finishes; one overwritten latest-input mailbox replaces
an unbounded queue. Listening waits for a stable partial for at least
max(merge_ms, min_interval_ms). Speaking keeps a bounded merge delay for stop
judgments; it does not also ask a speculative start question. Backchannel
playback can still be preempted by an accepted main response. No cancel/restart
on partial. Immutable request IDs and revision/response epoch fences reject
obsolete results. Request context is a deep snapshot; late word alignment cannot
pin a request in flight. Whitespace-only duplicate input does not revise state.

The maximum response wait is measured from the LAST input, never the first
partial in a long utterance. A confident continuation keeps the user's floor.
Only sustained silence at max_wait_ms can produce one bounded clarification;
further incomplete fragments cannot repeatedly prompt until an accepted main
answer/clarification resets that guidance budget. wait.continuation_ms remains
accepted for v1 compatibility but no longer schedules an automatic clarification.

Waits: answer 250 ms; clarify 900; explicit_wait 4000; ignore 1800. Wait/ignore
consume input without speaking, including low-confidence labels as conservative
vetoes. Timers are invalidated by new input, stop or disconnect. Pause suspends
the accepted timer label and its remaining delay; resume restores it only if its
input revision still matches. New input while paused gets a fresh decision.
Final alone grants no start permission. Agent EOS is ignored.

The baseline start threshold is .6. For a final segment with a below-threshold winning label,
answer+clarify probability can satisfy the parent "ready to respond" category.
The larger child probability selects answer versus clarify; a tie clarifies.
This does not override an explicit_wait/ignore label. Observations retain the
provider's original label/score and record effective_label/effective_score when
applying a start policy. Tuned Jev instead uses top-label scoring at .47;
tuned SD / SD → Jev use combined answer+clarify only for an already-selected
answer or clarify, at .95 / .54 respectively. This is a timing policy, not
proof of semantic accuracy.

Backchannel defaults off. Allowed phrases `["Mm-hmm.", "I see."]`, cooldown
5000 ms, result validity 600 ms, baseline threshold .8 (tuned Jev .71,
SD .62, SD → Jev .74). Only continuation allows it;
answer, clarify, wait and ignore veto it. It never starts while a main response
or stop acknowledgment is active. Stop threshold .65 (tuned SD .49). A backchannel older than
600 ms is intentionally dropped even if the provider succeeds within its 800 ms
timeout: a late acknowledgment should not interrupt a newly developing thought.

The tuned Jev stop question favors yielding when the user clearly initiates a new
topic, task, or complete request addressed to the assistant. It keeps short
acknowledgments, requests to another person, and unfinished ASR prefixes from
claiming the assistant's floor. This changes the question and criteria, not the
stop threshold or the independent backchannel decision.

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

The session-start `voice.language` setting accepts `en` (default), `ja`, or
`ko` in both the WebSocket and RTC demos. English keeps the configured
`CARTESIA_VOICE_ID`; Japanese selects Cartesia voice
`861213b7-f057-45c8-9527-0f4c144f1a03` with TTS language `ja`, and Korean
selects voice `90dba946-774b-40ed-98d9-ac3835117827` with language `ko`.
Soniox remains multilingual. The language is fixed for a session; choose it
before starting a new call. Japanese and Korean also select backchannel phrases
in the chosen language.

`voice.prompt` overrides the default voice assistant prompt (max 2000 characters).
The default describes the actual TEN → Soniox → Jev turn decisions → Groq →
Cartesia path, answers briefly in the chosen session language, asks at most one question,
and explicitly has no search, booking, filesystem or executor capability.
The session language instruction is appended even when `voice.prompt` is overridden,
so the prompt and configured TTS voice stay aligned.
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

Full-playback integrity additionally requires `tts_audio_end.reason=REQUEST_END`
(`1`) and a finite positive provider `request_total_audio_duration_ms`. Its unit is
milliseconds; it must match forwarded PCM sample duration within **2 ms** (integer
rounding only). Missing/mismatched duration, `INTERRUPTED` (`2`) or `ERROR` (`3`)
never authorizes full text. Duplicate consistent ends are idempotent; an abnormal
end cannot be upgraded by a later normal end. Without word alignment an unverified
completion stores no guessed text. Browser drain cursor tolerance remains 30 ms
and is explicitly an estimate; it is not acoustic proof.

Summary payloads must contain a nonempty `choices` array, a message with nonempty
string content, and `finish_reason=stop`. Every job releases its reservation even
on unexpected provider exceptions, timeout or cancellation. Cancellation is
re-raised (not swallowed), failures keep original memory, and cooldown limits
subsequent attempts.

## Optional P1 execution

`executor.enabled` defaults to false and applies only at call start. The session
checkbox also requires operator `JEV_CODEX_ENABLED=true`; it cannot enable an
unconfigured deployment. See `../executor/CALL_SESSIONS.md` for the separate
service, credential injection and one-call/one-thread lifecycle. The normal
voice image has no SDK dependency and remains usable on executor failure.
