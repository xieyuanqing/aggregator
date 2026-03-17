#!/usr/bin/env bash
set -euo pipefail

# Update Clash kernel used by aggregator to MetaCubeX/mihomo (Linux amd64)
# This script is intended to run on a machine with `gh` installed and authenticated.

REPO="MetaCubeX/mihomo"
PREFER_VARIANT="v3"   # v1/v2/v3 are different build variants; v3 is generally feature-rich
DEST_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/clash"
DEST_BIN="$DEST_DIR/clash-linux-amd"

mkdir -p "$DEST_DIR"

tag=$(gh release view --repo "$REPO" --json tagName --jq .tagName)
assets=$(gh release view --repo "$REPO" --json assets --jq '.assets[].name')

pick_asset() {
  local variant="$1"
  # Prefer .gz static binary
  local name
  name=$(echo "$assets" | grep -E "^mihomo-linux-amd64-${variant}-v.*\\.gz$" | head -n 1 || true)
  if [ -n "$name" ]; then echo "$name"; return 0; fi
  name=$(echo "$assets" | grep -E '^mihomo-linux-amd64-v[0-9.]+\.gz$' | head -n 1 || true)
  if [ -n "$name" ]; then echo "$name"; return 0; fi
  return 1
}

asset=$(pick_asset "$PREFER_VARIANT")
if [ -z "$asset" ]; then
  echo "Failed to find suitable mihomo linux amd64 asset in $tag" >&2
  exit 1
fi

tmpdir=$(mktemp -d)
trap 'rm -rf "$tmpdir"' EXIT

echo "Downloading $REPO $tag asset: $asset"
( cd "$tmpdir" && gh release download --repo "$REPO" "$tag" -p "$asset" --clobber )

# Decompress
( cd "$tmpdir" && gunzip -f "$asset" )
raw_bin="$tmpdir/${asset%.gz}"

chmod +x "$raw_bin"

# Backup existing
if [ -f "$DEST_BIN" ]; then
  cp -a "$DEST_BIN" "$DEST_BIN.bak.$(date +%Y%m%d-%H%M%S)" || true
fi

mv -f "$raw_bin" "$DEST_BIN"
chmod +x "$DEST_BIN"

# Print version (best-effort)
"$DEST_BIN" -v 2>/dev/null || "$DEST_BIN" -version 2>/dev/null || true

echo "Updated kernel: $DEST_BIN"
