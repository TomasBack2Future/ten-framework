# Response opportunity evaluation protocol — frozen before new provider results

Base: 78d44c91d2a7151da18a9d5e82b69b86dbbc1536. No engine/Web changes in this work.
The engine-fix SHA will be recorded separately and replayed against the same
traces/results. Previously inspected calls, 24 audio runs and all prior pilot /
holdout families are SEEN REGRESSION ONLY. Missing historical request bodies or
speech must remain unknown; reconstructed control-state fixtures are labelled.

New data: authored synthetic conversational families plus previously unused
public Full-Duplex-Bench synthetic source conversations. Every source conversation,
all its prefixes, silence checkpoints and derived variants share one family and
one split. Conservative similarity-connected components group related source
contexts; any component touching previously seen data is regression-only.
Development / validation / holdout are assigned before provider calls, stratified
where group constraints permit. New holdout labels and prompts cannot be edited
in response to results. This is single-author annotation, not independently blind
labelling. Source reference text is not presented as actual ASR or audio listening.

Nine strata: complete question, contextual short/elliptical answer, finished
number sequence, hesitant continuation, explicit wait, supportive acknowledgment,
correction, request for a response, new question after interruption. User
acknowledgment and proactive assistant backchannel are distinct. All timeline
sources, exact timestamps, synthetic timings and assumptions are recorded.

A: shipped prompt + .47 start threshold. B: candidate prompt/criteria only + .47.
C: shipped prompt + selected threshold, swept on EXACT SAME frozen outputs.
D: candidate prompt + selected threshold. Schema and five start labels unchanged;
stop prompt and .65 stop threshold unchanged. No probability products. Threshold
selection uses development, validation confirmation, then a signed lock before
new holdout. Full request/response, requested/resolved version, latency, errors,
request/prompt hashes are retained without authentication material. Every input
and prompt is paired between Jev jev-1.13.0 and ScaleDown classify-1.

Predeclared threshold grid: .20,.25,.30,.35,.40,.42,.45,.47,.50,.55,.60,.65,.70,
.75,.80,.85,.90,.95. Prefer lower weighted errors (premature/wait violation/
acknowledgment false trigger weight 10; missed response weight 2), then fewer
negative-family errors, then closeness to .47. Validation may reject a dev
selection, not tune it using holdout. Report answer and clarify separately.

Sequence evaluation preserves ASR/reference event times, then continues clock
progression with NO further ASR. It records stale decisions, missing response,
early floor-taking, explicit-wait intrusion, acknowledgment false response,
correction recovery, and response-opportunity → response.start delay/censoring.
This is controller-start timing, not acoustic onset or listener experience.
Actual ASR traces include observed ASR latency; reference/synthetic projections
cannot establish real audio end-to-end latency. Existing real-audio traces are
reported separately as seen regressions. No fabricated auditory review.

Timing/silence-recheck candidates (300,500,1000,2000 ms) are separate experiments,
not recommendations and not credited as prompt improvements. State-changing
closed-loop traces are distinguished from the fixed-score threshold ablation;
a score may be reused only for the identical request body/hash. Key provider
label/gate disagreements are repeated three times with request IDs and times.

Report per-stratum denominators, sample/family counts, failure counts, confusion,
response recall, early-start/wait/acknowledgment rates, recovery, delay quantiles
and censored counts. Use Wilson 95% intervals and family bootstrap paired deltas.
Do not replace the default unless the seen call failure is addressed on the fixed
engine, misses improve without obvious early-start regression, and uncertainty /
source coverage support the recommendation. Sparse evidence means no replacement.
