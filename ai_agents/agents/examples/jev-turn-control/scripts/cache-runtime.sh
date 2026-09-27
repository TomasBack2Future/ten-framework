#!/usr/bin/env bash
set -euo pipefail
# The runtime artifact used by tman install is verified in every image build.
PACKAGE=system-ten_runtime-0.11.7333a763f1a571a8136fe1cf2fcc2f114cf2b36bc093ed8092a072f7f58b399103.tpkg
CACHE=/root/.tman/package_cache/system/ten_runtime/0.11.73
mkdir -p "$CACHE"
curl --fail --location --retry 3 --connect-timeout 15 --max-time 900 \
  "https://rte-store.s3.amazonaws.com/ten-packages/$PACKAGE" -o "$CACHE/$PACKAGE"
echo "414dc2e971296117d13881b71e57ad7f087f72fa54ead8976cf6e6e630136f8f  $CACHE/$PACKAGE" | sha256sum --check -
