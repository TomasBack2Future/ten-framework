#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/../tenapp"
export PYTHONPATH="$PWD/ten_packages/system/ten_runtime_python/lib:$PWD/ten_packages/system/ten_runtime_python/interface:$PWD/ten_packages/system/ten_ai_base/interface"
export LD_LIBRARY_PATH="$PWD/ten_packages/system/agora_rtc_sdk/lib:$PWD/ten_packages/system/ten_runtime/lib:${LD_LIBRARY_PATH:-}"
exec ../.venv/bin/python -u main.py
