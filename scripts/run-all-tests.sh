#!/usr/bin/env bash
set -euo pipefail

scripts/run-tests.sh "$@"
scripts/run-integration-tests.sh
