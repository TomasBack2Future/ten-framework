#!/usr/bin/env bash
set -euo pipefail
: "${KUBECONFIG:?Use a scoped operator kubeconfig; never put it into GitHub Actions}"
DIGEST=${1:?Usage: deploy.sh sha256:... mock|live}
MODE=${2:-mock}
[[ "$DIGEST" =~ ^sha256:[a-f0-9]{64}$ ]]
[[ "$MODE" = mock || "$MODE" = live ]]
cd "$(dirname "$0")"
python3 - "$DIGEST" "$MODE" <<'PY' | kubectl -n ten-jev-demo apply -f -
from pathlib import Path
import sys
text = Path('demo.yaml').read_text().replace('ghcr.io/tomasback2future/jev-turn-control:REPLACE_WITH_SHA', 'ghcr.io/tomasback2future/jev-turn-control@'+sys.argv[1])
if sys.argv[2] == 'live':
    text = text.replace('{name: JEV_MODE, value: mock}', '{name: JEV_MODE, value: live}')
    text = text.replace('        env:\n', '        envFrom:\n        - secretRef: {name: jev-provider-keys}\n        env:\n        - {name: GROQ_MODEL, value: openai/gpt-oss-20b}\n')
print(text)
PY
kubectl -n ten-jev-demo rollout status deployment/jev-demo --timeout=120s
kubectl -n ten-jev-demo get pods -l app=jev-demo -o wide
