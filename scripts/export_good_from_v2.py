#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Export "good" nodes from EasyProxiesV2 into a keep list for the next subscription build.

We use EasyProxiesV2 monitor API to:
- auth (POST /api/auth with management.password)
- list runtime node statuses (GET /api/nodes)
- list configured nodes including URI (GET /api/nodes/config)

Then we join by node name, select nodes that are:
- not disabled
- initial_check_done
- available
- not blacklisted

Output:
- data/keep_good.txt: one proxy URI per line

This is used to implement the "B方案": next publish = new random batch + previously verified good nodes.

Env:
- EP_CFG: path to easy_proxies_v2/config.yaml (default /root/vps-token-maintain/easy_proxies_v2/config.yaml)
- EP_PANEL: management base url (default http://127.0.0.1:9888)
- KEEP_GOOD: how many good nodes to keep (default 10)
"""

from __future__ import annotations

import json
import os
import sys
import urllib.request
from typing import Any, Dict, List

import yaml

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DATA_DIR = os.path.join(ROOT, "data")
OUT_FILE = os.path.join(DATA_DIR, "keep_good.txt")

EP_CFG = os.environ.get("EP_CFG", "/root/vps-token-maintain/easy_proxies_v2/config.yaml")
EP_PANEL = os.environ.get("EP_PANEL", "http://127.0.0.1:9888").rstrip("/")

try:
    KEEP_GOOD = int(os.environ.get("KEEP_GOOD", "10"))
except Exception:
    KEEP_GOOD = 10


def http_json(method: str, url: str, headers: Dict[str, str] | None = None, body: Any | None = None, timeout: int = 10) -> Any:
    h = {"Accept": "application/json"}
    if headers:
        h.update(headers)
    data = None
    if body is not None:
        raw = json.dumps(body).encode("utf-8")
        data = raw
        h["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=h, method=method)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        text = resp.read().decode("utf-8", errors="replace")
        if not text.strip():
            return {}
        return json.loads(text)


def main() -> int:
    os.makedirs(DATA_DIR, exist_ok=True)

    if not os.path.exists(EP_CFG):
        print(f"EP config not found: {EP_CFG}", file=sys.stderr)
        return 2

    cfg = yaml.safe_load(open(EP_CFG, "r", encoding="utf-8")) or {}
    pw = ((cfg.get("management") or {}).get("password") or "").strip()
    if not pw:
        print("management.password missing", file=sys.stderr)
        return 2

    auth = http_json("POST", f"{EP_PANEL}/api/auth", body={"password": pw}, timeout=5)
    token = (auth.get("token") or "").strip()
    if not token:
        print("auth failed", file=sys.stderr)
        return 3

    headers = {"Authorization": f"Bearer {token}"}

    runtime = http_json("GET", f"{EP_PANEL}/api/nodes", headers=headers, timeout=10) or {}
    config = http_json("GET", f"{EP_PANEL}/api/nodes/config", headers=headers, timeout=10) or {}

    runtime_nodes: List[Dict[str, Any]] = runtime.get("nodes") or []
    config_nodes: List[Dict[str, Any]] = config.get("nodes") or []

    # map name -> uri
    name2uri: Dict[str, str] = {}
    disabled: set[str] = set()
    for n in config_nodes:
        name = str(n.get("name") or "").strip()
        uri = str(n.get("uri") or "").strip()
        if not name or not uri:
            continue
        name2uri[name] = uri
        if bool(n.get("disabled")):
            disabled.add(name)

    good: List[tuple[int, str]] = []  # (latency, uri)
    for rn in runtime_nodes:
        name = str(rn.get("name") or rn.get("tag") or "").strip()
        if not name:
            continue
        if name in disabled:
            continue
        if bool(rn.get("blacklisted")):
            continue
        if not bool(rn.get("initial_check_done")):
            continue
        if not bool(rn.get("available")):
            continue

        uri = name2uri.get(name)
        if not uri:
            continue

        lat = rn.get("last_latency_ms")
        try:
            lat_i = int(lat) if lat is not None else 10**9
        except Exception:
            lat_i = 10**9
        if lat_i <= 0:
            lat_i = 10**9

        good.append((lat_i, uri))

    # sort by latency asc
    good.sort(key=lambda x: x[0])

    uris: List[str] = []
    seen = set()
    for _, u in good:
        if u in seen:
            continue
        seen.add(u)
        uris.append(u)
        if KEEP_GOOD > 0 and len(uris) >= KEEP_GOOD:
            break

    with open(OUT_FILE + ".new", "w", encoding="utf-8") as f:
        for u in uris:
            f.write(u + "\n")
    os.replace(OUT_FILE + ".new", OUT_FILE)

    print(f"exported_good={len(uris)} -> {OUT_FILE}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
