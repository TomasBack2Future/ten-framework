# PR2 review disposition

Reviewed baseline: 1445d8a15e7833549391f03049fa47f62138a3b7. All seven findings
were accepted after checking their concrete paths. No finding is dismissed.
The executor remains disabled; no graph/Web/deployment change is included.
Five targeted lifecycle reproductions were run against the original adapter
fetched by exact GitHub SHA: one error and four assertion failures (all five
failed), then all five passed against the fix. Full local suite: 23 passed.

| Review finding | Disposition and implementation | Regression evidence |
|---|---|---|
| P1: cancellation consumes public input revision | Separate private generation fences from Request.input_revision. Cancel does not advance the public revision. | cancel revision 1, then adjust revision 2 completes |
| P1: SDK interruption failure corrupts cancellation / duplicate terminals | Preserve CancelledError when interrupt times out or raises. Adapter fences late errors as well as file plans. Publish cancellation once, before cleanup. Context-close failure cannot overwrite it either. Always drain the owned backend operation, including Python 3.10 wait_for cancellation cleanup. | SDK timeout, RPC rejection and context-exit failure all leave cancelled, emit exactly one task.cancelled and no files; generic backend cleanup failure and zero unhandled loop exceptions covered too |
| P1: translations/semantic families cross splits | Explicit canonical family aliases consolidate 32 source scripts into 17 authored families, with source_family retained. Audit all bilingual/semantic groups, not just the two examples. | table-driven translation/family tests; all 80 carry exposed-regression metadata |
| P2: wrong dispatch still counted as success | Separate terminal_state_success, dispatch_policy_success and unexpected_dispatch; combined success requires both. | an always-execute router fails non-action turns even when fake leaves no files |
| P2: overlapping adjustments regress revision | Per-task lock serializes the full revision check, cancellation cleanup, request update and new-run creation. | ordered races (3,4) and (4,3): final file/revision always 4; lower waiter is rejected; completion versions do not regress |
| P2: non-dev CLI defaults differ from selection | Non-dev evaluation requires a hash-bound selection lock; omitted threshold/variant load from it, conflicts fail before keys/API calls. Dataset and prompt hashes and exposure boundary are checked. | omitted threshold loads .75; .65 override, prompt/variant/data mismatch and absent lock rejected |
| P3: omitted old artifacts survive snapshot | Define file plans as complete desired snapshots. After validation and successful writes remove previously managed files absent from the new plan; SDK instruction explicitly requires retained files. | index.html -> notes.txt -> empty snapshot; actual directory and task manifest agree |

## Evaluation correction

The original 26-example test was called locked-test, but its translation-family
split defect invalidates independent holdout interpretation. Original files,
checksums and report are retained in results/historical-v1/ and data/historical-v1/.
They are evidence of what ran, not an unseen-test claim. No labels were changed
in response to model errors.

The revised bookkeeping partition is 28 train / 22 dev / 30 regression-test.
All 80 examples were already authored/inspected/evaluated. Fresh paired Jev and
ScaleDown calls over all 80 use the previous refined prompt and .75 threshold,
frozen with dataset/prompt SHA256 before calls. There was no further tuning.
The resulting report is exposed-sample regression, not new holdout evidence.

A corrected local ablation replays the original paired provider decisions and
rechecks actual fake artifact states. It makes no new paid provider call.
Original terminal-state success remains 36/36 in each arm, but all-accepted
violates the dispatch gate on 24/36 turns, so combined success is 12/36 there;
Jev/ScaleDown remain 36/36 in this narrow fixture. This is a comparison of the
explicit dispatch gate, not proof that a live model would perform a harmful
operation on an explanation request. Codex live execution remains blocked by
missing authorized deployment credentials.

## Additional reviewer uncertainties checked

The pinned multi_turn_miss_param_1 source was checked locally: turns 0–2 identify
log.txt but no tail line count; turn 3 says "last several lines". The later
clarification is excluded. The derived tool inventory requires an explicit line
count, so missing_parameters remains the documented pilot label. No source text
is added to the public repo. SDK public types remain installed at 0.157.1 and
contract tests use the real Sandbox/ApprovalMode values with injected transport.

## Integration / merge gate

Run `task test-core` for all core and evaluation regressions, not only the
original test_adapter.py. `task test` additionally needs requirements-sdk.txt.
The Web integration owner must replace/cherry-pick the reviewed executor change
before the user's combined merge/deploy gate. The final SHA requires Grok
re-review; this fix submission does not bypass that gate or claim deployment.
