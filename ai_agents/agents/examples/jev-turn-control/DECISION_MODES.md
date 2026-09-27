# Decision providers and frozen candidate profiles

Session settings now select `provider.name`: `jev` (default), `sd`, or
`sd_jev` (shown as SD → Jev). This is independent of the start, stop,
backchannel and background-memory feature switches. Backchannel and memory
compression remain disabled by default. Mock transport remains synthetic
regardless of the selected provider; the standalone smoke graph explicitly
uses `mock`.

- `jev`: original structured state → Jev `jev-1.13.0`.
- `sd`: the same structured state serialized into `state.text` → ScaleDown
  `/v1/scaledown`, model `classify-1`, with the same choice-question contract.
- `sd_jev`: state → ScaleDown `/compress/raw/` → Jev with
  `state.compressed_state_text`. Compression preserves the decision definitions,
  speaker attribution, user prefix and negation. Its backend revision is not
  pinned. This adds one serial request; it does not replace Groq summarization.

Select the provider/profile before connecting. The authenticated gateway accepts
only these names, never credentials or endpoint overrides. Server environments
need `JEV_API_KEY` for Jev, `SCALEDOWN_API_KEY` for SD, both for SD → Jev. Missing
keys fail session startup. ASR, LLM and TTS credentials are still required for
live voice. The graph can also be generated with:

```sh
JEV_SESSION_CONFIG='{"provider.name":"sd_jev","provider.profile":"tuned"}' \
  python3 scripts/run_graph.py --mode live --write-only /tmp/jev-graph.json
```

`provider.profile=tuned` is the default candidate. `baseline` preserves the
original voice prompts, criteria, thresholds, `jev-latest` selection and legacy
combined-readiness rule for reproducing b09 behavior. The default Jev candidate
uses top-label scoring, not combined readiness. SD candidates combine
P(answer)+P(clarify) only when the chosen label is answer or clarify; they retain
that chosen subcategory and never promote continuation based on combined mass.
Low-confidence results do not schedule a reply. Existing maximum-wait and stop
fallback behavior remains in the reducer, including its `hold` failure policy.

| Decision | Jev | SD | SD → Jev |
| --- | ---: | ---: | ---: |
| Start | .47 (top) | .95 (answer + clarify) | .54 (answer + clarify) |
| Stop | .65 | .49 | .65 |
| Backchannel | .71 | .62 | .74 |
| Memory compression decision | .70 | .70 | .70 |
| Route: execute | .75 | .75 | .55 |
| Route: task control | .75 | .75 | .75 |
| Support | .61 | .40 | .63 |

The extension's `decision_profiles.json` contains the exact selected
instructions **and** criteria for all six decisions. `baseline_questions.json`
retains the previous definitions. Server-owned `Config.load` accepts per-decision
`prompt`, `criteria` and `threshold` overrides; criteria must preserve all label
names. Empty prompt overrides from the UI select the profile default. The
browser cannot override thresholds or criteria. No runtime prompt retrieval or
provider-side prompt templates are needed.

`DecisionProvider.decide` returns the same `{label, score, probabilities}`
contract for each question in all modes. One total timeout (800 ms by default)
covers the entire chain; no retries or silent provider fallback occur. HTTPS
connections are reused and redirects disabled. Invalid labels, distributions,
empty compression, HTTP failures and timeouts reject the decision. The voice
adapter handles these through its existing bounded-wait/hold behavior.

`DecisionProvider.route` applies separate intent and support thresholds, returns
`wait` below the relevant threshold, and strips non-visible metadata.
`executor.routing.RuntimeRouter(session_decision_provider)` adapts it to the
executor sample interface. The existing offline `Router`, locked benchmark
specs, and stored scores are unchanged. The web demo still has execution
disabled: this PR does **not** connect task execution to voice, execute a tool,
or relax capability, parameter, stability or task-owner checks. Hosts integrating
the runtime router must retain those deterministic checks.

## Evidence and limits

These profiles were selected on train/dev and frozen before a 63-snapshot test
across only 18 families. They remain provisional: the Jev support gate still had
a false-supported result, start admitted only 4/7 positive test snapshots, and
summary fidelity did not pass. The test was not independently blind. This PR
integrates that frozen candidate; it does not claim production acceptance or
retune against the test set.

A previous isolated khipaa probe compared identical inputs and identical Jev
questions, with 24 cases per mode/connection strategy. Warm HTTPS P50/P95:
Jev 113/153 ms, SD 299/411 ms, SD → Jev 211/407 ms. New HTTPS connections:
126/168 ms, 538/600 ms, 393/543 ms. These measure provider calls only, not audio
turn latency, and are not a load test. They replace the earlier local-network
latency estimate, not the correctness results.

Selection lock SHA-256:
`cef4870c763959c355eb086ead62872ce9b864780e17aeca457f31b7e1145474`.
Prompt sources and attribution: [PROMPT_PROVENANCE.md](PROMPT_PROVENANCE.md).

## Integration validation (2026-09-27)

- Python 3.10, TEN runtime 0.11.73: full example suite, including real graph
  lifecycle and WebSocket roundtrip, **80 passed**.
- Gateway/browser tests: **17 passed**; JavaScript syntax checks passed.
- Executor core/lifecycle/frozen-evaluation tests: **23 passed**, plus **2** new
  runtime-router contract tests. The optional SDK suite was not validated in
  this checkout (SDK dependency unavailable); SDK execution code is unchanged.
- Example `task check`: Black, Pylint (10/10), four manifest/property schema
  checks and bytecode compilation passed. Executor routing lint also passed.
- New provider code ran in a dedicated khipaa Pod, six identical visible inputs
  × three modes, with common selected Jev instructions and criteria: **18/18**
  decisions succeeded within the existing 800 ms total timeout (24 HTTP calls).
  Connections were reused within each mode; this is a small contract smoke,
  not a new latency percentile estimate or accuracy score. The temporary Pod
  was deleted and its absence checked. No serving deployment was modified.
  [Sanitized results and source hashes](validation/provider-smoke-20260927.json).
