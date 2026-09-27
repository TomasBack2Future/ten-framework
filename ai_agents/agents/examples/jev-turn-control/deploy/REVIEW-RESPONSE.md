# Review response: memory and gateway repair candidate

This candidate is not deployed. Current demo remains `35c4ebd`; publication must
follow review → fixes → review of final SHA → merge all three PRs → one deployment.

| Finding | Disposition and regression |
|---|---|
| PR1 P0: slim image lacks bash | Refuted against running immutable image: `/usr/bin/bash`, Node 22.21.1, Python 3.10.18. Existing native graph/live evidence also contradicts it. The separate spawn-error reservation edge case is fixed/tested. |
| PR1 reconnect loses stop ACK | Gateway sends stop + last cursor before upstream close; browser retains/resends final stopped cursor after explicit ready. Engine accepts late ACK for retained finished response only. Tests cover disconnect forwarding and r46-style 4541→13059ms repair without touching new active response. |
| PR1 concurrent session POSTs | Repeat reservation check after request-body await, before creating process; simultaneous requests return one 200 and one 409. Connect disables immediately. |
| PR1 early PCM/control loss | Explicit graph `ready`; mic disabled until ready; bounded early-control queue, explicit PCM warmup error. Fake upstream delayed-start regression. |
| PR1 shared proxy login bucket | Optional trusted `X-Real-IP`, successful logins do not consume failed-attempt budget. Verified khipaa Kong overwrites header with `$remote_addr`; manifest opts in. Separate client regression keeps rate limiting. |
| PR1 runtime checksum gap | `cache-runtime.sh` downloads the pinned tpkg and verifies SHA256 inside each runtime Docker build before tman install. Immutable deployment still uses digest, not tag. |
| PR1 probe Origin | `validate_live.py` supplies derived/explicit Origin and awaits ready for cookie-authenticated gateway. Cursor remains explicitly synthetic, not an acoustic test. |
| Real call: destination forgotten | Remove deque(12) silent eviction. Repeated cancellations/backchannels no longer evict first facts. Maya + Shanghai/San Francisco after seven cancelled fragments regression. Bounded capacity now fails explicitly instead of silently deleting memory. |
| Real call: completed reply truncated | Commit complete text only with LLM/TTS end + nonempty forwarded audio + browser drain cursor. No-audio completion is rejected as full playback. |
| Real call: all timestamps discarded | Cartesia emits epoch ms; controller used relative 0..3600000 filter. Normalize against first PCM timestamp, bounded pending words if words arrive first. Preserve provider whitespace. Epoch, late alignment and interrupted prefix regressions. |
| PR3: late alignment mutates inflight snapshot | History/action/decision snapshots deep-copied. Decision owner separately adds explicit request IDs; integrate and rerun together. |
| PR3: duplicate user in LLM input | Refuted: `start` captures context before appending current user. Real official-adapter HTTP messages test confirms one current user; real Groq multi-turn probe confirms all previous messages. |
| PR3: duplicate final/late partial | Timed Soniox results at/before the already finalized end are ignored; identical consumed segment is not restarted. A genuinely new segment with same words remains accepted. |
| PR3: final cursor cannot shrink | A confirmed stopped/completed cursor may correct an earlier estimate downward. Late correction never revives the response. |
| PR3: backchannel context pollution | Main conversation excludes backchannel playback; test preserves history across acknowledgment. |
| PR3: shutdown abort not pumped | Explicit bounded LLM abort/TTS flush before task cancellation; regression checks abort of active response. |
| Groq no-tool errors/capability fiction | Default voice prompt states actual modules and disabled executor/search/booking; `tool_choice=none`; at most one pre-output retry, then audible safe fallback if TTS works. Partial-output failures stop rather than mixing speculative text. Test injects two tool-choice errors; real Groq refuses live search/booking. |
| Ten-click debug request | Page-local 10 clicks with ≤2s gaps; authenticated current-session timer removal or next-session flag. Default TTL/unauthenticated rejection/old timer cleanup/nonconsecutive clicks/single-session tests. |
| Future incident evidence | Bounded, private JSONL observations; revision/session/response IDs, ASR, decision, timers, sanitized failures, alignment, playback. Default redacts text and all credentials; explicit text opt-in. Files survive graph exit but require export before Pod replacement. Rotation/redaction/permissions tests. |

## Verification and limits

- 32 Python reducer/memory/native TEN/WebSocket tests; Black, Pylint 10/10 and TEN
  manifests/property schemas passed on Ubuntu.
- 12 Node gateway/player/debug/observation tests; syntax and Prettier passed on
  macOS Node 24 and Ubuntu Node 22.
- Actual official Groq adapter HTTP payloads: one system prompt, 2/4/6 messages
  across successive turns. Maya, peanut restriction and unfinished dinner retained.
- Actual Jev compression decision (`compress`, 0.81) → Groq summary → application →
  follow-up answer preserved facts. Summary did not infer allergy/gender and kept
  assistant suggestions attributed to assistant. This is a fixed synthetic case,
  not a broad accuracy guarantee. Compression remains default off.
- Independent parent comparison includes original→Jev vs ScaleDown compression→Jev,
  and original/ScaleDown old prefixes→Groq summary. Earlier weaker summary prompts
  distorted allergy/speaker attribution, motivating the stricter prompt. ScaleDown
  is not an independent classifier. No performance claim from single samples.
- Provider probe ran in a temporary directory in the existing demo Pod without
  changing its deployment/graph. Synthetic playback acknowledgement is not human
  microphone or acoustic acceptance. Final merged-image live graph, HTTPS/WSS and
  digest verification remain the release gate.
- The turn timing/continuation/maximum-wait policy is owned by PR3. Executor stays
  disabled and its review fixes are owned by PR2. This candidate must not be treated
  as the final integrated release until both are merged and rechecked.

## Integrity follow-up after afce67d

Self-review found and repaired two additional edges: abnormal TTS end could permit
full-text commitment, and an unexpected summary shape could strand the job slot.
Normal TTS end now requires explicit positive provider duration within 2 ms of
forwarded PCM; abnormal/missing/mismatched end retains only aligned heard words,
otherwise no guessed completion text. Tests cover partial audio then ERROR with
LLM done, INTERRUPTED, missing duration, no audio, mismatch, duplicate and late end.
Summary shape validation plus guaranteed job cleanup covers empty choices, missing
message/content, timeout, unexpected exception and propagated cancellation; originals
remain and cooldown-bounded subsequent scheduling works.
