# Input lifecycle and playback terminal contract

The reducer consumes an input cycle when a main response starts, an `ignore` timer expires, or a manual/buffer-limit control stop arrives.
Consumption cancels its timer and clears segment assembly. A repeated final for
the consumed segment is ignored. Valid subsequent input starts a new cycle and
renews its guidance budget; partial revisions within a pending cycle do not.
`input.consumed` observations contain `reason` and `cycle`; snapshots expose
`input_cycle`. Conversation history remains independent of the assembly buffer.

After playback releases the floor, an overlapping pending input must receive a
current start decision before its old deadline can launch a response. Tick order
and provider latency therefore cannot bypass that decision. Stop/continue alone
does not consume a possible follow-up. `ignore` consumes an acknowledgment;
`answer` preserves a real follow-up; `explicit_wait` retains unresponded input.
Provider failures retain the configured `hold`/`bounded_wait` behavior, after the
current decision attempt. Ordinary start/stop decisions preserve their revision/epoch fencing.

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

## Retained explicit waiting (TEN-9998)

An accepted `explicit_wait` preserves the input assembly and `pending` flag.
Its timer requests a fresh start judgment with the current `silence_ms` and
`wait_recheck=true`; it never consumes text or directly grants the floor.
At most two silence rechecks are issued per input revision, using the existing
`explicit_wait_ms` delay measured from the preceding result. Continued waiting
or two provider errors parks the retained input until new ASR; no clock loop can
keep retrying it. Duplicate ASR does not renew that budget. New input cancels the
old timer and invalidates its in-flight results. Pause/resume preserves the
remaining delay. Main response or control-stop consumption clears this state.

While an explicit hold is known, a live non-final answer/clarify or a fresh
continuation retains that hold instead of permitting an interruption. A final
answer/clarify result, or a silence recheck returning answer/clarify/continuation,
can release it. Final alone never grants the floor, and a stable non-final input
can still be released by a bounded recheck. This conservative guard applies only
after explicit floor retention, leaving ordinary non-final questions unchanged.
Normal confidence thresholds and maximum-wait fallback then apply: a permitted
answer answers; a low-confidence answer or continuation can clarify at the
existing maximum wait. A recheck classified `ignore` preserves the held content
instead of erasing it. A new response appends the complete retained user span
once; later turns receive it in history. Waiting spans remain subject to the
existing input-size bounds. Persistent waiting is semantic, not a keyword regex:
`explicit_wait` continues to wait even if max-wait has passed. Provider failures
while an explicit hold is known fail closed regardless of bounded-wait policy.

The tuned Jev start question distinguishes a temporary request to finish from a
persistent condition such as “until I say go”, and recognizes a completed debate
argument as a possible response opportunity. Only this question/criteria change;
thresholds, durations, ScaleDown profile and voice prompt remain unchanged.
Frozen development contrasts: 14 states × 2 repeats × 2 providers × 2 arms = 112
HTTP-successful requests. Jev exact labels improve 24/28 to 28/28, with all 10
explicit-wait samples retained. The equivalent ScaleDown candidate improves
24/28 to 26/28 but violates 2/10 explicit-wait samples, so it is rejected and its
original profile remains. This is small development evidence, not a holdout or
acoustic quality claim. Captured requests, responses and models are retained with
the task's evaluation artifacts. Local cold-connection timings exceed production
timeouts in some cases and must not be read as serving latency acceptance.

`test_wait_retention.py` embeds the recorded debate request/result and six actual
silence-only model results. With the same input retained, high-confidence Jev
answer responds; low-confidence Jev answer and ScaleDown continuation reach the
existing bounded clarify path. Model failure is tested separately from these
successful-result timelines; it can remain silently parked after both retries.

A second frozen check uses six actual non-final prefixes from the same debate.
The Jev prompt candidate alone incorrectly selects answer on revision319 in
2/12 prefix samples; adding more grammatical prose did not repair it. We retain
the smaller question update for its complete-final improvement and require the
explicit-hold streaming guard above. Regression applies answer=.77 to all six
actual prefixes and verifies no response before the complete final. This is a
combined scheduler/question repair, not a claim that the classifier has learned
all boundaries. The larger v2 wording and the ScaleDown candidates are rejected.
