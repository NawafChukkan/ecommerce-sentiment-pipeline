#!/usr/bin/env bash
set -euo pipefail

docker compose up -d postgres app
docker compose exec -T app python -m src.ecom_lifecycle.generate_seed --profile assignment --target-size-gb "${SEED_TARGET_SIZE_GB:-1.5}" --replace --local-only
docker compose exec -T app python -m src.ecom_lifecycle.spark.jobs.pipeline --replace-output --local-only
