#!/usr/bin/env bash
set -euo pipefail

docker compose up -d postgres app

docker compose exec -T app python -m src.ecom_lifecycle.scheduler \
  --interval-minutes "${REFRESH_INTERVAL_MINUTES:-360}" \
  --profile "${REFRESH_PROFILE:-demo}" \
  ${REFRESH_LOCAL_ONLY:+--local-only}
