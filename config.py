import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

SECRET_KEY = os.getenv("SECRET_KEY", "anajak-dev-secret-change-in-production")
DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite+aiosqlite:///{BASE_DIR}/database/database.db")
PORT = int(os.getenv("PORT", "15794"))
APP_URL = os.getenv("APP_URL", f"http://localhost:{PORT}")
DEBUG = os.getenv("DEBUG", "true").lower() == "true"
DOCKER_ENABLED = os.getenv("DOCKER_ENABLED", "false").lower() == "true"
ADMIN_EMAIL = os.getenv("ADMIN_EMAIL", "admin@anajakhost.local")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "admin123456")

# Social login (can also be set from Admin → Login tab; the Admin value wins)
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "").strip()
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET", "").strip()
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_BOT_USERNAME = os.getenv("TELEGRAM_BOT_USERNAME", "").strip().lstrip("@")

# Cloudflare Tunnel (fill token in .env)
CLOUDFLARE_TUNNEL_TOKEN = os.getenv("CLOUDFLARE_TUNNEL_TOKEN", "").strip()  # paste token here via .env
# If CLOUDFLARE_TUNNEL_ENABLED is not set, a token alone turns the tunnel on.
_flag = os.getenv("CLOUDFLARE_TUNNEL_ENABLED", "").strip().lower()
CLOUDFLARE_TUNNEL_ENABLED = (_flag == "true") if _flag else bool(CLOUDFLARE_TUNNEL_TOKEN)
CLOUDFLARE_TUNNEL_NAME = os.getenv("CLOUDFLARE_TUNNEL_NAME", "")
CLOUDFLARE_TUNNEL_URL = os.getenv("CLOUDFLARE_TUNNEL_URL", f"http://127.0.0.1:{PORT}")

# Public display (Hostname / Server IP in panel)
SERVER_IP = os.getenv("SERVER_IP", "").strip()  # e.g. 51.81.90.228 — auto-detect if empty
HOST_PREFIX = os.getenv("HOST_PREFIX", "us").strip() or "us"  # us.angker.lol
HOST_BASE = os.getenv("HOST_BASE", "lol").strip() or "lol"  # TLD-style suffix for display host


# ── Hosting server layout ──────────────────────────────────
#   user_bots/user001/bot_1/...   project files of each hosting instance
#   data/user001/                 config.json, database.db, logs/, runtime/, backups/
USER_BOTS_DIR = BASE_DIR / "user_bots"
DATA_DIR = BASE_DIR / "data"
UPLOADS_DIR = BASE_DIR / "uploads"
# Old layout (only read once, to migrate existing hostings)
LEGACY_PROJECTS_DIR = BASE_DIR / "user_projects"
LEGACY_LOGS_DIR = BASE_DIR / "logs"
LEGACY_BACKUPS_DIR = BASE_DIR / "backups"

for d in (USER_BOTS_DIR, DATA_DIR, UPLOADS_DIR, LEGACY_LOGS_DIR, BASE_DIR / "database"):
    d.mkdir(parents=True, exist_ok=True)

ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24 * 7  # 7 days

# Cloudflare Turnstile (Human Verification)
# Get keys at https://dash.cloudflare.com/ → Turnstile
TURNSTILE_SITE_KEY = os.getenv("TURNSTILE_SITE_KEY", "").strip()
TURNSTILE_SECRET_KEY = os.getenv("TURNSTILE_SECRET_KEY", "").strip()
# When true AND both keys set → gate all page routes behind verification
HUMAN_VERIFY_ENABLED = os.getenv("HUMAN_VERIFY_ENABLED", "true").lower() == "true"
HUMAN_COOKIE_NAME = "ah_human"
HUMAN_COOKIE_HOURS = int(os.getenv("HUMAN_COOKIE_HOURS", "24"))

