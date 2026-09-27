# ScaleDown reasoning-off / dedicated-era paired measurement

Frozen before primary results. Source baseline: 5ed692cf78bde417c553b8e798e13d647afcd29c.
Production change: direct ScaleDown classify requests explicitly send
`reasoning: false`. No change to Jev requests, compression requests, prompts,
thresholds, timeouts, default mode, engine or UI.

219 previously seen regression inputs / 126 family groups: 63 legacy six-decision
records (101 exact-choice labels), plus 156 final start/stop snapshots from 108
prior response-opportunity families (binary floor labels). Authored synthetic,
public-reference projection and legacy text/ASR sources are reported separately.
All labels remain frozen. No new blind holdout, human/audio annotation or
production accuracy claim; no threshold/prompt tuning based on these results.

Primary controlled comparison: same current Jev instructions/criteria and same
state for Jev, direct SD reasoning=false, SD compression→Jev, and direct SD
reasoning=true control. The SD text wrapper and compressed-state wrapper match
runtime wire contracts. SD→Jev has two serial stages; it never calls SD classify,
so no unsupported reasoning field is added to compression. Compare full-chain
wall latency and each stage, not just final Jev latency.

Warm: three paid uncached repetitions per case/arm, persistent HTTPS connections
per arm/stage per worker. Cold: two repetitions on a fixed hash-stratified
20-case subset covering all six decision kinds, fresh connection per stage.
Two workers, serial arms within each paired input with rotating order. Case order
is frozen and shuffled by replicate. Pilot is separate and excluded. Record
connection reuse; the first warm request may include connection establishment.

A secondary lane uses each shipped mode's own prompt/criteria/thresholds on the
same 156 binary floor states, once per mode. This describes current mode behavior
but does not isolate model quality because prompts and thresholds differ.

Retain every actual body, raw response, returned model, timestamp, stage/chain
latency, errors and reasoning-field paths/length. No credentials in artifacts.
Reasoning=true text is preserved for traceability, and its output/gate variability
is compared to false; it is not used to rewrite labels. Provider-reported
'dedicated enabled' is not independently verified and cannot be causally isolated
from service/time changes with this before/after study.

Report P50/P90/P95/P99, errors, >800ms total deadline fraction, exact-choice
accuracy on 101 labelled decisions separately from binary floor accuracy on
156 labelled states, and per-kind/source denominators. Raw semantic scores and
deadline-aware/gated floor decisions are separate. Current Jev's sum-of-answer
and-clarify rule is used only after an answer/clarify chosen label; never replace
chosen label by probability argmax. Secondary mode gates use their own policies.
Repeated trials are not independent samples: report per-case variability and
paired family-cluster bootstrap confidence intervals (2,000 resamples, fixed
seed). Do not recommend a mode change from latency alone.
