#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

# Incremental sync: proxy-manager -> data/sub.txt (plain proxy URIs)
# Output is designed for EasyProxiesV2 subscription refresh manager.
#
# Put the full URL (with token/params) into:
#   ./secrets/proxy_manager_links_url.txt
#
# Then run:
#   bash scripts/sync_proxy_manager_links.sh

mkdir -p data
chmod 777 data || true

export RETENTION_HOURS=${RETENTION_HOURS:-168}  # 7 days
export MAX_LINKS=${MAX_LINKS:-300}
export SYNC_HTTP_TIMEOUT=${SYNC_HTTP_TIMEOUT:-60}

python3 scripts/incremental_sync_proxy_manager_links.py
