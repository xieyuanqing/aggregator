#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

mkdir -p data
chmod 777 data || true

# Run a single collection (outputs to ./data)
docker compose run --rm aggregator
