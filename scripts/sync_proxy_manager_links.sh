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
# For now: do not cap by default (user can set MAX_LINKS later when pool grows)
export MAX_LINKS=${MAX_LINKS:-0}
export SYNC_HTTP_TIMEOUT=${SYNC_HTTP_TIMEOUT:-60}
export KEEP_GOOD=${KEEP_GOOD:-10}

# Best-effort: export currently verified-good nodes from EasyProxiesV2 to keep list.
# If auth fails / service down, we still continue with upstream sync.
python3 scripts/export_good_from_v2.py >/dev/null 2>&1 || true

python3 scripts/incremental_sync_proxy_manager_links.py
