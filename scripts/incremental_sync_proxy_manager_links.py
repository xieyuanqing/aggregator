#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Incremental sync for proxy-manager subscription -> local plain-links subscription.

EasyProxiesV2 subscription refresh (internal/subscription/manager.go) only supports:
- base64-encoded plain text, OR
- plain text with one proxy URI per line (vless://, vmess://, trojan://, ss://, etc.)

It does NOT parse Clash YAML. So we generate data/sub.txt in that format.

Behavior:
- Fetch remote content from secrets URL (do not print URL)
- If content is base64, decode
- Extract proxy URIs line-by-line
- Incrementally merge into a local pool, evict stale entries by last_seen
- Cap total size
- Atomic publish to data/sub.txt

Environment variables:
- RETENTION_HOURS (default 168)
- MAX_LINKS (default 300)
- SYNC_HTTP_TIMEOUT (default 60)
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import sys
import time
import urllib.request
from typing import Dict, Any, List


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DATA_DIR = os.path.join(ROOT, "data")
SECRETS_URL_FILE = os.path.join(ROOT, "secrets", "proxy_manager_links_url.txt")
STATE_FILE = os.path.join(DATA_DIR, "pool_state_links.json")
OUT_FILE = os.path.join(DATA_DIR, "sub.txt")
LAST_SYNC_LOG = os.path.join(DATA_DIR, "last_sync_links.log")
KEEP_GOOD_FILE = os.path.join(DATA_DIR, "keep_good.txt")


def _env_int(name: str, default: int) -> int:
    try:
        v = os.environ.get(name, "").strip()
        return int(v) if v else default
    except Exception:
        return default


RETENTION_HOURS = _env_int("RETENTION_HOURS", 24 * 7)  # 7d
# MAX_LINKS=0 means unlimited (no cap)
MAX_LINKS = _env_int("MAX_LINKS", 300)
HTTP_TIMEOUT = _env_int("SYNC_HTTP_TIMEOUT", 60)


URI_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.-]*://")


def log_line(line: str) -> None:
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(LAST_SYNC_LOG, "a", encoding="utf-8") as f:
        f.write(line.rstrip("\n") + "\n")


def read_text(path: str) -> str:
    with open(path, "r", encoding="utf-8") as f:
        return f.read().strip()


def http_get_bytes(url: str, timeout: int) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "incremental-sync-links/1.0", "Accept": "*/*"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        if resp.status != 200:
            raise RuntimeError(f"status {resp.status}")
        return resp.read()


def looks_like_base64(text: str) -> bool:
    s = text.strip().replace("\n", "").replace("\r", "")
    if not s:
        return False
    if "://" in s:
        return False
    try:
        base64.b64decode(s, validate=False)
        return True
    except Exception:
        return False


def decode_maybe_base64(raw: bytes) -> str:
    text = raw.decode("utf-8", errors="replace")
    t = text.strip()
    if looks_like_base64(t):
        s = t.replace("\n", "").replace("\r", "")
        for fn in (base64.b64decode, base64.urlsafe_b64decode):
            try:
                decoded = fn(s + "==")
                return decoded.decode("utf-8", errors="replace")
            except Exception:
                continue
    return text


def extract_uris(text: str) -> List[str]:
    uris: List[str] = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if URI_RE.match(line):
            uris.append(line)
    return uris


def uri_key(uri: str) -> str:
    return hashlib.sha1(uri.encode("utf-8", errors="ignore")).hexdigest()


def load_state() -> Dict[str, Any]:
    if not os.path.exists(STATE_FILE):
        return {"version": 1, "items": {}}
    with open(STATE_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict) or "items" not in data or not isinstance(data["items"], dict):
        return {"version": 1, "items": {}}
    # ensure each item is a mapping
    items = data.get("items") or {}
    if isinstance(items, dict):
        for k, v in list(items.items()):
            if not isinstance(v, dict):
                items.pop(k, None)
    data["items"] = items
    return data


def save_state(state: Dict[str, Any]) -> None:
    tmp = STATE_FILE + ".new"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
    os.replace(tmp, STATE_FILE)


def atomic_write_text(path: str, text: str) -> None:
    tmp = path + ".new"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, path)


def main() -> int:
    os.makedirs(DATA_DIR, exist_ok=True)

    if not os.path.exists(SECRETS_URL_FILE):
        print(f"missing secrets url file: {SECRETS_URL_FILE}", file=sys.stderr)
        return 2

    url = read_text(SECRETS_URL_FILE)
    if not url:
        print(f"empty url in: {SECRETS_URL_FILE}", file=sys.stderr)
        return 2

    now = int(time.time())

    raw = http_get_bytes(url, timeout=HTTP_TIMEOUT)
    content = decode_maybe_base64(raw)
    incoming = extract_uris(content)

    if len(incoming) == 0:
        print("upstream returned 0 proxy URIs", file=sys.stderr)
        return 3

    # Load keep-good URIs if present (B方案: new batch + previously verified good nodes)
    keep_good: List[str] = []
    if os.path.exists(KEEP_GOOD_FILE):
        try:
            with open(KEEP_GOOD_FILE, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    if URI_RE.match(line):
                        keep_good.append(line)
        except Exception:
            keep_good = []

    state = load_state()
    items: Dict[str, Any] = state["items"]

    # reset pinned flags
    for it in items.values():
        if isinstance(it, dict):
            it.pop("pinned", None)

    added = 0
    updated = 0

    def upsert(uri: str, pinned: bool = False) -> None:
        nonlocal added, updated
        k = uri_key(uri)
        it = items.get(k)
        if it is None:
            items[k] = {"uri": uri, "first_seen": now, "last_seen": now, "seen": 1, "pinned": pinned}
            added += 1
        else:
            it["uri"] = uri
            it["last_seen"] = now
            it["seen"] = int(it.get("seen", 0)) + 1
            if pinned:
                it["pinned"] = True
            updated += 1

    # always keep-good first (so they don't get evicted by retention)
    for uri in keep_good:
        upsert(uri, pinned=True)

    for uri in incoming:
        upsert(uri, pinned=False)

    retention_sec = RETENTION_HOURS * 3600
    before = len(items)
    stale = [k for k, it in items.items() if not it.get("pinned") and now - int(it.get("last_seen", 0)) > retention_sec]
    for k in stale:
        items.pop(k, None)

    # Cap size if MAX_LINKS > 0
    if MAX_LINKS > 0 and len(items) > MAX_LINKS:
        ranked = sorted(items.items(), key=lambda kv: (0 if kv[1].get("pinned") else 1, -int(kv[1].get("last_seen", 0))))
        keep = dict(ranked[:MAX_LINKS])
        items.clear()
        items.update(keep)

    removed = before - len(items)

    # Output: pinned first, then recent
    def sort_key(it: Dict[str, Any]):
        pinned = 1 if it.get("pinned") else 0
        return (-pinned, -int(it.get("last_seen", 0)))

    out_list = [it["uri"] for it in sorted(items.values(), key=sort_key)]
    if len(out_list) == 0:
        print("refusing to publish empty sub.txt", file=sys.stderr)
        return 4

    atomic_write_text(OUT_FILE, "\n".join(out_list) + "\n")
    save_state(state)

    summary = (
        f"{time.strftime('%Y-%m-%d %H:%M:%S')} sync_ok "
        f"incoming={len(incoming)} keep_good={len(keep_good)} added={added} updated={updated} removed={removed} kept={len(out_list)} "
        f"retention_hours={RETENTION_HOURS} max_links={MAX_LINKS}"
    )
    log_line(summary)
    print(summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
