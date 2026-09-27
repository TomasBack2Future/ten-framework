#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/../tenapp"
export PYTHONPATH="$PWD/ten_packages/system/ten_runtime_python/lib:$PWD/ten_packages/system/ten_runtime_python/interface:$PWD/ten_packages/system/ten_ai_base/interface"
timeout --signal=TERM --kill-after=5s 45s ../.venv/bin/python -m pytest -q -s ../tests
