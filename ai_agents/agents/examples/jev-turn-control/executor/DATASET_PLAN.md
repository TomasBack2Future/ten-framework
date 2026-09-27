# Routing and execution pilot — reviewed revision

80 routing examples: 64 independently authored bilingual cases and 16 pinned
BFCL original/derived cases. 12 independently authored artifact tasks exercise
terminal filesystem assertions. This is prompt/threshold work, not fine-tuning,
natural production calls, or real Codex execution evidence.

## Exposure and family audit

The original split had a defect: translated/semantic variants used different
family names, including speech_vs_task/stop_reading and
conditional/hypothetical_en. Its "locked-test" was not independent of dev.
All original observations and metadata are preserved under historical-v1/;
**the original holdout claim is withdrawn**. Repartitioning already inspected
examples does not create a fresh unseen holdout.

`FAMILY_ALIASES` and data/family-audit.json explicitly consolidate 32 original
script labels into 17 authored semantic families. This includes translations,
negated/partial creation variants, quotation variants, progress questions,
ambiguous references, and speech/task-cancellation contrasts. Stable IDs and
`source_family` preserve original provenance. Seed 20260927 is unchanged;
related variants inherit the canonical family's split. Any future audio or
paraphrase variant must inherit the canonical family too.

Current bookkeeping groups: 28 train, 22 dev, 30 regression-test (14 authored,
16 BFCL). All 80 have `evaluation_boundary=exposed-regression`; none is an
unseen holdout. The repaired pilot runs all 80 as a paired regression check,
with the earlier refined prompt and 0.75 threshold frozen before rerunning.
No new prompt/threshold selection is performed from these scores. A future
unseen evaluation requires independently collected families never used in
this pilot, a new source manifest and a new pre-run selection lock.

## Public sources and labels

BFCL inputs are downloaded using `gh` at Gorilla commit
`6ea57973c7a6097fd7c5915698c54c17c5b1b6c8`. Manifest fields include source ID,
turn, original/derived kind, family, derivation rationale and file SHA256.
All BFCL families retain the upstream evaluation role; local use is now
explicitly regression-test. No public raw text or translations are vendored:
repository Apache-2.0 does not establish separate dataset redistribution terms.

BFCL tool-call gold is not Jev four-class gold. Operational/tool requests without
capabilities are execute/unsupported; missing required user arguments are
clarify/missing_parameters; mental arithmetic and explanation can be conversation.
These are pilot author annotations, not independent human-reviewed gold.

Only the current user turn, previous user messages, active tasks and available
capabilities reach the classifier. No future turns, private initial state,
answer/call paths, labels or source IDs are projected. The reviewed BFCL
multi_turn_miss_param_1 turn 3 is missing its line count: earlier turns 0–2
identify log.txt but supply no count; the later clarification is excluded.

Jev and ScaleDown always use identical IDs/context. Non-dev evaluation requires
a selection lock binding dataset SHA256, prompt SHA256, variant, threshold and
exposure boundary. Conflicting CLI overrides fail before key reads/API calls.
Errors stay in denominators; USD costs stay unknown unless billing is available.

## Dataset suitability and deferred scope

- [BFCL V3](https://gorilla.cs.berkeley.edu/blogs/13_bfcl_v3_multi_turn.html)
  describes missing-parameter/function and state-check boundaries. Current files
  use V4 names; the [leaderboard](https://gorilla.cs.berkeley.edu/leaderboard)
  score is not directly comparable to this derived four-way routing pilot.
- [ToolTalk](https://github.com/microsoft/ToolTalk): 78 conversations, 28 tools,
  7 plugins; optional multi-turn complement, not copied in this pilot.
- [ToolSandbox](https://github.com/apple/ToolSandbox): state/milestone and
  dependency tests are relevant. Apple software license and component notices
  do not establish separate dataset rights; not copied.
- [tau-Voice](https://github.com/sierra-research/tau2-bench/blob/main/src/tau2/voice/README.md),
  inspected main b7ea9074c1cba482b30687fecdb5c8425fd6f619: a TEN cascade needs a
  DiscreteTimeAdapter connecting inbound/outbound audio and tools to 0.2 s ticks,
  audio conversion, interrupt/playback timing and configured persona/TTS accounts.
  This is not a turnkey flag; no full or paid user simulator is run here.
  [Paper](https://arxiv.org/abs/2603.13686).
- Full-Duplex-Bench and integrated Soniox/Groq/Cartesia acoustic validation stay
  in the integrated voice phase. Executor tests do not replace those measures.
