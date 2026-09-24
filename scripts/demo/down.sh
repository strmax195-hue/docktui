#!/bin/sh
cd "$(dirname "$0")"
docker compose -f shop.compose.yml down
docker compose -f monitoring.compose.yml down
docker rm -f traefik nightly-backup >/dev/null 2>&1 || true
