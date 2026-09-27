# Verified bootstrap record — 2026-09-27

## Source and isolation

- Host: `ten_env`, Ubuntu 22.04.5 LTS, x86_64.
- Checkout: `/root/CodeBase/ten-jev-hackathon`.
- Branch: `chore/jev-oss-bootstrap` (local only).
- Public main SHA: `ca00160c79d277a6179b5bd7af3c585db4c8f3db`.
- Main was fetched again after setup and remained at this SHA.
- Shallow, sparse, independent clone; no other project checkout was reused.
- Dedicated container: `ten-jev-bootstrap`, no published ports.
- Official image: `ghcr.io/ten-framework/ten_agent_build:0.7.14`.
- Image ID: `sha256:e49f6779aa1e5ba31d5e2448c8f64a87510937ab5d09bc2e10e8903d43ab3c7a`.

## Versions

| Component | Version |
| --- | --- |
| Host Git | 2.34.1 |
| Host Docker | 29.3.0 |
| Host Python / uv | 3.10.12 / 0.8.18 |
| Host Node / npm | 22.18.0 / 10.9.3 |
| Container Python / uv | 3.10.12 / 0.9.21 |
| Container Task | 3.46.4 |
| Container Black / Pylint | 25.12.0 / 3.3.9 |
| Container Node / GCC | 22.21.1 / 11.4.0 |
| Project tman / TEN runtime / Python binding | 0.11.73 |
| pytest / namedthreads / uvloop | 9.0.2 / 1.0 / 0.22.1 |

Python dependencies are pinned in `requirements-dev.txt`. The image's older
system tman (0.11.48) is not overwritten; commands explicitly select the
project's downloaded 0.11.73 manager.

## Artifact integrity and download recovery

- tman release ZIP SHA256:
  `1ac22f455cc0be5f2541701bd38cacecc918f41a1b1b891889c71914cc3b3ab2`.
- Public Linux x64 ten_runtime package SHA256:
  `414dc2e971296117d13881b71e57ad7f087f72fa54ead8976cf6e6e630136f8f`.
- Runtime package size: 16,798,337 bytes.
- Default registry metadata was reachable. Its S3 runtime-body download
  exceeded tman's timeout on this connection. A bounded retry confirmed it.
- The same public artifact was downloaded with resume/ranges, verified against
  its S3 ETag and SHA256, and placed into this container's tman cache.
- `scripts/prefetch-runtime.sh` reproduces the download/check/cache step.
- The official CN registry probe timed out; it was not retained in config.

## Verification

All checks passed on this checkout:

- Shell syntax checks and `git diff --check`.
- `task format`, `task build` (Python compileall; no C/C++ source rebuild).
- `task check`: Black, Pylint 10.00/10, four tman JSON schema checks.
- `task smoke`: 2 passed — configured graph command/result roundtrip and
  actual app readiness/SIGTERM/clean exit.
- `task official-smoke`: 1 passed — unchanged official default Python
  extension hello-world test with the official app dependency layout.
- Fresh disposable container with `--network none`: 2 smoke tests passed.
- Bootstrap-container and prefetch scripts were rerun successfully.

Success markers: `JEV_GRAPH_ROUNDTRIP_PASS`, `JEV_APP_LIFECYCLE_PASS`.
Full local logs are under `.bootstrap/logs/`, especially
`final-validation.log` and `offline-smoke.log`.

## Scope and process state

Environment setup, Python build checks, real runtime startup, addon loading,
and an offline graph message roundtrip are complete. Voice turn business
logic and provider integration are not implemented. No PR, push, package
publication, public deployment, or real customer-data access was performed.

The smoke apps terminate themselves through the test harness. The dedicated
container can be stopped after checks and restarted with the bootstrap script.
No listener or provider connection is configured by this graph. Existing host
services and the commercial checkout were not modified.

See `README.md` for commands, source attribution, planned integration boundaries,
and the remaining turn-control work.
