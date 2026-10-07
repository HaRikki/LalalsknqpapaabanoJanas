#!/usr/bin/env bash
# Anajak Host — Cloudflare Tunnel (auto-download cloudflared if missing)
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
BIN_DIR="$ROOT_DIR/bin"
CF_BIN="$BIN_DIR/cloudflared"

if [[ -f "$ROOT_DIR/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "$ROOT_DIR/.env"
  set +a
fi

LOCAL_URL="${CLOUDFLARE_TUNNEL_URL:-http://127.0.0.1:15794}"
TOKEN="${CLOUDFLARE_TUNNEL_TOKEN:-}"
TUNNEL_NAME="${CLOUDFLARE_TUNNEL_NAME:-}"
LOG_FILE="${CLOUDFLARE_TUNNEL_LOG:-$ROOT_DIR/logs/cloudflared.log}"

mkdir -p "$(dirname "$LOG_FILE")" "$BIN_DIR"

# send everything to Console and the log file, without a pipeline (so exec keeps one PID)
exec > >(tee -a "$LOG_FILE") 2>&1

resolve_cloudflared() {
  if command -v cloudflared >/dev/null 2>&1; then
    command -v cloudflared
    return
  fi
  if [[ -x "$CF_BIN" ]]; then
    echo "$CF_BIN"
    return
  fi
  echo ""
}

install_cloudflared() {
  echo "[cloudflare_tunnel] cloudflared not found — downloading..."
  ARCH="$(uname -m)"
  case "$ARCH" in
    x86_64|amd64)  CF_ARCH="amd64" ;;
    aarch64|arm64) CF_ARCH="arm64" ;;
    armv7l)        CF_ARCH="arm" ;;
    *)
      echo "[cloudflare_tunnel] ERROR: unsupported arch: $ARCH"
      exit 1
      ;;
  esac
  URL="https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-${CF_ARCH}"
  echo "[cloudflare_tunnel] GET $URL"
  if command -v curl >/dev/null 2>&1; then
    curl -fsSL -o "$CF_BIN" "$URL"
  elif command -v wget >/dev/null 2>&1; then
    wget -q -O "$CF_BIN" "$URL"
  else
    echo "[cloudflare_tunnel] ERROR: need curl or wget"
    exit 1
  fi
  chmod +x "$CF_BIN"
  echo "[cloudflare_tunnel] installed → $CF_BIN"
}

CF="$(resolve_cloudflared)"
if [[ -z "$CF" ]]; then
  install_cloudflared
  CF="$CF_BIN"
fi

echo "[cloudflare_tunnel] binary=$CF"
echo "[cloudflare_tunnel] target=$LOCAL_URL"
"$CF" --version 2>&1 | head -1 || true

if [[ -n "$TOKEN" ]]; then
  echo "[cloudflare_tunnel] mode=token"
  exec "$CF" tunnel --no-autoupdate run --token "$TOKEN"
elif [[ -n "$TUNNEL_NAME" ]]; then
  echo "[cloudflare_tunnel] mode=named name=$TUNNEL_NAME"
  exec "$CF" tunnel --no-autoupdate run "$TUNNEL_NAME"
else
  echo "[cloudflare_tunnel] mode=quick"
  exec "$CF" tunnel --no-autoupdate --url "$LOCAL_URL"
fi
