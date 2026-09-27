#!/usr/bin/env bash
set -euo pipefail
: "${KUBECONFIG:?Point to an authorized operator kubeconfig; never upload it to CI}"
: "${CERTBOT_TOKEN:?}" "${CERTBOT_VALIDATION:?}" "${CERTBOT_DOMAIN:?}"
test "$CERTBOT_DOMAIN" = jev-demo.hipaa-poc.agoralab.co
kubectl -n ten-jev-demo create configmap jev-acme --from-literal="$CERTBOT_TOKEN=$CERTBOT_VALIDATION" --dry-run=client -o yaml | kubectl -n ten-jev-demo apply -f -
kubectl -n ten-jev-demo rollout restart deployment/jev-acme
kubectl -n ten-jev-demo rollout status deployment/jev-acme --timeout=60s
for attempt in {1..12}; do
  if [[ "$(curl -fsS --max-time 10 "http://$CERTBOT_DOMAIN/.well-known/acme-challenge/$CERTBOT_TOKEN")" = "$CERTBOT_VALIDATION" ]]; then exit 0; fi
  sleep 3
done
exit 1
