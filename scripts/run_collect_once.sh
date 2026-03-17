#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

# "Atomic" publish strategy:
# - run collector with a temp data dir (mounted to /aggregator/data)
# - only if it produced a non-empty clash.yaml, publish it to ./data via atomic rename
# This prevents breaking the existing local subscription when upstream sources fail.

mkdir -p data
chmod 777 data || true

ts="$(date +%Y%m%d-%H%M%S)"
tmp_dir="data._tmp.${ts}"
mkdir -p "$tmp_dir"
chmod 777 "$tmp_dir" || true

cleanup() {
  # best-effort cleanup (keep on failure for debugging if needed)
  rm -rf "$tmp_dir" 2>/dev/null || true
}
trap cleanup EXIT

# Run a single collection (outputs to /aggregator/data inside container)
# but we override the bind mount to write into tmp dir.
docker compose run --rm -v "$PWD/$tmp_dir:/aggregator/data" aggregator "$@"

candidate="$tmp_dir/clash.yaml"

# Publish only when we have a real output
if [ -f "$candidate" ] && grep -qE '^\s*proxies\s*:' "$candidate" && grep -qE 'name\s*:' "$candidate"; then
  echo "[run_collect_once] publish: $candidate -> data/clash.yaml"
  mv -f "$candidate" "data/clash.yaml.new"
  mv -f "data/clash.yaml.new" "data/clash.yaml"

  # carry over logs if present
  for f in last_run.log domains.txt coupons.txt valid-domains.txt subscribes.txt; do
    [ -f "$tmp_dir/$f" ] && mv -f "$tmp_dir/$f" "data/$f" || true
  done
else
  echo "[run_collect_once] no valid clash.yaml produced; keep existing data/clash.yaml unchanged"
  # still carry over last_run.log for troubleshooting
  [ -f "$tmp_dir/last_run.log" ] && mv -f "$tmp_dir/last_run.log" "data/last_run.log" || true
fi
