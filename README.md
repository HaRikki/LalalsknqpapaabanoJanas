# Anajak Host — Professional Hosting Panel

Universal control panel for bots, websites, APIs and game servers.

## Stack
- **Backend:** FastAPI + SQLAlchemy (async) + SQLite/PostgreSQL
- **Process:** asyncio subprocess (+ optional Docker when `DOCKER_ENABLED=true`)
- **Tunnel:** Cloudflare Tunnel (token in `.env`)
- **UI:** Jinja2 templates, original Anajak panel design

## Quick start
```bash
cp .env.example .env   # edit secrets, PORT, CLOUDFLARE_TUNNEL_TOKEN, SERVER_IP
pip install -r requirements.txt
bash start.sh
# or: python app.py
```

Default admin (change after first login): see `.env` → `ADMIN_EMAIL` / `ADMIN_PASSWORD`

## Feature status

| Feature | Status | Notes |
|--------|--------|-------|
| Auth register/login/logout | **Completed** | Password hashing (bcrypt) |
| Google + Telegram login | **Completed** | Configure in Admin → Login, see LOGIN_SETUP_KM.md |
| ABA KHQR payment | **Completed** | Admin → Payment, see PAYMENT_SETUP_KM.md |
| Login history | **Completed** | IP + user-agent stored |
| User dashboard + projects | **Completed** | Real DB + process status |
| Start / Stop / Restart | **Completed** | Process manager |
| Auto-restart on crash | **Completed** | Background monitor |
| File manager (upload/download/mkdir/delete) | **Completed** | Sandboxed paths |
| Unarchive ZIP/TAR + ZIP compress | **Completed** | Zip-slip protected |
| Rename / Copy / Move / Edit file | **Completed** | Text edit max 2MB |
| Console logs | **Completed** | File-based logs |
| Metrics CPU/RAM/Disk | **Completed** | psutil per process |
| Manual backup + restore | **Completed** | ZIP to backups/, download + delete + restore from the panel |
| Custom domains + DNS verify | **Completed** | SSL via Cloudflare/proxy (host config) |
| Git deploy (clone/pull) | **Completed** | Token not stored |
| Env vars | **Completed** | Per project; show/hide values, edit in place |
| Orders + admin confirm/reject | **Completed** | Manual payment flow |
| Coupons | **Completed** | Admin create + validate API |
| Support tickets | **Completed** | User + admin |
| Notifications + broadcast | **Completed** | |
| Admin users/projects/plans | **Completed** | Force-stop projects |
| Appearance Light/Dark/OLED | **Completed** | localStorage |
| Cloudflare Tunnel | **Requires token** | `.env` CLOUDFLARE_TUNNEL_TOKEN |
| Google OAuth / real 2FA | **Requires credentials** | UI placeholders only |
| Automatic ACME SSL on bare metal | **Requires host config** | Use Cloudflare SSL or Caddy/Nginx |
| Full Docker isolation | **Partial** | Flag `DOCKER_ENABLED`; default = process isolation on shared hosts (e.g. Apsara) |
| Live WebSocket console | **Partial** | Fast polling (2s) while Console is open, colour-coded lines, pause button; real WebSocket not yet |
| GitHub OAuth App connect | **Not yet** | Deploy uses one-shot token |

## Security
- Path traversal blocked on all file APIs
- Auth required; ownership checks on every project route
- Admin routes use `require_admin`
- Git token never written to DB
- Secrets only via environment / `.env` (not committed)

## Environment (see `.env.example`)
- `PORT`, `SECRET_KEY`, `DATABASE_URL`
- `CLOUDFLARE_TUNNEL_TOKEN`, `CLOUDFLARE_TUNNEL_URL`
- `SERVER_IP`, `HOST_PREFIX`, `HOST_BASE` (display hostname)
- `DOCKER_ENABLED`

## Health
`GET /health` — process health check for orchestrators.

## License
Private / project use.

## UI v2 changelog (this update)

**Bug fixes**
- Restore backup crashed (`Backup` has no `file_path`) -> now uses the stored filename.
- Server page returned HTTP 500 once a plan was active (`expires_at` naive vs timezone-aware datetime). Same fix for coupon expiry.
- Page background was never applied (invalid `background` shorthand), so pages were white even in Dark mode.
- `.toggle` CSS was defined twice, which broke the "Server stats" collapse button; `.seg` also collided in the console.
- Settings -> Port field was ignored on Save (only the Startup port was sent).
- Start/Stop/Restart/Command showed "sent" even when the API returned `ok: false`; the real error is shown now.
- Domains / Deployments lists inserted raw HTML (XSS) -> escaped.
- `_safe_path` prefix check (`/proj` vs `/proj-evil`) replaced with a proper parent check.
- Admins could open any server page but most actions returned 404 -> admin-aware ownership checks.
- Language button "ខ្មែរ" was clipped in the top bar.

**New features**
- Real code editor modal for files (Ctrl+S, Tab, line/col, unsaved-changes guard) instead of `prompt()`.
- Modal dialogs for rename / create / confirm (no more browser `prompt()`/`confirm()`).
- File Manager: Move, drag & drop upload, upload progress bar, click a file to edit it.
- Backups: download + delete, "file missing" detection (`GET/DELETE /api/projects/{id}/backups`).
- Env vars: show/hide values, edit, no page reload (`GET /api/projects/{id}/env`).
- Server name can be renamed in Settings; delete service requires typing the server name.
- Servers page: search, status filter chips, live CPU/RAM/disk refresh, quick Start/Restart/Stop (`GET /api/dashboard/live`).
- Usage meters (CPU / RAM / Disk) with warning colours.
- Upload limits: `MAX_UPLOAD_MB` and plan storage quota are enforced.
- Khmer translations for the whole server panel, dialogs and toasts.
- Dark / OLED theme completed (buttons, command bar, modals, editor).


## Hosting file structure

```
app.py                      main Hosting Manager
user_bots/
  user001/bot_1/            project files of hosting #1 of user001 (app.py, requirements.txt, .env ...)
  user001/bot_2/
  user002/bot_1/
data/
  user001/config.json       metadata of all hostings of user001 (id, name, status, pid, path, expiry ...)
        database.db         user data
        logs/bot_1.log      console log per hosting
        runtime/bot_1.json  pid / state per hosting
        backups/            ZIP backups
```
- User folders are `user{id:03d}`; hostings are `bot_N` (see `Project.folder`). Old installs are migrated automatically at startup.
- The browser never reads these folders; everything goes through the API (`/api/servers`, `/api/files`, `/api/console`, `/api/backups`, ...). Every request is checked against the logged-in user and paths are sandboxed (`_safe_path`).
- Each hosting is its own process group; starting/restarting one never touches another.
- Hosting processes receive `ANAJAK_DATA_DIR` (their owner's data folder) and `ANAJAK_PROJECT_DIR`.
