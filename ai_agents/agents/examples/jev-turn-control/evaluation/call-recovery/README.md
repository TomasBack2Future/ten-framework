# Call recovery acceptance (2026-09-27)

Backend-only patch on e102df4. Frontend and deployment files are unchanged.

## Deterministic repairs

- An accepted stop decision ends its unresolved timeout budget. Fresh input gets
  a new budget; continuously unresolved partials still cannot postpone stopping.
- Apply a parsed provider result inside the bounded request task, before the
  `wait_for` completion wakeup, so a queued clock cannot beat an available result.
- A consumed segment's case/terminal-punctuation-only final revision is not a
  new user interruption. Added words and different segment IDs remain new input.
- Reconstruct streamed LLM text from monotonically extending cumulative content.
  Recover missing deltas, ignore delayed shorter prefixes, and include the final
  suffix. Reject incompatible rewrites rather than speaking corrupted text.
- Emit immutable decision.applied evidence for consumers that persist events
  before the in-memory decision.completed record is updated.

The recorded incident has eight nonempty LLM streams. Direct replay of the
production delta concatenation matches final content in 4/8; the repaired suffix
reducer matches 8/8, including the visa answer's missing 130 characters. This is
recorded-stream replay, not new audio or human listening acceptance. Native
adapter tests additionally verify exactly-once TTS submission and cancellation.

## Prompt selection is separate from bugs

Only Jev's tuned start instructions/criteria change. Threshold .47,
stop rules, timer durations, and SD runtime profile remain unchanged.
The final Jev gate uses answer+clarify probability only when the chosen label is
answer or clarify. It never overrides continuation, explicit_wait, or ignore. The bounded
prompt limit increases from 2000 to 4096 to accommodate the evaluated 2222-char
prompt verbatim. No browser protocol or default capability switches change.

Candidate D prioritizes the latest complete question after abandoned fragments,
uses ASR final as text-stability evidence rather than unconditional permission,
distinguishes incomplete syntax from clarification, and resolves short answers
against the last assistant question before treating them as acknowledgment.

Development: 32 authored contrasts and four recorded incident states (three
requests to respond/resume and an acknowledgment). Three prompt revisions were
compared with both providers; this development set was used for selection and
is NOT a held-out result. D passes all 36 on both providers in its selection run.
Lowering the old threshold from .47 to .40 still misses two of the three incident
requests and starts a reply on the recorded Okay; it was not selected.

After D was frozen, the attached manifest froze 24 new authored cases, 12 reply
and 12 hold/acknowledgment, with A (old) and B (selected D) questions. Each state
was sent identically to Jev and ScaleDown three times: 288 successful HTTP calls.
No prompt/gold/threshold was changed after these acceptance results.

| Provider / prompt | Missed replies / 36 | False starts / 36 |
|---|---:|---:|
| Jev old | 0 | 0 |
| Jev selected D | 0 | 0 |
| ScaleDown old | 0 | 3 |
| ScaleDown selected D | 0 | 0 |

Repeated calls are not independent families. These are only 24 authored cases,
not DuplexBench audio or a broad generalization claim. Both providers use the
same chosen-label >= .47 gate here for controlled comparison, not SD's distinct
production gate. HTTP durations include the local client's network path and are
not khipaa latency or speech latency. No provider credentials are included.

See manifest.json and results.jsonl for all acceptance inputs and raw outputs.
The incident evidence and intermediate candidate results remain in the local
investigation directory rather than publishing the user's session contents.

## Stability follow-up and final gate acceptance

Additional identical-prompt repetition found one borderline incident answer at
.43 (answer) + .12 (clarify). In that follow-up A and B were byte-identical D
questions because the source default had already been updated: these are six
repetitions per state/provider, NOT an old/new A/B comparison. Jev top .47 missed
one of the six repetitions for that case. The reply-mass gate recovers it.

The final selected policy is D + chosen-label-in-{answer,clarify} +
(answer+clarify >= .47). Raw threshold lowering was not selected. The original
24-case acceptance above became an additional gate-development check; do not
claim it is untouched holdout for the gate selection.

With prompt and gate fixed, final-acceptance/ froze 28 NEW authored cases, 14
positive and 14 negative. Three repeats per case, both questions and providers:
336 HTTP 200 results. A uses old prompt/top .47, B uses D/reply-mass .47.

| Provider / policy | Missed replies / 42 | False starts / 42 |
|---|---:|---:|
| Jev old | 3 | 3 |
| Jev selected | 0 | 0 |
| ScaleDown old (controlled .47) | 0 | 12 |
| ScaleDown selected (controlled .47) | 0 | 0 |

These are repeated observations of 28 cases, not 84 independent cases per
provider/policy. The final set was not used to alter the selected policy.
SD remains a same-input controlled comparison, not a change to its runtime
profile. This is limited offline semantic acceptance; live acoustic testing
must use the merged release and is not asserted here.
