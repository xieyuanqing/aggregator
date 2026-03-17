#!/usr/bin/env bash
set -euo pipefail

# Lightweight CLI controller for:
# - syncing proxy-manager (incremental) into data/sub.txt
# - refreshing EasyProxiesV2 subscription via local management API
# - showing status
#
# No extra ports/services required.

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DATA_DIR="$ROOT/data"
LOCK_FILE="/tmp/aggregator_ctl.lock"

EP_CFG_DEFAULT="/root/vps-token-maintain/easy_proxies_v2/config.yaml"
EP_PANEL_DEFAULT="http://127.0.0.1:9888"

usage() {
  cat <<'EOF'
Usage:
  scripts/ctl.sh                 # interactive menu
  scripts/ctl.sh status          # show status
  scripts/ctl.sh sync            # sync upstream -> data/sub.txt (incremental)
  scripts/ctl.sh refresh         # refresh EasyProxiesV2 subscription
  scripts/ctl.sh sync-refresh    # sync then refresh
  scripts/ctl.sh tail            # tail recent logs

Env overrides:
  EP_CFG=/path/to/easy_proxies_v2/config.yaml
  EP_PANEL=http://127.0.0.1:9888
EOF
}

_ep_cfg() {
  echo "${EP_CFG:-$EP_CFG_DEFAULT}"
}

_ep_panel() {
  echo "${EP_PANEL:-$EP_PANEL_DEFAULT}"
}

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "missing command: $1" >&2
    exit 2
  }
}

with_lock() {
  require_cmd flock
  exec 9>"$LOCK_FILE"
  if ! flock -n 9; then
    echo "another operation is running (lock: $LOCK_FILE)" >&2
    exit 3
  fi
  "$@"
}

sub_txt_count() {
  if [ -f "$DATA_DIR/sub.txt" ]; then
    wc -l < "$DATA_DIR/sub.txt" | tr -d ' '
  else
    echo 0
  fi
}

pool_count() {
  if [ -f "$DATA_DIR/pool_state_links.json" ]; then
    python3 - <<'PY'
import json
p='data/pool_state_links.json'
obj=json.load(open(p,'r',encoding='utf-8'))
items=obj.get('items') or {}
print(len(items))
PY
  else
    echo 0
  fi
}

show_status() {
  mkdir -p "$DATA_DIR" || true
  echo "== aggregator local =="
  echo "root: $ROOT"
  echo "sub.txt lines: $(sub_txt_count)"
  echo "pool size (dedup): $(pool_count)"
  if [ -f "$DATA_DIR/last_sync_links.log" ]; then
    echo "last sync:"
    tail -n 3 "$DATA_DIR/last_sync_links.log" || true
  else
    echo "last sync: (none)"
  fi
  echo

  echo "== data-server =="
  if curl -sS -I --max-time 3 http://127.0.0.1:8099/sub.txt >/dev/null 2>&1; then
    curl -sS -I --max-time 3 http://127.0.0.1:8099/sub.txt | head -n 5
  else
    echo "http://127.0.0.1:8099/sub.txt unreachable"
  fi
  echo

  echo "== EasyProxiesV2 subscription status =="
  local cfg panel
  cfg="$(_ep_cfg)"
  panel="$(_ep_panel)"

  if [ ! -f "$cfg" ]; then
    echo "config not found: $cfg" >&2
    return 0
  fi

  # get password from yaml (do NOT echo)
  local pw token
  pw=$(python3 - <<PY
import yaml
cfg=yaml.safe_load(open('$cfg','r',encoding='utf-8'))
print(cfg.get('management',{}).get('password',''))
PY
)
  if [ -z "$pw" ]; then
    echo "management.password not found in $cfg" >&2
    return 0
  fi

  token=$(curl -sS --max-time 5 -H 'Content-Type: application/json' -d "{\"password\":\"$pw\"}" "$panel/api/auth" | python3 - <<'PY'
import sys, json
try:
  print(json.load(sys.stdin).get('token',''))
except Exception:
  print('')
PY
)

  if [ -z "$token" ]; then
    echo "auth failed (panel: $panel)" >&2
    return 0
  fi

  curl -sS --max-time 5 -H "Authorization: Bearer $token" "$panel/api/subscription/status" || true
  echo
}

sync_upstream() {
  with_lock bash -lc "cd '$ROOT' && bash scripts/sync_proxy_manager_links.sh"
}

refresh_v2() {
  with_lock bash -lc '
set -euo pipefail
cfg="'"$(_ep_cfg)"'"
panel="'"$(_ep_panel)"'"

pw=$(python3 - <<PY
import yaml
cfg=yaml.safe_load(open("'$(_ep_cfg)'","r",encoding="utf-8"))
print(cfg.get("management",{}).get("password",""))
PY
)
if [ -z "$pw" ]; then
  echo "management.password not found" >&2
  exit 2
fi

token=$(curl -sS --max-time 5 -H "Content-Type: application/json" -d "{\"password\":\"$pw\"}" "$panel/api/auth" | python3 - <<"PY"
import sys, json
try:
  print(json.load(sys.stdin).get("token",""))
except Exception:
  print("")
PY
)
if [ -z "$token" ]; then
  echo "auth failed" >&2
  exit 3
fi

# trigger refresh
http_code=$(curl -sS -o /tmp/ep_refresh.out -w "%{http_code}" -X POST -H "Authorization: Bearer $token" "$panel/api/subscription/refresh")
echo "refresh_http_code=$http_code"
cat /tmp/ep_refresh.out
'
}

tail_logs() {
  echo "== last_sync_links.log =="
  tail -n 50 "$DATA_DIR/last_sync_links.log" 2>/dev/null || echo "(none)"
  echo
  echo "== EasyProxiesV2 journal (last 60 lines) =="
  journalctl -u easy-proxies-v2.service -n 60 --no-pager 2>/dev/null || true
}

interactive() {
  while true; do
    cat <<'EOF'

[aggregator ctl]
  1) status
  2) sync upstream -> sub.txt
  3) refresh V2 subscription
  4) sync + refresh
  5) tail logs
  q) quit
EOF
    read -r -p "> " choice || true
    case "$choice" in
      1) show_status ;;
      2) sync_upstream ;;
      3) refresh_v2 ;;
      4) sync_upstream && refresh_v2 ;;
      5) tail_logs ;;
      q|Q) exit 0 ;;
      *) echo "unknown: $choice" ;;
    esac
  done
}

main() {
  require_cmd python3
  require_cmd curl

  local cmd="${1:-}"
  case "$cmd" in
    "" ) interactive ;;
    -h|--help|help) usage ;;
    status) show_status ;;
    sync) sync_upstream ;;
    refresh) refresh_v2 ;;
    sync-refresh) sync_upstream && refresh_v2 ;;
    tail) tail_logs ;;
    *) echo "unknown command: $cmd" >&2; usage; exit 2 ;;
  esac
}

main "$@"
