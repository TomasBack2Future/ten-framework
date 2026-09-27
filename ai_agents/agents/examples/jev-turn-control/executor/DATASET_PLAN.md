# Routing and execution pilot

80 routing decisions: 64 independently authored bilingual contrast cases and 16
BFCL-linked decisions, plus 12 independently authored sandbox artifact tasks.
This is prompt/threshold evaluation, not fine-tuning or production-call evidence.

- Public BFCL inputs are downloaded at a pinned commit using `gh`. The manifest
  keeps source IDs, turn indices, derivation rules, source checksums and label
  rationale. Original, derived and self-authored records have separate kinds.
  Repository Apache-2.0 does not by itself establish a separate dataset license;
  raw public inputs and derived wording are not redistributed in this PR.
- BFCL is an evaluation set: all selected source families remain locked-test.
  Base/missing-function/missing-parameter variants use the same family id.
  Only the current user turn and earlier user context are projected. No answer,
  execution path, initial private state, later clarification or task goal enters
  model input. Missing-function fixtures explicitly project the available tools.
- Self-authored contrast families share one split (seed 20260927; stable hash).
  Translations, semantic rewrites and any later audio variants inherit the family.
  Train is reserved; two predeclared prompts are compared on dev only, then one
  chosen threshold/prompt is frozen before a single locked-test evaluation.
- BFCL irrelevance is not Jev conversation gold. Explicit operational/query
  requests without tools are execute/unsupported; missing required user arguments
  are clarify/missing_parameters; mental math/explanation may be conversation.
  Labels are pilot author annotations, not claimed upstream four-class labels.
- Jev and ScaleDown always run on identical IDs with identical context. Errors
  remain in the denominator. Report confusion matrix, execute precision/recall,
  false execution and support classification, complete wall time and usage.
- Artifact success requires filesystem content assertions. A fake result proves
  lifecycle/validator behavior only. A three-arm fake orchestration ablation is
  separately labeled and cannot establish the benefit or speed of a real model.

## Deferred datasets

BFCL V3 describes multi-turn missing parameter/function boundaries and terminal
state checking; current repository filenames are V4, pinned explicitly.
https://gorilla.cs.berkeley.edu/blogs/13_bfcl_v3_multi_turn.html
https://gorilla.cs.berkeley.edu/leaderboard

ToolTalk is a small optional multi-turn complement (78 conversations, 28 tools,
7 plugins); not copied or used in this pilot.
https://github.com/microsoft/ToolTalk

ToolSandbox repository LICENSE is Apple software terms with separate component
notices in ACKNOWLEDGEMENTS. Dataset redistribution rights are not inferred;
not copied. Milestone/dependency validation is a useful later complement.
https://github.com/apple/ToolSandbox

The inspected sierra-research/tau2-bench main revision
`b7ea9074c1cba482b30687fecdb5c8425fd6f619` includes tau-Voice. Its
src/tau2/voice/README.md and audio_native adapters use discrete ticks (0.2 s),
provider-specific full-duplex interfaces, telephony audio, synthesis/transcription
services and externally configured ElevenLabs persona voices. A TEN cascade
requires a new DiscreteTimeAdapter bridging incoming audio, outgoing audio and
tool events, clocked without blocking ticks; convert sample rates and maintain
playback/interrupt timing. This is nontrivial integration, not a flag change.
No paid simulator or full suite is run in this pilot.
https://github.com/sierra-research/tau2-bench/blob/main/src/tau2/voice/README.md
https://arxiv.org/abs/2603.13686

Full-Duplex-Bench remains owned by the later integrated voice evaluation; routing
and artifact checks do not replace speech timing or acoustic acceptance tests.
