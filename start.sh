#!/usr/bin/env bash
# Anajak Host — start panel + optional Cloudflare tunnel
set -euo pipefail
cd "$(dirname "$0")"

export PATH="$PWD/bin:$PATH"

if [[ ! -f .env ]]; then
  cp .env.example .env
  echo "Created .env — edit CLOUDFLARE_TUNNEL_TOKEN if needed"
fi

# Pre-install cloudflared so tunnel works on Apsara/containers without system package
if [[ ! -x bin/cloudflared ]] && ! command -v cloudflared >/dev/null 2>&1; then
  echo "[start] Installing cloudflared..."
  bash scripts/install_cloudflared.sh || true
fi

# Prefer local venv pip deps if present
if [[ -d .venv ]]; then
  # shellcheck disable=SC1091
  source .venv/bin/activate
fi

echo "[start] Anajak Host on port ${PORT:-15794}"
exec python app.py
