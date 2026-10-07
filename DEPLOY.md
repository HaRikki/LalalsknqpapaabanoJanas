# Deploy Anajak Host — Render / Railway / VPS / Vercel notes

## Important reality check

| Platform | Suitable? | Notes |
|----------|-----------|-------|
| **Render.com** (Web Service) | ✅ Yes (panel UI + DB) | Free sleeps after idle. Disk is **ephemeral** — user_projects / logs reset on redeploy. Use Postgres. |
| **Railway.app** | ✅ Yes | Similar to Render, good free/paid tiers. |
| **Vercel** | ❌ Not suitable | Serverless only. No long-running processes, no subprocess for user bots, no persistent FS for projects. |
| **VPS** (Hetzner, Contabo, DO, Apsara) | ✅ Best | Full process manager, persistent disk, 24/7 bots. |
| **Fly.io / Railway / Render paid** | ✅ Good | Persistent disk options available. |

This app is a **hosting control panel** that starts/stops user project processes (bots, games, etc.).  
That requires a real machine with disk + process control → **VPS is recommended** for production bots.

For **UI testing + admin + billing**, Render Free + Postgres is fine.

---

## 1. Deploy on Render.com (recommended free test)

### A. Push to GitHub

1. Create a new GitHub repo.
2. Upload **only** these (do NOT upload `.env` with secrets, `database/`, `user_bots/`, `data/`, `logs/`):

```
app.py
requirements.txt
render.yaml
README.md
DEPLOY.md
core/
templates/
static/
scripts/
start.sh
.env.example
```

### B. Create services

1. Render Dashboard → **New → Blueprint** → connect the repo (uses `render.yaml`)  
   **OR** manually:
2. **New → PostgreSQL** (Free) → name `anajak-db` → copy Internal Database URL.
3. **New → Web Service**:
   - Runtime: **Python 3**
   - Build: `pip install -r requirements.txt`
   - Start: `uvicorn app:app --host 0.0.0.0 --port $PORT`
   - Plan: Free

### C. Environment variables

| Key | Value |
|-----|--------|
| `SECRET_KEY` | long random string (or let Render generate) |
| `DATABASE_URL` | Internal Postgres URL from the DB service |
| `APP_URL` | `https://YOUR-SERVICE.onrender.com` |
| `DEBUG` | `false` |
| `DOCKER_ENABLED` | `false` |
| `CLOUDFLARE_TUNNEL_ENABLED` | `false` |
| `HUMAN_VERIFY_ENABLED` | `false` |
| `ADMIN_EMAIL` | your email |
| `ADMIN_PASSWORD` | strong password |

### D. After deploy

Open `https://YOUR-SERVICE.onrender.com/login`  
Login with ADMIN_EMAIL / ADMIN_PASSWORD.

---

## 2. Deploy on Railway.app

1. New Project → Deploy from GitHub
2. Add **PostgreSQL** plugin
3. Variables: same as above (`DATABASE_URL` is auto-injected often)
4. Start command: `uvicorn app:app --host 0.0.0.0 --port $PORT`

---

## 3. Deploy on VPS (best for real hosting)

```bash
# Ubuntu example
sudo apt update && sudo apt install -y python3-pip python3-venv git
git clone YOUR_REPO anajak-host && cd anajak-host
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
nano .env   # set SECRET_KEY, ADMIN_*, APP_URL, etc.
mkdir -p database data user_bots uploads logs
python app.py
# or with systemd / screen / pm2
```

Optional Cloudflare Tunnel: set `CLOUDFLARE_TUNNEL_ENABLED=true` and paste token.

---

## 4. Why Vercel will not work well

- Vercel is **serverless functions** (short-lived).
- This app needs:
  - Long-running process manager (`process_manager` starts bots)
  - Persistent filesystem for `user_bots/`, `data/`, uploads
  - WebSocket / continuous log streaming
- Result: panel may load, but **Start/Stop project will fail**.

Use Render/Railway for testing the panel, VPS for real bots.

---

## 5. Common fixes already applied in this package

- Added `asyncpg` to `requirements.txt` (required for Render Postgres)
- Clean `.env.example` (no real secrets)
- `render.yaml` ready for Blueprint deploy
- `CLOUDFLARE_TUNNEL_ENABLED=false` by default for cloud hosts
- Health check: `GET /health`

