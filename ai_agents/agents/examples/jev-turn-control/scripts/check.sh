#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
TMAN="${TMAN:-tman}"
EXT=../../ten_packages/extension/jev_turn_control_python
export PYTHONPATH="$PWD:$PWD/tenapp/ten_packages/system/ten_runtime_python/lib:$PWD/tenapp/ten_packages/system/ten_runtime_python/interface:$PWD/tenapp/ten_packages/system/ten_ai_base/interface"
black --check --line-length 80 "$EXT" tenapp/main.py tests
.venv/bin/python -m pylint --rcfile=../../../../tools/pylint/.pylintrc "$EXT" tests/*.py
for path in tenapp "$EXT"; do
    "$TMAN" check manifest-json --path "$path/manifest.json"
    "$TMAN" check property-json --path "$path/property.json"
done
python3 -m compileall -q "$EXT" tenapp/main.py tests
