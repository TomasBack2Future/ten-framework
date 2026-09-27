# Input lifecycle and playback terminal contract

The reducer consumes an input cycle when a main response starts, an `ignore` or
`explicit_wait` timer expires, or a manual/buffer-limit control stop arrives.
Consumption cancels its timer and clears segment assembly. A repeated final for
the consumed segment is ignored. Valid subsequent input starts a new cycle and
renews its guidance budget; partial revisions within a pending cycle do not.
`input.consumed` observations contain `reason` and `cycle`; snapshots expose
`input_cycle`. Conversation history remains independent of the assembly buffer.

After playback releases the floor, an overlapping pending input must receive a
current start decision before its old deadline can launch a response. Tick order
and provider latency therefore cannot bypass that decision. Stop/continue alone
does not consume a possible follow-up. `ignore` consumes an acknowledgment;
`answer` preserves a real follow-up; `explicit_wait` preserves the hold policy.
Provider failures retain the configured `hold`/`bounded_wait` behavior, after the
current decision attempt. This does not add silence polling or change delays,
prompts, profiles, or thresholds.

Natural completion requires final generation, consistent successful audio end
metadata and the existing cursor tolerance. A short completed cursor remains
partial; a later larger completed cursor may repair that response's history if
all evidence verifies. A confirmed stopped terminal is immutable. A stop request
wins a concurrent completed ACK; a provisional stop timeout can be corrected by
one confirmed stopped ACK, never promoted by completed. A verified natural
completion is terminal. Duplicate ACKs neither append history nor bump its
revision, and old response ACKs do not release a newer response.

`tests/test_input_lifecycle.py` uses fixed decision outputs and injected times.
The 49c0d169 regression uses the visible question, score, and relevant timing;
redacted prior text and aligned output examples are explicitly synthetic. It is
not a reconstruction of missing audio or transcript. Existing memory/duration
coverage checks alignment and incomplete generation/audio. Browser cursor
accuracy is a separate dependency; this reducer does not infer unheard text from
`completed=true`.
