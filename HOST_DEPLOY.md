# Deploy Anajak Host (Apsara / VPS)

## 1. Upload
Unzip project, keep this folder structure.

## 2. Environment
```bash
cp .env .env.bak 2>/dev/null || true
# Edit .env — SECRET_KEY, ADMIN_PASSWORD, CLOUDFLARE_TUNNEL_TOKEN
```

Or set in panel **Environment / Startup variables**:
- `CLOUDFLARE_TUNNEL_ENABLED=true`
- `CLOUDFLARE_TUNNEL_TOKEN=` (your token)
- `CLOUDFLARE_TUNNEL_URL=http://127.0.0.1:15794`
- `PORT=15794`

## 3. Install & run
```bash
pip install -r requirements.txt
bash start.sh
# or: python app.py
```

## 4. Cloudflare Tunnel
Dashboard → Zero Trust → Tunnels → Public Hostname:
- Hostname: your domain (e.g. angker-smm.ndclub.top)
- Service: `http://localhost:15794`

After start, console must show tunnel connected (not "disabled").

## 5. Admin login
Default: see `ADMIN_EMAIL` / `ADMIN_PASSWORD` in `.env` — change after first login.

## Error 1033
= tunnel token missing or cloudflared not connected. Check token + Public Hostname + app listening on 15794.
