# Jev turn-control Python extension

Bootstrap-only `AsyncExtension` using public TEN Runtime 0.11.73.
It registers `jev_turn_control_python` and handles the `jev_ping` diagnostic
command declared in `manifest.json`. No provider, audio, or turn-control
business behavior is implemented yet.

See `../../../examples/jev-turn-control/README.md` for the graph, isolated
container setup, tests, reproducible commands and future interface boundary.
