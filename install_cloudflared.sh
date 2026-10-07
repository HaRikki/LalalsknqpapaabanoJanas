#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
mkdir -p "$ROOT/bin"
ARCH="$(uname -m)"
case "$ARCH" in
  x86_64|amd64)  A=amd64 ;;
  aarch64|arm64) A=arm64 ;;
  armv7l)        A=arm ;;
  *) echo "Unsupported arch: $ARCH"; exit 1 ;;
esac
URL="https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-${A}"
OUT="$ROOT/bin/cloudflared"
echo "[install] arch=$ARCH → $URL"
if command -v curl >/dev/null 2>&1; then
  curl -fsSL -o "$OUT" "$URL"
elif command -v wget >/dev/null 2>&1; then
  wget -q -O "$OUT" "$URL"
else
  echo "Need curl or wget"; exit 1
fi
chmod +x "$OUT"
"$OUT" --version
echo "[install] OK → $OUT"
