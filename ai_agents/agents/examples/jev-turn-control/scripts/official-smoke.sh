#!/usr/bin/env bash
set -euo pipefail
ROOT=$(git -C "$(dirname "$0")" rev-parse --show-toplevel)
EXAMPLE="$ROOT/ai_agents/agents/examples/jev-turn-control"
APP="$ROOT/.bootstrap/official-app"
TMAN="${TMAN:-tman}"
if ! test -d "$APP"; then
    mkdir -p "$(dirname "$APP")"
    cp -a "$ROOT/packages/core_apps/default_app_python" "$APP"
fi
python3 - "$APP" <<'CONFIG'
import json
import sys
from pathlib import Path
app = Path(sys.argv[1])
path = app / "manifest.json"
manifest = json.loads(path.read_text())
dep = {"path": "../../packages/core_extensions/default_extension_python"}
if dep not in manifest["dependencies"]:
    manifest["dependencies"].append(dep)
path.write_text(json.dumps(manifest, indent=2) + "\n")
CONFIG
cd "$APP"
timeout --kill-after=5s 300s "$TMAN" -y install
export PYTHONPATH="$PWD/ten_packages/system/ten_runtime_python/lib:$PWD/ten_packages/system/ten_runtime_python/interface"
timeout --kill-after=5s 45s "$EXAMPLE/.venv/bin/python" -m pytest -q -s \
    "$ROOT/packages/core_extensions/default_extension_python/tests/test_basic.py"
