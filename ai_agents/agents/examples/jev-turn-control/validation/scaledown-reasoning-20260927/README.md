# ScaleDown reasoning-off: paired khipaa evidence

See [REPORT.md](REPORT.md) for measured latency, exact-choice accuracy, floor
accuracy, uncertainty and limitations. [PROTOCOL.md](PROTOCOL.md) was frozen
before primary results. Default Jev, prompts and thresholds remain unchanged.

Direct SD classification now explicitly sends `reasoning: false`. The compression
endpoint and Jev requests do not receive this field. The extra true control did
not return reasoning text either, and did not show a clear latency effect. This
records what the current endpoint did without assuming that its flag is active
or that provider-reported dedicated routing is causally verified.

## Reproduce offline

Python 3.10+; tests additionally need pytest. No API keys, Kubernetes or provider
calls are needed. From this directory:

```sh
python src/audit.py
python src/analyze.py
python -m pytest -q src/test_analysis.py
```

The readers accept compressed evidence directly. `audit.py` verifies all 3,256
paired results / 4,109 captured HTTP stages, exact body hashes, reasoning flags,
compression→Jev state continuity, and full-chain timing. `analyze.py` checks the
frozen inputs/config and reproduces family-cluster bootstrap metrics. Repetitions
are not independent families. The old six-decision labels and binary floor labels
have different meanings and denominators; no combined accuracy hides this.

All input families are previously seen regressions. Source cohorts are retained;
reference projections are not actual new ASR, and no new acoustic/voice evaluation
was performed. Dataset attribution is in the example's
[Prompt provenance](../../PROMPT_PROVENANCE.md), including MIT public synthetic
Full-Duplex-Bench and Apache-2.0 BFCL source material.

## New live run

Use a new artifact directory and an explicitly created non-serving Pod. Do not
overwrite this frozen run or silently replace recorded responses. `run.py` reads
`KUBECONFIG` (default `~/k8s/hipaa.kubeconfig`) and scopes every command to
`ten-jev-demo`; Pod parameters are in `manifests/pod.json`. Its fixed Pod name must
be changed for a new run. Supply Jev and SD keys in `/tmp/b.pub` and `/tmp/c.pub`;
they travel only in exec stdin into process memory. No credentials are committed,
put into Pod specs, environment variables or command arguments.

Expand `data/jobs.json.gz` before live collection. The pilot (`run.py --pilot`)
is excluded from main metrics. `run.py` preserves captured results when the
Kubernetes exec stream fails. `run.py --resume` sends only missing job/arm pairs;
it never retries successful captured outputs and marks recovered results.
Unknown requests that executed after a lost stream cannot be counted as if they
had evidence. The original stream and 13 resumed secondary-profile results are
preserved separately here; the controlled main comparisons were complete before
the interruption. Inspect `manifests/resume.json` for this limitation.

The original Pod was deleted and its absence verified. No serving deployment,
new call session, thresholds or provider backend configuration was changed.
