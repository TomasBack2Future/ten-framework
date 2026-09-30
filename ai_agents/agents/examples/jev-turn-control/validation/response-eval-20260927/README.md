# Frozen response-opportunity evaluation

This evaluation retains the shipped **Jev default**, prompts, thresholds and
waiting times. Candidate B is an evaluation artifact only. It does not justify
replacing the default: prompt-only did not improve held-out snapshot admission,
and the conservative threshold increased controller waiting. No engine, Web,
profile or deployment changes are included.

See [REPORT.md](REPORT.md) for results and limitations, [PROTOCOL.md](PROTOCOL.md)
for the predeclared design, and [manifests/replay-assumptions.json](manifests/replay-assumptions.json)
for timing assumptions. New data is authored synthetic/reference-text projection,
not new ASR, acoustic listening or end-to-end voice evidence. Both providers use
Jev's chosen-label policy in the controlled comparison; this does not evaluate
the shipped SD sum-of-answer-and-clarify policy.

## Offline reproduction

Python 3.10+; only tests require `pytest`. Measurements use the standard library.
Run from this directory, with `$REPO` set to the repository root:

```sh
# These exact public Git objects must exist; prepare never silently fetches.
git -C "$REPO" fetch origin 78d44c91d2a7151da18a9d5e82b69b86dbbc1536
git -C "$REPO" fetch origin bf4c21e1f70940b28e4e794e7b1db08624afaedb
python src/prepare.py --repo "$REPO"
python -m pytest -q src/test_evaluation.py
python src/analyze.py report
python src/sequence_metrics.py
python src/measurement_summary.py
python src/seen_regression.py
python src/offline_verify.py
```

`prepare` checks hashes, restores the two immutable engines, expands compressed
raw evidence and regenerates the frozen checkpoints. `offline_verify` replays all
2,592 sequences and requires every resulting event/request/outcome to match;
missing exact HTTP bodies fail instead of extrapolating or making a network call.
The raw `.jsonl.gz` files contain all sanitized request/response data and engine
events. Metrics `.json.gz` files include all source/scenario/arm/split groups and
family bootstrap intervals; reports distinguish censored timing denominators.

The dataset is already frozen. `build_data.py --work SOURCE_ARCHIVE_DIRECTORY`
can reconstruct it in a fresh output directory from `pause.zip`, `interrupt.zip`
and `backchannel.zip` at the recorded Full-Duplex-Bench revision; seen source IDs
and exclusion rules are included. It refuses to overwrite the frozen dataset.
Public synthetic-source attribution and MIT terms are in the example's
[Prompt provenance](../../PROMPT_PROVENANCE.md). No Candor or ICC data is used.

## Live collection (explicit operator action)

The checked-in results need no credentials or Kubernetes. To collect a separate
new run, use a fresh artifact directory/Pod name; do not overwrite these files or
reuse this holdout to tune another candidate. Freeze a new protocol and data first.

The operator must have access to the intended khipaa cluster. `collect.py` reads
`KUBECONFIG` (default `~/k8s/hipaa.kubeconfig`), explicitly scopes every command to
`ten-jev-demo`, and sends Jev/ScaleDown credentials from `/tmp/b.pub` and
`/tmp/c.pub` through exec stdin to process memory only. No credentials enter Pod
specs, environment variables, arguments, request logs or repository artifacts.
`manifests/pod.json` describes a non-serving, non-root, resource-limited Pod with
no service account token and a bounded lifetime. Creation/deletion is an explicit
operator step. The original measurement Pod was deleted; see `cleanup.txt`.

Collection order: `collect.py development-validation`, `analyze.py select`,
`collect.py holdout`, `run_replay.py`, then `repeat.py`. Selection lock must exist
before holdout collection. Prompt A/B and source labels stay frozen. Repeated
critical outputs are sensitivity checks, not additional independent families.

Request caching keys the complete provider/body and repetition number. The
network collector retains failures, uses no retries and imposes a separate 800ms
runtime-policy deadline on measured completion. Network requests allow 12s so
late responses/errors remain observable; expired results are never applied to
replay. Every newly queried state is paired across Jev and ScaleDown. Same-score
threshold ablation applies only to fixed snapshots; closed-loop replays request
new exact bodies whenever state diverges.
