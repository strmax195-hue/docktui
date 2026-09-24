#!/bin/sh
# Start the demo environment used for README screenshots.
# Uses busybox re-tagged under realistic image names, so it needs no registry
# access beyond a single `docker pull busybox`.
set -e
cd "$(dirname "$0")"
docker pull -q busybox >/dev/null
for tag in shop/web:2.4.1 shop/api:2.4.1 shop/worker:2.4.1 postgres:16-alpine redis:7-alpine \
           grafana/grafana:11.2 prom/prometheus:v2.54 traefik:v3.1; do
  docker tag busybox "$tag"
done
docker compose -f shop.compose.yml up -d
docker compose -f monitoring.compose.yml up -d
docker run -d --name traefik -p 443:443 traefik:v3.1 sleep 100000 >/dev/null 2>&1 || true
docker run --name nightly-backup busybox sh -c 'exit 2' >/dev/null 2>&1 || true
echo "Demo stacks are up. Tear down with: $(dirname "$0")/down.sh"
