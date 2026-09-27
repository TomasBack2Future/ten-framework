#!/usr/bin/env bash
set -euo pipefail
ROOT=$(git -C "$(dirname "$0")" rev-parse --show-toplevel)
NAME=${JEV_CONTAINER:-ten-jev-bootstrap}
IMAGE=ghcr.io/ten-framework/ten_agent_build:0.7.14
TOOLS="$ROOT/.bootstrap/tools"
mkdir -p "$TOOLS" "$ROOT/.bootstrap/logs"
if ! test -f "$TOOLS/tman-linux-release-x64.zip"; then
    gh release download 0.11.73 --repo TEN-framework/ten-framework \
        --pattern tman-linux-release-x64.zip --dir "$TOOLS"
fi
(cd "$TOOLS" && echo '1ac22f455cc0be5f2541701bd38cacecc918f41a1b1b891889c71914cc3b3ab2  tman-linux-release-x64.zip' | sha256sum -c -)
unzip -qo "$TOOLS/tman-linux-release-x64.zip" -d "$TOOLS"
if docker container inspect "$NAME" >/dev/null 2>&1; then
    LABEL=$(docker inspect --format '{{index .Config.Labels "purpose"}}' "$NAME")
    MOUNT=$(docker inspect --format '{{range .Mounts}}{{if eq .Destination "/workspace"}}{{.Source}}{{end}}{{end}}' "$NAME")
    test "$LABEL" = jev-oss-bootstrap && test "$MOUNT" = "$ROOT" || {
        echo "Container name is already owned by another workspace: $NAME" >&2
        exit 1
    }
    docker start "$NAME" >/dev/null
else
    docker run -d --name "$NAME" --label purpose=jev-oss-bootstrap \
        --mount "type=bind,src=$ROOT,dst=/workspace" \
        --workdir /workspace --entrypoint sleep "$IMAGE" infinity
fi
printf 'Container ready: %s (no published ports)\n' "$NAME"
