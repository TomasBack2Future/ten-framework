#!/usr/bin/env bash
set -euo pipefail
ROOT=$(git -C "$(dirname "$0")" rev-parse --show-toplevel)
NAME=${JEV_CONTAINER:-ten-jev-bootstrap}
FILE="$ROOT/.bootstrap/tools/ten_runtime-0.11.73.tpkg"
CHECKSUM=414dc2e971296117d13881b71e57ad7f087f72fa54ead8976cf6e6e630136f8f
PACKAGE=system-ten_runtime-0.11.7333a763f1a571a8136fe1cf2fcc2f114cf2b36bc093ed8092a072f7f58b399103.tpkg
mkdir -p "$(dirname "$FILE")"
if ! echo "$CHECKSUM  $FILE" | sha256sum -c - 2>/dev/null; then
    curl -fL -C - --connect-timeout 10 --max-time 900 \
        --speed-time 60 --speed-limit 1024 \
        -o "$FILE" "https://rte-store.s3.amazonaws.com/ten-packages/$PACKAGE"
fi
echo "$CHECKSUM  $FILE" | sha256sum -c -
LABEL=$(docker inspect --format '{{index .Config.Labels "purpose"}}' "$NAME")
MOUNT=$(docker inspect --format '{{range .Mounts}}{{if eq .Destination "/workspace"}}{{.Source}}{{end}}{{end}}' "$NAME")
test "$LABEL" = jev-oss-bootstrap && test "$MOUNT" = "$ROOT"
docker exec "$NAME" mkdir -p /root/.tman/package_cache/system/ten_runtime/0.11.73
docker cp "$FILE" "$NAME:/root/.tman/package_cache/system/ten_runtime/0.11.73/$PACKAGE"
