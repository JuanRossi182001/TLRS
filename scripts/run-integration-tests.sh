#!/usr/bin/env bash
set -euo pipefail

compose_file="docker-compose.test.yml"
test_database_url="postgresql://tlrs_test:tlrs_test@127.0.0.1:55432/tlrs_test"

cleanup() {
  docker compose -f "$compose_file" down --volumes --remove-orphans
}
trap cleanup EXIT

docker compose -f "$compose_file" up -d --wait

TEST_DATABASE_URL="$test_database_url" \
  .venv/bin/python -m pytest -m integration "$@"
