# Jev turn control — TEN voice demo

A public TEN 0.11.73 graph with separate start/stop/backchannel judgments,
revision fences, bounded scheduling, and played-context tracking. Jev is the
main decision provider. Soniox supplies streaming ASR, Groq supplies the main
answer through the public OpenAI-compatible extension, and Cartesia supplies
PCM16 audio and word timestamps. ScaleDown remains an offline comparison.

The event stream exposes inputs, classification probabilities, timers and
applied actions, never model reasoning. Backchannel defaults off. ASR final
commits a segment; it does not grant answer permission. Stop is the user taking
back the floor, not assistant proactive interruption.

## Run

Inside the isolated Ubuntu build container, from this example directory:

```bash
export TMAN=/workspace/.bootstrap/tools/ten_manager/bin/tman
task install
task build
task check
task smoke
.venv/bin/python scripts/run_graph.py --mode mock
# After supplying server-only JEV_API_KEY, SONIOX_API_KEY,
# GROQ_API_KEY and CARTESIA_API_KEY:
.venv/bin/python scripts/run_graph.py --mode live
```

The Web owner supplies the protected HTTPS gateway and browser UI. The native
WebSocket binds only `127.0.0.1:8765`; one graph process owns one session.
`mock` uses deterministic labels and an audible synthetic test tone, not speech.
`live` loads the actual overseas provider graph. A missing key fails startup.
No secret is embedded in the graph file or browser configuration.

`JEV_SESSION_CONFIG` accepts flat, allowlisted session-start settings, e.g.
`{"backchannel.enabled":true,"start.prompt":"Classify response timing..."}`.
`JEV_SESSION_ID` comes from the server. All overrides are fixed for that session.
The runner writes a private temporary graph and initializes it during the TEN
app configuration lifecycle; the checked-in offline graph stays unchanged.

See [config](docs/config.md), [event schema](docs/events-v1.schema.json),
[synthetic replay](fixtures/replay-synthetic.jsonl), and
[verification](docs/VERIFICATION.md). The original offline bootstrap provenance
and exact public baseline are preserved in [BOOTSTRAP.md](BOOTSTRAP.md).

## Reproduce observations and validate a live graph

```bash
python3 scripts/replay.py fixtures/replay-synthetic.jsonl
# Set JEV_API_KEY and SCALEDOWN_API_KEY server-side for three paired calls:
.venv/bin/python scripts/compare_providers.py --output /tmp/comparison.json
.venv/bin/python scripts/validate_live.py /tmp/synthetic-input.pcm \
  --url ws://127.0.0.1:8765 --output /tmp/jev-live-evidence.json
```

Replay is network-free and deterministic. Its input can be split by source
script family for later train/dev/locked-test work; no benchmark prompt tuning
is included in this MVP. Live validation accepts synthetic mono PCM16 at 16kHz,
checks real Jev results and generated audio, then simulates a playback cursor
and stop acknowledgment. It does not certify human listening or microphone UX.

## Playback limitations

Cancellation actively aborts LLM/TTS and tells the browser to clear scheduled
sources. Old response IDs are discarded. Playback acknowledgments keep only
fully played words when timestamps are available; fallback character-rate
truncation is visibly estimated. Late timestamps can refine retained context.
Browser cursor + provider alignment is still not an exact measurement of what
a person heard. A 500ms missing-stop-ack timeout is explicitly unconfirmed.

## Public references

- [TypeSafe evaluation API](https://docs.typesafe.ai/api)
- [Soniox streaming transcription](https://soniox.com/docs/stt/rt/real-time-transcription)
- [Groq supported models](https://console.groq.com/docs/models)
- [Cartesia streaming TTS](https://docs.cartesia.ai/api-reference/tts/websocket)
- [ScaleDown compression](https://docs.scaledown.ai/quickstart)

All added business logic was written against public TEN APIs; no commercial
interceptor or conversational-agent implementation was copied. Repository and
copied-template licenses remain applicable.

## Decision modes

Session settings support Jev (default), SD direct classification and SD → Jev.
The tuned candidate includes instructions, criteria and per-provider thresholds;
the original baseline remains selectable. See [DECISION_MODES.md](DECISION_MODES.md)
for configuration, measured latency, executor boundaries and evaluation limits.
