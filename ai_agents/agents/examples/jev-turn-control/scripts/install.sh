#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
TMAN="${TMAN:-tman}"
ARGS=(-y)
if [[ -n "${TMAN_CONFIG:-}" ]]; then ARGS+=(-c "$TMAN_CONFIG"); fi
(cd tenapp && timeout --kill-after=5s 300s "$TMAN" "${ARGS[@]}" install)
# Local extension API imports resolve from their source paths.
BASE=../../ten_packages/system/ten_ai_base
if ! test -e "$BASE"; then
    mkdir -p ../../ten_packages/system
    ln -s ../../examples/jev-turn-control/tenapp/ten_packages/system/ten_ai_base "$BASE"
fi
if ! test -x .venv/bin/python; then
    uv venv --python python3 --system-site-packages .venv
fi
uv pip install --link-mode=copy --python .venv/bin/python -r requirements-dev.txt \
  "websockets==15.0.1" "pydantic>=2.0" \
  "openai==1.109.1" "httpx==0.28.1" "aiohttp==3.12.15" \
  -r ../../ten_packages/extension/soniox_asr_python/requirements.txt \
  -r ../../ten_packages/extension/openai_llm2_python/requirements.txt \
  -r ../../ten_packages/extension/cartesia_tts/requirements.txt \
  -r tenapp/ten_packages/system/ten_ai_base/requirements.txt
python3 - <<'CHECK'
import json
from pathlib import Path
for name in ("ten_runtime", "ten_runtime_python"):
    path = Path("tenapp/ten_packages/system") / name / "manifest.json"
    assert json.loads(path.read_text())["version"] == "0.11.73", path
print("Runtime packages pinned to 0.11.73")
CHECK
