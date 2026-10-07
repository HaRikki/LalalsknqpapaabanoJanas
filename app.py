"""
Anajak Host - Universal Hosting Control Panel
Entry point: python app.py
  or: uvicorn app:app --host 0.0.0.0 --port 15794

"""
from __future__ import annotations

import os
import json
import uuid

import asyncio
import re
import shutil
import zipfile
import tarfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Request, Depends, HTTPException, Form, UploadFile, File, status
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import select, func, desc
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from core.config import (
    BASE_DIR, SECRET_KEY, DEBUG, ADMIN_EMAIL, ADMIN_PASSWORD,
    USER_BOTS_DIR, DATA_DIR, LEGACY_PROJECTS_DIR, LEGACY_LOGS_DIR, LEGACY_BACKUPS_DIR, APP_URL, PORT,
    CLOUDFLARE_TUNNEL_ENABLED, CLOUDFLARE_TUNNEL_TOKEN,
    CLOUDFLARE_TUNNEL_URL, SERVER_IP, HOST_PREFIX, HOST_BASE,
    TURNSTILE_SITE_KEY, TURNSTILE_SECRET_KEY, HUMAN_VERIFY_ENABLED,
    HUMAN_COOKIE_NAME, HUMAN_COOKIE_HOURS,
)
from core.database import init_db, get_db, AsyncSessionLocal
from core.models import (
    User, HostingPlan, Project, Order, SupportTicket, TicketMessage,
    Notification, GameTemplate, AuditLog, Backup,
    Coupon, LoginHistory, DomainRecord, Deployment, SystemSetting, BlockedIP, UserSession, WebhookEndpoint,
)
from core.auth import (
    hash_password, verify_password, create_access_token,
    get_current_user, get_current_user_optional, require_admin,
)
from core.process_manager import process_manager
from contextlib import asynccontextmanager

# FastAPI app is created after lifespan is defined below
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
MAX_UPLOAD_BYTES = int(os.getenv("MAX_UPLOAD_MB", "200")) * 1024 * 1024


# ─── Panel helpers (server cards / usage) ─────────────────
def _mib(v, trim=False):
    if v is None:
        return "—"
    v = float(v); unit = "MiB"
    if v >= 1024:
        v /= 1024; unit = "GiB"
    t = f"{v:.2f}"
    if trim:
        t = t.rstrip("0").rstrip(".")
    return f"{t} {unit}"


def _uptime(sec):
    sec = int(sec or 0)
    d, r = divmod(sec, 86400); h, r = divmod(r, 3600); m = r // 60
    return f"{d}d {h}h {m}m"


templates.env.filters["mib"] = _mib
def _ago(dt):
    if not dt:
        return "—"
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    s = int((datetime.utcnow() - dt).total_seconds())
    for n, unit in ((86400, "day"), (3600, "hour"), (60, "minute")):
        if s >= n:
            c = s // n
            return f"{c} {unit}{'' if c == 1 else 's'} ago"
    return "just now"


templates.env.filters["uptime"] = _uptime
templates.env.filters["ago"] = _ago


def _dir_bytes(path) -> int:
    total = 0
    try:
        for f in Path(path).rglob("*"):
            try:
                if f.is_file() and not f.is_symlink():
                    total += f.stat().st_size
            except OSError:
                pass
    except OSError:
        pass
    return total



def _detect_server_ip() -> str:
    """Best-effort public/server IP for display."""
    if SERVER_IP:
        return SERVER_IP
    import socket
    # try env common on PaaS
    for key in ("PUBLIC_IP", "SERVER_ADDR", "HOST_IP"):
        v = os.getenv(key, "").strip()
        if v:
            return v
    try:
        # outbound UDP trick — no packets sent
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        if ip and not ip.startswith("127."):
            return ip
    except Exception:
        pass
    try:
        return socket.gethostbyname(socket.gethostname())
    except Exception:
        return "127.0.0.1"


def _short_name(domain: str | None, slug: str | None = None) -> str:
    """angker-smm.ndclub.top → angker  (first label, then first hyphen segment)."""
    src = (domain or slug or "server").strip().lower()
    # strip scheme if any
    src = src.replace("https://", "").replace("http://", "").split("/")[0]
    label = src.split(".")[0]  # angker-smm
    short = label.split("-")[0]  # angker
    short = re.sub(r"[^a-z0-9]", "", short) or "server"
    return short[:32]


def _display_host(domain: str | None, port: int | None, slug: str | None = None) -> str:
    """Build us.angker.lol:15517 style display hostname."""
    short = _short_name(domain, slug)
    host = f"{HOST_PREFIX}.{short}.{HOST_BASE}"
    if port:
        host = f"{host}:{port}"
    return host


def _host_info(p, request_hostname: str | None = None) -> dict:
    ip = _detect_server_ip()
    port = p.port or PORT
    nice = _display_host(p.domain, port, p.slug)
    # Hostname row like Apsara: IP:port
    hostname_ip = f"{ip}:{port}" if port else ip
    public = p.domain or nice
    return {
        "server_ip": ip,
        "hostname": hostname_ip,       # 51.81.90.228:15517
        "display_host": nice,          # us.angker.lol:15517
        "public_domain": p.domain or "",
        "port": port,
        "short_name": _short_name(p.domain, p.slug),
    }


def _srv_info(p) -> dict:
    st = process_manager.status(p.id)
    m = process_manager.metrics(p.id)
    s = st.get("status", "stopped")
    tag, label = {"running": ("ok", "Running"), "stopped": ("off", "Offline")}.get(s, ("warn", str(s).title()))
    cmd = (p.start_command or "").strip().lower()
    rtc = next((k for k in ("python", "node", "java", "bun") if cmd.startswith(k)), "other")
    rt = {"python": "python", "node": "node.js", "java": "java", "bun": "bun"}.get(rtc, (p.project_type or "cloud").replace("_", " "))
    return {
        "status": s, "tag": tag, "label": label,
        "cpu": m.get("cpu_percent"), "ram": m.get("ram_mb"),
        "disk_mb": _dir_bytes(process_manager.project_dir(p.user_id, p.folder)) / 1048576,
        "uptime": st.get("uptime_sec", 0), "rtc": rtc, "rt": rt,
    }



# ─── Hosting layout helpers ────────────────────────────────

def _backup_file(user_id: int, filename: str) -> Path:
    """data/userNNN/backups/<file>; falls back to the old flat backups/ dir for old backups."""
    name = Path(filename).name
    new = process_manager.backup_dir(user_id) / name
    old = LEGACY_BACKUPS_DIR / name
    return new if (new.exists() or not old.exists()) else old


def _next_folder(existing: list[str | None]) -> str:
    nums = [int(m.group(1)) for f in existing if f and (m := re.fullmatch(r"bot_(\d+)", f))]
    return f"bot_{(max(nums) + 1) if nums else 1}"


async def sync_user_meta(db: AsyncSession, user_id: int):
    """Write data/userNNN/config.json: metadata of every hosting of this user."""
    rows = (await db.execute(select(Project).where(Project.user_id == user_id).order_by(Project.id))).scalars().all()
    hostings = []
    for p in rows:
        st = process_manager.status(p.id)
        hostings.append({
            "id": p.id, "name": p.name, "folder": p.folder, "status": st.get("status", p.status),
            "runtime": p.project_type, "start_command": p.start_command, "pid": st.get("pid"),
            "path": f"user_bots/{process_manager.user_code(user_id)}/{p.folder}",
            "cpu": p.cpu, "ram_mb": p.ram_mb, "storage_gb": p.storage_gb, "port": p.port,
            "created_at": p.created_at.isoformat() if p.created_at else None,
            "expires_at": p.expires_at.isoformat() if p.expires_at else None,
        })
    try:
        d = process_manager.user_data_dir(user_id)
        (d / "config.json").write_text(json.dumps({"user": process_manager.user_code(user_id), "hostings": hostings}, indent=2))
    except OSError:
        pass


async def migrate_layout():
    """One-time: give old projects a bot_N folder and move their files/logs to the new layout."""
    async with AsyncSessionLocal() as db:
        projects = (await db.execute(select(Project).order_by(Project.id))).scalars().all()
        by_user: dict[int, list[Project]] = {}
        for p in projects:
            by_user.setdefault(p.user_id, []).append(p)
        for uid, plist in by_user.items():
            for p in plist:
                if p.folder:
                    continue
                p.folder = _next_folder([x.folder for x in plist])
                old_dir = LEGACY_PROJECTS_DIR / f"user{uid}" / p.slug
                new_dir = USER_BOTS_DIR / process_manager.user_code(uid) / p.folder
                if old_dir.is_dir() and not new_dir.exists():
                    new_dir.parent.mkdir(parents=True, exist_ok=True)
                    shutil.move(str(old_dir), str(new_dir))
                old_log = LEGACY_LOGS_DIR / f"user{uid}" / p.slug / "app.log"
                if old_log.is_file():
                    shutil.move(str(old_log), str(process_manager.log_path(uid, p.folder)))
                process_manager.project_dir(uid, p.folder)
            await db.flush()
        await db.commit()
        for uid in by_user:
            await sync_user_meta(db, uid)


# ─── Helpers ───────────────────────────────────────────────

def utcnow():
    return datetime.now(timezone.utc)


def _aware(dt):
    """SQLite returns naive datetimes; treat them as UTC so they can be compared with utcnow()."""
    if dt is not None and dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


async def audit(db: AsyncSession, user_id: int | None, action: str, detail: str = ""):
    db.add(AuditLog(user_id=user_id, action=action, detail=detail))
    await db.commit()


async def notify(db: AsyncSession, user_id: int, title: str, body: str):
    db.add(Notification(user_id=user_id, title=title, body=body))
    await db.commit()


def safe_slug(name: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9_-]", "-", name.strip().lower())
    return s[:80] or "project"


async def seed_data():
    async with AsyncSessionLocal() as db:
        # Admin
        r = await db.execute(select(User).where(User.email == ADMIN_EMAIL))
        if not r.scalar_one_or_none():
            admin = User(
                email=ADMIN_EMAIL,
                username="admin",
                hashed_password=hash_password(ADMIN_PASSWORD),
                full_name="Administrator",
                role="admin",
            )
            db.add(admin)

        # Plans
        plans = [
            ("Basic", "basic", 512, 1.0, 5, 1, 0.50, "Starter resources"),
            ("Starter", "starter", 1024, 1.0, 10, 3, 1.50, "Good for bots"),
            ("Pro", "pro", 2048, 2.0, 25, 10, 4.00, "Websites & APIs"),
            ("Advanced", "advanced", 4096, 4.0, 50, 20, 8.00, "Heavy workloads"),
        ]
        for name, slug, ram, cpu, storage, max_h, price, desc in plans:
            r = await db.execute(select(HostingPlan).where(HostingPlan.slug == slug))
            if not r.scalar_one_or_none():
                db.add(HostingPlan(
                    name=name, slug=slug, ram_mb=ram, cpu=cpu,
                    storage_gb=storage, max_hostings=max_h,
                    price_monthly=price, description=desc,
                ))

        # Game templates
        games = [
            ("Minecraft Java", "minecraft", "itzg/minecraft-server", 25565, 2048, 2.0, 10),
            ("Custom Game", "custom-game", None, 25565, 1024, 1.0, 5),
        ]
        for name, slug, img, port, ram, cpu, storage in games:
            r = await db.execute(select(GameTemplate).where(GameTemplate.slug == slug))
            if not r.scalar_one_or_none():
                db.add(GameTemplate(
                    name=name, slug=slug, docker_image=img,
                    default_port=port, ram_mb=ram, cpu=cpu, storage_gb=storage,
                ))
        await db.commit()


_tunnel_proc: asyncio.subprocess.Process | None = None
_tunnel_task: asyncio.Task | None = None


async def _spawn_tunnel(script: Path, env: dict):
    # run through bash so a missing exec bit never blocks it; stdout/stderr go to the panel Console
    return await asyncio.create_subprocess_exec(
        "bash", str(script), cwd=str(BASE_DIR), env=env, stdout=None, stderr=None,
    )


async def _tunnel_watchdog(script: Path, env: dict):
    """Keep cloudflared alive: a dead tunnel is what causes Cloudflare Error 1033."""
    global _tunnel_proc
    delay = 5
    while True:
        started = asyncio.get_event_loop().time()
        code = await _tunnel_proc.wait()
        if asyncio.get_event_loop().time() - started > 60:
            delay = 5
        print(f"[tunnel] cloudflared exited (code {code}) - restarting in {delay}s", flush=True)
        await asyncio.sleep(delay)
        delay = min(delay * 2, 60)
        try:
            _tunnel_proc = await _spawn_tunnel(script, env)
            print(f"[tunnel] cloudflared restarted pid={_tunnel_proc.pid}", flush=True)
        except Exception as e:
            print(f"[tunnel] restart failed: {e}", flush=True)
            await asyncio.sleep(delay)


async def _start_cloudflare_tunnel():
    """Launch scripts/cloudflare_tunnel.sh when enabled (token in .env or panel variables)."""
    global _tunnel_proc, _tunnel_task
    if not CLOUDFLARE_TUNNEL_ENABLED:
        print("[tunnel] disabled - set CLOUDFLARE_TUNNEL_TOKEN (in .env or the panel Startup variables) to enable", flush=True)
        return
    script = BASE_DIR / "scripts" / "cloudflare_tunnel.sh"
    if not script.exists():
        print("[tunnel] scripts/cloudflare_tunnel.sh not found - skip", flush=True)
        return
    mode = "token" if CLOUDFLARE_TUNNEL_TOKEN else "quick (no token)"
    print(f"[tunnel] enabled, mode={mode}, target={CLOUDFLARE_TUNNEL_URL}", flush=True)
    env = {**dict(__import__("os").environ), "CLOUDFLARE_TUNNEL_URL": CLOUDFLARE_TUNNEL_URL}
    if CLOUDFLARE_TUNNEL_TOKEN:
        env["CLOUDFLARE_TUNNEL_TOKEN"] = CLOUDFLARE_TUNNEL_TOKEN
    try:
        _tunnel_proc = await _spawn_tunnel(script, env)
        print(f"[tunnel] cloudflared launching pid={_tunnel_proc.pid} - look for 'Registered tunnel connection' below", flush=True)
        _tunnel_task = asyncio.create_task(_tunnel_watchdog(script, env))
    except Exception as e:
        print(f"[tunnel] failed to start: {e}", flush=True)


@asynccontextmanager
async def lifespan(app_instance: FastAPI):
    global _tunnel_proc, _tunnel_task
    await init_db()
    await seed_data()
    await migrate_layout()
    async with AsyncSessionLocal() as db:
        r = await db.execute(select(Project).where(Project.auto_start == True))
        for p in r.scalars().all():
            if p.start_command:
                await process_manager.start(
                    p.id, p.user_id, p.slug, p.start_command, p.env_vars or {}, ram_mb=p.ram_mb, cpu=p.cpu
                )
                p.status = "running"
        await db.commit()
    asyncio.create_task(_monitor_loop())
    await _start_cloudflare_tunnel()
    yield
    if _tunnel_task:
        _tunnel_task.cancel()
        _tunnel_task = None
    if _tunnel_proc and _tunnel_proc.returncode is None:
        _tunnel_proc.terminate()
        try:
            await asyncio.wait_for(_tunnel_proc.wait(), timeout=5)
        except (asyncio.TimeoutError, ProcessLookupError):
            try:
                _tunnel_proc.kill()
            except ProcessLookupError:
                pass
    _tunnel_proc = None


app = FastAPI(title="Anajak Host", docs_url="/api/docs" if DEBUG else None, lifespan=lifespan)
from core.social import router as social_router, public_providers  # Google + Telegram login
app.include_router(social_router)
from core.payment import router as payment_router, aba_enabled, mark_order_paid, UNPAID  # ABA KHQR payments
app.include_router(payment_router)
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")

# ─── Human verification (Cloudflare Turnstile) ────────────
from core.human_verify import (
    is_enabled as human_verify_enabled,
    make_human_cookie_value,
    validate_human_cookie,
    rate_limit_ok,
    verify_turnstile_token,
    should_skip_path,
    request_has_human,
)


def _wants_html(request: Request) -> bool:
    accept = (request.headers.get("accept") or "").lower()
    if "application/json" in accept and "text/html" not in accept:
        return False
    # Browser navigation usually has text/html
    if "text/html" in accept or accept == "" or "*/*" in accept:
        # fetch() API often sends */* — treat non-API paths as HTML
        path = request.url.path or ""
        if path.startswith("/api/"):
            return False
        return True
    return False


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    """Browser: 401→login, 404→home/dashboard. API: keep JSON."""
    if _wants_html(request):
        if exc.status_code == 401:
            dest = "/login"
            path = request.url.path or "/"
            if path not in ("/login", "/register", "/"):
                from urllib.parse import quote
                dest = "/login?next=" + quote(path)
            resp = RedirectResponse(url=dest, status_code=302)
            resp.delete_cookie("access_token", path="/")
            return resp
        if exc.status_code == 404:
            # Avoid bare {"detail":"Not Found"} on phone browsers
            return RedirectResponse(url="/", status_code=302)
    detail = exc.detail
    if detail is None or detail == "":
        detail = "Not Found" if exc.status_code == 404 else "Error"
    return JSONResponse(status_code=exc.status_code, content={"detail": detail})


@app.middleware("http")
async def human_gate_middleware(request: Request, call_next):
    """Block page + API access until Turnstile verification cookie is present."""
    path = request.url.path or "/"
    # Always allow static / health / verify endpoints
    if should_skip_path(path):
        return await call_next(request)
    # If feature off or keys missing → pass through (dev-friendly)
    if not human_verify_enabled():
        return await call_next(request)
    if request_has_human(request):
        return await call_next(request)
    # API without cookie → 403 JSON (not HTML redirect)
    if path.startswith("/api/"):
        return JSONResponse(
            {"detail": "Human verification required", "verify_url": "/verify"},
            status_code=403,
        )
    # HTML pages → redirect to /verify?next=...
    next_url = path
    if request.url.query:
        next_url = path + "?" + request.url.query
    from urllib.parse import quote
    return RedirectResponse(url="/verify?next=" + quote(next_url, safe="/"), status_code=302)


@app.get("/verify", response_class=HTMLResponse)
async def verify_page(request: Request, next: str = "/"):
    # Already verified → go through
    if request_has_human(request) or not human_verify_enabled():
        dest = next if next.startswith("/") and not next.startswith("//") else "/"
        return RedirectResponse(dest, status_code=302)
    return templates.TemplateResponse("verify.html", {
        "request": request,
        "site_key": TURNSTILE_SITE_KEY,
        "next_url": next if next.startswith("/") and not next.startswith("//") else "/",
        "enabled": human_verify_enabled(),
    })


@app.post("/api/verify/turnstile")
async def api_verify_turnstile(request: Request):
    """Verify Turnstile token with Cloudflare; set signed human cookie on success."""
    client_ip = request.client.host if request.client else "0.0.0.0"
    if not rate_limit_ok(client_ip):
        raise HTTPException(429, "Too many attempts. Please wait a minute.")
    form = await request.form()
    next_url = str(form.get("next") or "/")
    if not human_verify_enabled():
        dest = next_url if next_url.startswith("/") and not next_url.startswith("//") else "/"
        resp = JSONResponse({"ok": True, "redirect": dest})
        resp.set_cookie(
            HUMAN_COOKIE_NAME, make_human_cookie_value(),
            httponly=True, max_age=HUMAN_COOKIE_HOURS * 3600,
            samesite="lax", secure=request.url.scheme == "https", path="/",
        )
        return resp
    token = str(form.get("cf-turnstile-response") or form.get("token") or "")
    ok, err = await verify_turnstile_token(token, remoteip=client_ip)
    if not ok:
        raise HTTPException(400, err or "Verification failed")
    dest = next_url if next_url.startswith("/") and not next_url.startswith("//") else "/"
    resp = JSONResponse({"ok": True, "redirect": dest})
    resp.set_cookie(
        HUMAN_COOKIE_NAME, make_human_cookie_value(),
        httponly=True, max_age=HUMAN_COOKIE_HOURS * 3600,
        samesite="lax", secure=request.url.scheme == "https", path="/",
    )
    return resp






async def _monitor_loop():
    """Auto-restart crashed projects."""
    while True:
        await asyncio.sleep(30)
        try:
            async with AsyncSessionLocal() as db:
                r = await db.execute(
                    select(Project).where(Project.auto_restart == True, Project.status == "running")
                )
                for p in r.scalars().all():
                    st = process_manager.status(p.id)
                    if st["status"] != "running":
                        if p.restart_count < p.max_restarts and p.start_command:
                            p.restart_count += 1
                            await process_manager.start(
                                p.id, p.user_id, p.slug, p.start_command, p.env_vars or {}
                            )
                            p.status = "running"
                        else:
                            p.status = "error"
                            await notify(db, p.user_id, "Project stopped", f"{p.name} crashed or exceeded restart limit.")
                await db.commit()
        except Exception:
            pass


# ─── Page routes ───────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def home(request: Request, user: Optional[User] = Depends(get_current_user_optional)):
    return templates.TemplateResponse("index.html", {"request": request, "user": user})


@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request, db: AsyncSession = Depends(get_db)):
    return templates.TemplateResponse("login.html", {
        "request": request, "error": None, "providers": await public_providers(request, db),
    })


@app.get("/register", response_class=HTMLResponse)
async def register_page(request: Request, db: AsyncSession = Depends(get_db)):
    return templates.TemplateResponse("register.html", {
        "request": request, "error": None, "providers": await public_providers(request, db),
    })


@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    r = await db.execute(select(Project).where(Project.user_id == user.id).order_by(desc(Project.created_at)))
    projects = r.scalars().all()
    unread = await db.execute(
        select(func.count()).select_from(Notification).where(
            Notification.user_id == user.id, Notification.is_read == False
        )
    )
    return templates.TemplateResponse("dashboard.html", {
        "request": request, "user": user, "projects": projects,
        "unread": unread.scalar() or 0,
        "info": {p.id: _srv_info(p) for p in projects},
        "host_map": {p.id: _host_info(p, request.url.hostname) for p in projects},
        "server_ip": _detect_server_ip(),
    })


@app.get("/create", response_class=HTMLResponse)
async def create_page(request: Request, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    plans = (await db.execute(select(HostingPlan).where(HostingPlan.is_active == True))).scalars().all()
    if user.role != "admin":
        plans = [pl for pl in plans if float(pl.price_monthly or 0) > 0]
    games = (await db.execute(select(GameTemplate).where(GameTemplate.is_active == True))).scalars().all()
    return templates.TemplateResponse("create.html", {
        "request": request, "user": user, "plans": plans, "games": games,
        "aba_enabled": await aba_enabled(db),
    })


@app.get("/project/{project_id}", response_class=HTMLResponse)
async def project_page(project_id: int, request: Request, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    p = await db.get(Project, project_id)
    if not p or (p.user_id != user.id and user.role != "admin"):
        return RedirectResponse("/dashboard?msg=project_not_found", status_code=302)
    st = process_manager.status(p.id)
    metrics = process_manager.metrics(p.id)
    logs = process_manager.read_logs(p.user_id, p.folder)
    backups = (await db.execute(select(Backup).where(Backup.project_id == p.id).order_by(desc(Backup.created_at)))).scalars().all()
    plan = await db.get(HostingPlan, p.plan_id) if p.plan_id else None
    if p.expires_at:
        days = (_aware(p.expires_at) - utcnow()).days
        expires_in = f"in {days} days" if days >= 0 else "expired"
        expires_at_fmt = _aware(p.expires_at).strftime("%Y-%m-%d %H:%M")
    else:
        expires_in = "—"
        expires_at_fmt = "—"
    starts_at_fmt = _aware(p.created_at).strftime("%Y-%m-%d %H:%M") if p.created_at else "—"
    return templates.TemplateResponse("project.html", {
        "request": request, "user": user, "project": p,
        "status": st, "metrics": metrics, "logs": logs, "backups": backups,
        "info": _srv_info(p), "plan": plan, "expires_in": expires_in,
        "expires_at_fmt": expires_at_fmt, "starts_at_fmt": starts_at_fmt,
        "host_info": _host_info(p, request.url.hostname),
    })


@app.get("/billing", response_class=HTMLResponse)
async def billing_page(request: Request, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    plans = (await db.execute(select(HostingPlan).where(HostingPlan.is_active == True))).scalars().all()
    orders = (await db.execute(select(Order).where(Order.user_id == user.id).order_by(desc(Order.created_at)))).scalars().all()
    projects = (await db.execute(select(Project).where(Project.user_id == user.id))).scalars().all()
    return templates.TemplateResponse("billing.html", {
        "request": request, "user": user, "plans": plans, "orders": orders, "projects": projects,
        "aba_enabled": await aba_enabled(db),
    })


@app.get("/support", response_class=HTMLResponse)
async def support_page(request: Request, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    tickets = (await db.execute(
        select(SupportTicket).where(SupportTicket.user_id == user.id).order_by(desc(SupportTicket.updated_at))
    )).scalars().all()
    return templates.TemplateResponse("support.html", {"request": request, "user": user, "tickets": tickets})


@app.get("/support/{ticket_id}", response_class=HTMLResponse)
async def support_detail(ticket_id: int, request: Request, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    t = await db.get(SupportTicket, ticket_id, options=[selectinload(SupportTicket.messages)])
    if not t or (t.user_id != user.id and user.role != "admin"):
        raise HTTPException(404)
    return templates.TemplateResponse("support_detail.html", {"request": request, "user": user, "ticket": t})


@app.get("/notifications", response_class=HTMLResponse)
async def notifications_page(request: Request, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    notes = (await db.execute(
        select(Notification).where(Notification.user_id == user.id).order_by(desc(Notification.created_at))
    )).scalars().all()
    return templates.TemplateResponse("notifications.html", {"request": request, "user": user, "notes": notes})


@app.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return templates.TemplateResponse("settings.html", {
        "request": request, "user": user, "msg": None,
        "providers": await public_providers(request, db, link=True),
    })


@app.get("/admin", response_class=HTMLResponse)
async def admin_page(request: Request, user: User = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    now = datetime.now(timezone.utc)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    async def cnt(q):
        return (await db.execute(q)).scalar() or 0

    users_total = await cnt(select(func.count()).select_from(User))
    users_active = await cnt(select(func.count()).select_from(User).where(User.is_suspended == False, User.is_active == True))
    users_suspended = await cnt(select(func.count()).select_from(User).where(User.is_suspended == True))
    projects_total = await cnt(select(func.count()).select_from(Project))
    projects_running = await cnt(select(func.count()).select_from(Project).where(Project.status == "running"))
    projects_stopped = await cnt(select(func.count()).select_from(Project).where(Project.status == "stopped"))
    projects_error = await cnt(select(func.count()).select_from(Project).where(Project.status == "error"))
    projects_expired = await cnt(select(func.count()).select_from(Project).where(Project.expires_at != None, Project.expires_at < now))
    revenue_total = (await db.execute(select(func.coalesce(func.sum(Order.amount), 0)).where(Order.status == "paid"))).scalar() or 0
    revenue_today = (await db.execute(select(func.coalesce(func.sum(Order.amount), 0)).where(Order.status == "paid", Order.paid_at >= today_start))).scalar() or 0
    revenue_month = (await db.execute(select(func.coalesce(func.sum(Order.amount), 0)).where(Order.status == "paid", Order.paid_at >= month_start))).scalar() or 0
    orders_pending = await cnt(select(func.count()).select_from(Order).where(Order.status.in_(["pending", "awaiting_confirm"])))
    orders_paid = await cnt(select(func.count()).select_from(Order).where(Order.status == "paid"))
    orders_failed = await cnt(select(func.count()).select_from(Order).where(Order.status.in_(["failed", "cancelled"])))
    domains_total = await cnt(select(func.count()).select_from(DomainRecord))
    domains_active = await cnt(select(func.count()).select_from(DomainRecord).where(DomainRecord.status == "active"))

    stats = {
        "users": users_total,
        "users_active": users_active,
        "users_suspended": users_suspended,
        "projects": projects_total,
        "running": projects_running,
        "stopped": projects_stopped,
        "error": projects_error,
        "expired": projects_expired,
        "revenue_total": float(revenue_total),
        "revenue_today": float(revenue_today),
        "revenue_month": float(revenue_month),
        "pending_orders": orders_pending,
        "orders_paid": orders_paid,
        "orders_failed": orders_failed,
        "domains": domains_total,
        "domains_active": domains_active,
    }
    users = (await db.execute(select(User).order_by(desc(User.created_at)).limit(100))).scalars().all()
    projects = (await db.execute(select(Project).order_by(desc(Project.created_at)).limit(100))).scalars().all()
    orders = (await db.execute(select(Order).order_by(desc(Order.created_at)).limit(100))).scalars().all()
    plans = (await db.execute(select(HostingPlan))).scalars().all()
    games = (await db.execute(select(GameTemplate))).scalars().all()
    tickets = (await db.execute(select(SupportTicket).order_by(desc(SupportTicket.updated_at)).limit(50))).scalars().all()
    audits = (await db.execute(select(AuditLog).order_by(desc(AuditLog.created_at)).limit(100))).scalars().all()
    logins = (await db.execute(
        select(LoginHistory, User.email).join(User, User.id == LoginHistory.user_id)
        .order_by(desc(LoginHistory.created_at)).limit(50)
    )).all()
    domains = (await db.execute(select(DomainRecord).order_by(desc(DomainRecord.created_at)).limit(50))).scalars().all()
    deployments = (await db.execute(select(Deployment).order_by(desc(Deployment.created_at)).limit(50))).scalars().all()
    backups = (await db.execute(select(Backup).order_by(desc(Backup.created_at)).limit(50))).scalars().all()
    coupons = (await db.execute(select(Coupon).order_by(desc(Coupon.created_at)).limit(50))).scalars().all()

    # Recent activity from audit + recent users/orders/projects
    activity = []
    for a in audits[:20]:
        activity.append({"type": "audit", "action": a.action, "detail": a.detail or "", "time": a.created_at, "user_id": a.user_id})
    recent_users = (await db.execute(select(User).order_by(desc(User.created_at)).limit(5))).scalars().all()
    for u in recent_users:
        activity.append({"type": "user_register", "action": "User registered", "detail": u.email, "time": u.created_at, "user_id": u.id})
    recent_orders = (await db.execute(select(Order).order_by(desc(Order.created_at)).limit(5))).scalars().all()
    for o in recent_orders:
        activity.append({"type": "order", "action": f"Order #{o.id} {o.status}", "detail": f"${o.amount}", "time": o.created_at, "user_id": o.user_id})
    activity.sort(key=lambda x: x["time"] or now, reverse=True)
    activity = activity[:25]

    return templates.TemplateResponse("admin.html", {
        "request": request, "user": user, "stats": stats,
        "users": users, "projects": projects, "orders": orders,
        "plans": plans, "games": games, "tickets": tickets, "audits": audits, "logins": logins,
        "domains": domains, "deployments": deployments, "backups": backups, "coupons": coupons,
        "activity": activity,
    })


# ─── Auth API ──────────────────────────────────────────────

@app.post("/api/auth/register")
async def api_register(
    email: str = Form(...), username: str = Form(...), password: str = Form(...),
    full_name: str = Form(""), db: AsyncSession = Depends(get_db),
):
    if len(password) < 6:
        raise HTTPException(400, "Password min 6 characters")
    if email.strip().lower().endswith("@telegram.local"):
        raise HTTPException(400, "This email domain is reserved")
    exists = await db.execute(select(User).where((User.email == email) | (User.username == username)))
    if exists.scalar_one_or_none():
        raise HTTPException(400, "Email or username already exists")
    user = User(
        email=email.strip().lower(),
        username=username.strip(),
        hashed_password=hash_password(password),
        full_name=full_name or username,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    token, jti, exp = create_access_token({"sub": str(user.id)})
    db.add(UserSession(user_id=user.id, jti=jti, expires_at=exp))
    await db.commit()
    resp = JSONResponse({"ok": True, "token": token})
    resp.set_cookie("access_token", token, httponly=True, max_age=60 * 60 * 24 * 7, samesite="lax")
    return resp


@app.post("/api/auth/login")
async def api_login(
    request: Request,
    email: str = Form(...), password: str = Form(...),
    db: AsyncSession = Depends(get_db),
):
    r = await db.execute(select(User).where(User.email == email.strip().lower()))
    user = r.scalar_one_or_none()
    client_ip = request.client.host if request.client else None
    ua = request.headers.get("user-agent", "")[:300]
    if not user or not verify_password(password, user.hashed_password):
        if user:
            db.add(LoginHistory(user_id=user.id, ip=client_ip, user_agent=ua, success=False, method="password"))
            await db.commit()
        raise HTTPException(401, "Invalid email or password")
    if user.is_suspended:
        raise HTTPException(403, "Account suspended")
    # Blocked IP check
    if client_ip:
        blocked = (await db.execute(select(BlockedIP).where(BlockedIP.ip == client_ip))).scalar_one_or_none()
        if blocked:
            raise HTTPException(403, "IP blocked")
    db.add(LoginHistory(user_id=user.id, ip=client_ip, user_agent=ua, success=True, method="password"))
    token, jti, exp = create_access_token({"sub": str(user.id)})
    db.add(UserSession(user_id=user.id, jti=jti, ip=client_ip, user_agent=ua, expires_at=exp))
    await db.commit()
    await audit(db, user.id, "login")
    resp = JSONResponse({"ok": True, "token": token, "role": user.role})
    resp.set_cookie("access_token", token, httponly=True, max_age=60 * 60 * 24 * 7, samesite="lax")
    return resp


@app.post("/api/auth/logout")
async def api_logout():
    resp = JSONResponse({"ok": True})
    resp.delete_cookie("access_token")
    return resp


@app.post("/api/settings/password")
async def change_password(
    new_password: str = Form(...), current: str = Form(""),
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    # Accounts created with Google/Telegram have no known password yet, so they may set one directly.
    social_only = (user.auth_provider or "password") != "password"
    if not social_only and not verify_password(current, user.hashed_password):
        raise HTTPException(400, "Current password wrong")
    if len(new_password) < 6:
        raise HTTPException(400, "New password min 6 characters")
    user.hashed_password = hash_password(new_password)
    user.auth_provider = "password"
    await db.commit()
    return {"ok": True}


@app.post("/api/settings/profile")
async def update_profile(
    full_name: str = Form(...),
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    user.full_name = full_name.strip()
    await db.commit()
    return {"ok": True}


# ─── Projects ──────────────────────────────────────────────

@app.post("/api/projects/create")
async def create_project(
    name: str = Form(...),
    project_type: str = Form(...),
    plan_id: int = Form(...),
    start_command: str = Form(""),
    port: int = Form(0),
    source_type: str = Form("upload"),
    source_url: str = Form(""),
    months: int = Form(1),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    plan = await db.get(HostingPlan, plan_id)
    if not plan or not plan.is_active:
        raise HTTPException(400, "Invalid plan")
    if months not in (1, 6, 12):
        raise HTTPException(400, "Invalid billing cycle")
    is_free = float(plan.price_monthly or 0) <= 0
    if is_free and user.role != "admin":
        raise HTTPException(403, "Free plan is for Admin only. Please choose a paid plan.")
    slug = safe_slug(name)
    # unique slug per user
    existing = await db.execute(
        select(Project).where(Project.user_id == user.id, Project.slug == slug)
    )
    if existing.scalar_one_or_none():
        slug = f"{slug}-{int(utcnow().timestamp()) % 10000}"

    folder = _next_folder((await db.execute(select(Project.folder).where(Project.user_id == user.id))).scalars().all())
    p = Project(
        user_id=user.id,
        name=name.strip(),
        slug=slug,
        folder=folder,
        project_type=project_type,
        plan_id=plan.id,
        ram_mb=plan.ram_mb,
        cpu=plan.cpu,
        storage_gb=plan.storage_gb,
        start_command=start_command.strip() or None,
        port=port or None,
        source_type=source_type,
        source_url=source_url.strip() or None,
        status="stopped",
        env_vars={},
    )
    db.add(p)
    await db.commit()
    await db.refresh(p)
    process_manager.project_dir(user.id, p.folder)
    await sync_user_meta(db, user.id)
    await audit(db, user.id, "create_project", f"{p.name} ({p.id})")
    # Admin free → activate immediately with period. Users on paid → always invoice + QR pay.
    order_id = None
    if user.role == "admin" and is_free:
        p.expires_at = (utcnow() + timedelta(days=365 * 10)).replace(tzinfo=None)  # long free for admin
        await db.commit()
    elif user.role == "admin" and not is_free:
        # Admin can skip payment and activate paid plan too
        p.expires_at = (utcnow() + timedelta(days=30 * max(1, months))).replace(tzinfo=None)
        await db.commit()
    else:
        # Regular user: must pay (QR if ABA on, else pending for admin confirm)
        amount = round(float(plan.price_monthly or 0) * months, 2)
        method = "aba" if await aba_enabled(db) else "manual"
        o = Order(
            user_id=user.id, plan_id=plan.id, project_id=p.id,
            amount=amount, months=months, status="pending", payment_method=method,
        )
        db.add(o)
        await db.commit()
        await db.refresh(o)
        order_id = o.id
    return {
        "ok": True, "id": p.id, "order_id": order_id,
        "need_payment": order_id is not None,
        "amount": round(float(plan.price_monthly or 0) * months, 2) if order_id else 0,
        "aba": await aba_enabled(db),
    }


async def _require_paid(db: AsyncSession, p: Project, user: User):
    """When online payment is on, a hosting with an unpaid invoice (and no active period) cannot be started."""
    if user.role == "admin" or not await aba_enabled(db):
        return
    active = p.expires_at is not None and _aware(p.expires_at) > utcnow()
    if active:
        return
    unpaid = (await db.execute(
        select(Order.id).where(Order.project_id == p.id, Order.status.in_(UNPAID)).limit(1)
    )).first()
    if unpaid:
        raise HTTPException(402, "Payment required. Please pay the invoice in Billing first.")


@app.post("/api/projects/{project_id}/start")
async def start_project(project_id: int, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    p = await db.get(Project, project_id)
    if not p or (p.user_id != user.id and user.role != "admin"):
        raise HTTPException(404)
    await _require_paid(db, p, user)
    root = process_manager.project_dir(p.user_id, p.folder)
    cmd = (p.start_command or "").strip()
    if not cmd:
        cmd = _detect_start_command(root) or ""
        if cmd:
            p.start_command = cmd
            await db.commit()
    if not cmd:
        # log and return clear error
        try:
            logp = process_manager.log_path(p.user_id, p.folder)
            with open(logp, "a", encoding="utf-8") as lf:
                files = ", ".join(sorted([x.name for x in root.iterdir()])[:30]) if root.exists() else "(missing dir)"
                lf.write(f"\n[anajak] START blocked: no start command. Files in project: {files}\n")
                lf.write("[anajak] Set Start Command in Settings (e.g. python bot.py) or Unarchive a project zip first.\n")
        except Exception:
            pass
        raise HTTPException(400, "No start command. Unarchive your code zip or set Start Command in Settings (e.g. python main.py)")
    result = await process_manager.start(p.id, p.user_id, p.folder, cmd, p.env_vars or {}, ram_mb=p.ram_mb, cpu=p.cpu)
    if result.get("ok"):
        p.status = "running"
        p.pid = result.get("pid")
        p.restart_count = 0
        await db.commit()
        await sync_user_meta(db, p.user_id)
    else:
        # ensure error visible in logs
        try:
            logp = process_manager.log_path(p.user_id, p.folder)
            with open(logp, "a", encoding="utf-8") as lf:
                lf.write(f"[anajak] start API error: {result.get('error')}\n")
        except Exception:
            pass
    return result


@app.post("/api/projects/{project_id}/stop")
async def stop_project(project_id: int, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    p = await db.get(Project, project_id)
    if not p or (p.user_id != user.id and user.role != "admin"):
        raise HTTPException(404)
    result = await process_manager.stop(p.id)
    p.status = "stopped"
    p.pid = None
    await db.commit()
    await sync_user_meta(db, p.user_id)
    return result


@app.post("/api/projects/{project_id}/restart")
async def restart_project(project_id: int, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    p = await db.get(Project, project_id)
    if not p or (p.user_id != user.id and user.role != "admin"):
        raise HTTPException(404)
    if not p.start_command:
        raise HTTPException(400, "No start command")
    await _require_paid(db, p, user)
    result = await process_manager.restart(p.id, p.user_id, p.folder, p.start_command, p.env_vars or {}, ram_mb=p.ram_mb, cpu=p.cpu)
    if result.get("ok"):
        p.status = "running"
        p.pid = result.get("pid")
        await db.commit()
        await sync_user_meta(db, p.user_id)
    return result


@app.get("/api/projects/{project_id}/logs")
async def get_logs(project_id: int, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    p = await db.get(Project, project_id)
    if not p or (p.user_id != user.id and user.role != "admin"):
        raise HTTPException(404)
    return {"logs": process_manager.read_logs(p.user_id, p.folder)}


@app.delete("/api/projects/{project_id}/logs")
async def clear_logs(project_id: int, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    p = await db.get(Project, project_id)
    if not p or (p.user_id != user.id and user.role != "admin"):
        raise HTTPException(404)
    process_manager.clear_logs(p.user_id, p.folder)
    return {"ok": True}


@app.post("/api/projects/{project_id}/command")
async def send_command(project_id: int, command: str = Form(...), user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    p = await db.get(Project, project_id)
    if not p or (p.user_id != user.id and user.role != "admin"):
        raise HTTPException(404)
    if len(command) > 500:
        raise HTTPException(400, "Command too long")
    result = await process_manager.send_command(p.id, command)
    if not result.get("ok"):
        raise HTTPException(400, result.get("error", "Failed"))
    await audit(db, user.id, "console_command", f"{p.name} ({p.id})")
    return result


@app.get("/api/projects/{project_id}/metrics")
async def get_metrics(project_id: int, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    p = await db.get(Project, project_id)
    if not p or (p.user_id != user.id and user.role != "admin"):
        raise HTTPException(404)
    m = dict(process_manager.metrics(p.id))
    m["disk_mb"] = round(_dir_bytes(process_manager.project_dir(p.user_id, p.folder)) / 1048576, 2)
    return m


@app.post("/api/projects/{project_id}/env")
async def set_env(
    project_id: int,
    key: str = Form(...),
    value: str = Form(...),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    p = await db.get(Project, project_id)
    if not p or (p.user_id != user.id and user.role != "admin"):
        raise HTTPException(404)
    env = dict(p.env_vars or {})
    env[key.strip()] = value
    p.env_vars = env
    await db.commit()
    return {"ok": True, "env": {k: ("***" if "token" in k.lower() or "key" in k.lower() or "secret" in k.lower() or "password" in k.lower() else v) for k, v in env.items()}}


@app.delete("/api/projects/{project_id}/env/{key}")
async def del_env(project_id: int, key: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    p = await db.get(Project, project_id)
    if not p or (p.user_id != user.id and user.role != "admin"):
        raise HTTPException(404)
    env = dict(p.env_vars or {})
    env.pop(key, None)
    p.env_vars = env
    await db.commit()
    return {"ok": True}


@app.post("/api/projects/{project_id}/settings")
async def project_settings(
    project_id: int,
    start_command: str = Form(""),
    port: int = Form(0),
    auto_start: bool = Form(False),
    auto_restart: bool = Form(True),
    domain: str = Form(""),
    name: str = Form(""),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    p = await db.get(Project, project_id)
    if not p or (p.user_id != user.id and user.role != "admin"):
        raise HTTPException(404)
    if name.strip():
        p.name = name.strip()[:100]
    p.start_command = start_command.strip() or p.start_command
    p.port = port or p.port
    p.auto_start = auto_start
    p.auto_restart = auto_restart
    p.domain = domain.strip() or None
    await db.commit()
    return {"ok": True}


@app.delete("/api/projects/{project_id}")
async def delete_project(project_id: int, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    p = await db.get(Project, project_id)
    if not p or (p.user_id != user.id and user.role != "admin"):
        raise HTTPException(404)
    await process_manager.stop(p.id)
    # remove files
    d = process_manager.project_dir(p.user_id, p.folder)
    if d.exists():
        shutil.rmtree(d, ignore_errors=True)
    shutil.rmtree(process_manager.user_data_dir(p.user_id) / "trash" / p.folder, ignore_errors=True)
    process_manager.log_path(p.user_id, p.folder).unlink(missing_ok=True)
    process_manager.runtime_path(p.user_id, p.folder).unlink(missing_ok=True)
    owner_id = p.user_id
    await db.delete(p)
    await db.commit()
    await sync_user_meta(db, owner_id)
    await audit(db, user.id, "delete_project", str(project_id))
    return {"ok": True}


# ─── File Manager (sandboxed) ──────────────────────────────

def _safe_path(base: Path, rel: str) -> Path:
    root = base.resolve()
    target = (base / rel).resolve()
    if target != root and root not in target.parents:
        raise HTTPException(400, "Path traversal denied")
    return target


@app.get("/api/projects/{project_id}/files")
async def list_files(project_id: int, path: str = "", user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    p = await db.get(Project, project_id)
    if not p or (p.user_id != user.id and user.role != "admin"):
        raise HTTPException(404)
    base = process_manager.project_dir(p.user_id, p.folder)
    target = _safe_path(base, path)
    if not target.exists():
        return {"path": path, "items": []}
    items = []
    for item in sorted(target.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower())):
        items.append({
            "name": item.name,
            "is_dir": item.is_dir(),
            "size": item.stat().st_size if item.is_file() else 0,
            "modified": datetime.fromtimestamp(item.stat().st_mtime).isoformat(),
            "is_archive": (not item.is_dir()) and _is_archive(item.name),
        })
    return {"path": path, "items": items}


def _is_archive(name: str) -> bool:
    n = name.lower()
    return n.endswith((".zip", ".tar", ".tar.gz", ".tgz", ".tar.bz2", ".tbz2"))


def _archive_stem(name: str) -> str:
    n = name
    lower = n.lower()
    for ext in (".tar.gz", ".tar.bz2", ".tgz", ".tbz2", ".zip", ".tar"):
        if lower.endswith(ext):
            return n[: -len(ext)]
    return Path(n).stem


def _extract_archive(archive_path: Path, dest_dir: Path, into_subfolder: bool = True) -> dict:
    """Extract zip/tar into dest_dir (Apsara-style).

    - into_subfolder=True (default): create folder named after archive, extract inside it
      (unless the archive already has a single top-level folder with the same name).
    - Zip-slip protected. Returns stats + folder path relative hint.
    """
    dest_dir.mkdir(parents=True, exist_ok=True)
    extracted = 0
    name = archive_path.name.lower()
    stem = _archive_stem(archive_path.name)
    # sanitize folder name
    stem = re.sub(r"[^\w.\- ]+", "_", stem).strip("._ ") or "extracted"
    out_dir = dest_dir

    # Peek top-level entries to avoid double-nesting (zip already has one root folder)
    top_dirs = set()
    top_files = 0
    members_zip = None
    members_tar = None

    if name.endswith(".zip"):
        try:
            zf = zipfile.ZipFile(archive_path, "r")
            members_zip = zf.infolist()
            for info in members_zip:
                member_name = info.filename.replace("\\", "/").lstrip("/")
                if not member_name or member_name.startswith("..") or "/../" in f"/{member_name}/":
                    continue
                parts = member_name.split("/")
                if len(parts) == 1 and not info.is_dir() and not member_name.endswith("/"):
                    top_files += 1
                elif parts[0]:
                    top_dirs.add(parts[0])
        except zipfile.BadZipFile:
            raise HTTPException(400, "Invalid ZIP file")
    elif name.endswith((".tar", ".tar.gz", ".tgz", ".tar.bz2", ".tbz2")):
        mode = "r"
        if name.endswith((".tar.gz", ".tgz")):
            mode = "r:gz"
        elif name.endswith((".tar.bz2", ".tbz2")):
            mode = "r:bz2"
        try:
            tf = tarfile.open(archive_path, mode)
            members_tar = tf.getmembers()
            for member in members_tar:
                member_name = member.name.replace("\\", "/").lstrip("/")
                if not member_name or member_name.startswith("..") or "/../" in f"/{member_name}/":
                    continue
                if member.issym() or member.islnk():
                    continue
                parts = member_name.split("/")
                if len(parts) == 1 and member.isfile():
                    top_files += 1
                elif parts[0]:
                    top_dirs.add(parts[0])
        except tarfile.TarError:
            raise HTTPException(400, "Invalid TAR file")
    else:
        raise HTTPException(400, "Unsupported archive type (use .zip / .tar / .tar.gz)")

    # Decide target folder (Apsara-like: always show a folder after unarchive when mixed files)
    folder_name = None
    if into_subfolder:
        if len(top_dirs) == 1 and top_files == 0:
            # archive already has single root folder — extract as-is into dest_dir
            folder_name = next(iter(top_dirs))
            out_dir = dest_dir
        else:
            folder_name = stem
            out_dir = dest_dir / stem
            # avoid overwrite collision
            if out_dir.exists() and any(out_dir.iterdir()):
                i = 2
                while (dest_dir / f"{stem}_{i}").exists():
                    i += 1
                folder_name = f"{stem}_{i}"
                out_dir = dest_dir / folder_name
            out_dir.mkdir(parents=True, exist_ok=True)

    if name.endswith(".zip"):
        try:
            with zipfile.ZipFile(archive_path, "r") as zf:
                for info in zf.infolist():
                    member_name = info.filename.replace("\\", "/").lstrip("/")
                    if not member_name or member_name.startswith("..") or "/../" in f"/{member_name}/":
                        continue
                    member = _safe_path(out_dir, member_name)
                    if info.is_dir() or member_name.endswith("/"):
                        member.mkdir(parents=True, exist_ok=True)
                    else:
                        member.parent.mkdir(parents=True, exist_ok=True)
                        with zf.open(info) as src, open(member, "wb") as out:
                            shutil.copyfileobj(src, out)
                        extracted += 1
        except zipfile.BadZipFile:
            raise HTTPException(400, "Invalid ZIP file")
    else:
        mode = "r"
        if name.endswith((".tar.gz", ".tgz")):
            mode = "r:gz"
        elif name.endswith((".tar.bz2", ".tbz2")):
            mode = "r:bz2"
        try:
            with tarfile.open(archive_path, mode) as tf:
                for member in tf.getmembers():
                    member_name = member.name.replace("\\", "/").lstrip("/")
                    if not member_name or member_name.startswith("..") or "/../" in f"/{member_name}/":
                        continue
                    if member.issym() or member.islnk():
                        continue
                    target = _safe_path(out_dir, member_name)
                    if member.isdir():
                        target.mkdir(parents=True, exist_ok=True)
                    elif member.isfile():
                        target.parent.mkdir(parents=True, exist_ok=True)
                        src = tf.extractfile(member)
                        if src is None:
                            continue
                        with src, open(target, "wb") as out:
                            shutil.copyfileobj(src, out)
                        extracted += 1
        except tarfile.TarError:
            raise HTTPException(400, "Invalid TAR file")

    return {
        "ok": True,
        "extracted": extracted,
        "archive": archive_path.name,
        "folder": folder_name,
    }


@app.post("/api/projects/{project_id}/files/upload")
async def upload_file(
    project_id: int,
    path: str = Form(""),
    file: UploadFile = File(...),
    extract: str = Form("true"),  # auto-extract archives by default
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    p = await db.get(Project, project_id)
    if not p or (p.user_id != user.id and user.role != "admin"):
        raise HTTPException(404)
    base = process_manager.project_dir(p.user_id, p.folder)
    target_dir = _safe_path(base, path)
    target_dir.mkdir(parents=True, exist_ok=True)
    filename = Path(file.filename or "upload.bin").name
    dest = target_dir / filename
    content = await file.read()
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, f"File too large (max {MAX_UPLOAD_BYTES // 1048576} MB per upload)")
    limit = (p.storage_gb or 0) * 1024 ** 3
    if limit and _dir_bytes(base) + len(content) > limit:
        raise HTTPException(400, "Storage limit reached for this plan")
    dest.write_bytes(content)

    auto_extract = str(extract).lower() in ("1", "true", "yes", "on")
    result = {"ok": True, "filename": filename, "extracted": False}

    if auto_extract and _is_archive(filename):
        stats = _extract_archive(dest, target_dir, into_subfolder=True)
        result["folder"] = stats.get("folder")
        result["extracted"] = True
        result["extracted_count"] = stats["extracted"]
        # keep the archive file so user can re-download or re-extract

    return result



def _promote_nested_root(project_root: Path, folder_name: str | None) -> dict:
    """If extract created / only contains one code folder, move its contents to project root (Apsara Move)."""
    if not folder_name:
        # detect single subdir with code
        subs = [p for p in project_root.iterdir() if p.is_dir() and not p.name.startswith(".")]
        files = [p for p in project_root.iterdir() if p.is_file() and not _is_archive(p.name)]
        if len(subs) == 1 and len(files) == 0:
            folder_name = subs[0].name
        else:
            return {"promoted": False}
    src = project_root / folder_name
    if not src.is_dir():
        return {"promoted": False}
    moved = 0
    for item in list(src.iterdir()):
        dest = project_root / item.name
        if dest.exists():
            if dest.is_dir() and item.is_dir():
                # merge shallow
                for sub in item.iterdir():
                    t = dest / sub.name
                    if not t.exists():
                        shutil.move(str(sub), str(t))
                        moved += 1
                try:
                    item.rmdir()
                except OSError:
                    pass
            continue
        shutil.move(str(item), str(dest))
        moved += 1
    try:
        if src.exists() and not any(src.iterdir()):
            src.rmdir()
    except OSError:
        pass
    return {"promoted": True, "from": folder_name, "moved": moved}


def _detect_start_command(work: Path) -> str | None:
    """Guess a start command from extracted files."""
    if (work / "bot.py").exists():
        return "python bot.py"
    if (work / "main.py").exists():
        return "python main.py"
    if (work / "app.py").exists():
        return "python app.py"
    if (work / "index.js").exists():
        return "node index.js"
    if (work / "package.json").exists():
        return "npm start"
    # one level nested
    for sub in work.iterdir():
        if sub.is_dir() and not sub.name.startswith("."):
            if (sub / "bot.py").exists():
                return f"python {sub.name}/bot.py"
            if (sub / "main.py").exists():
                return f"python {sub.name}/main.py"
            if (sub / "app.py").exists():
                return f"python {sub.name}/app.py"
    return None


@app.post("/api/projects/{project_id}/files/unarchive")
async def unarchive_file(
    project_id: int,
    path: str = Form(...),  # relative path to the archive file
    into_folder: str = Form("true"),
    promote: str = Form("true"),  # Apsara-style: move nested folder contents to current dir
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Extract archive in File Manager (Apsara-style → files ready to Start)."""
    p = await db.get(Project, project_id)
    if not p or (p.user_id != user.id and user.role != "admin"):
        raise HTTPException(404, "Not found")
    root = process_manager.project_dir(p.user_id, p.folder)
    archive = _safe_path(root, path)
    if not archive.is_file():
        raise HTTPException(404, "Archive not found")
    if not _is_archive(archive.name):
        raise HTTPException(400, "Not a supported archive (.zip / .tar / .tar.gz)")
    dest_dir = archive.parent
    into = str(into_folder).lower() in ("1", "true", "yes", "on")
    do_promote = str(promote).lower() in ("1", "true", "yes", "on")
    stats = _extract_archive(archive, dest_dir, into_subfolder=into)
    promo = {"promoted": False}
    if do_promote:
        # promote relative to dest_dir (usually project root or subfolder)
        promo = _promote_nested_root(dest_dir, stats.get("folder"))
        stats["promote"] = promo
    # write extract summary into project logs
    try:
        logp = process_manager.log_path(p.user_id, p.folder)
        with open(logp, "a", encoding="utf-8") as lf:
            lf.write(f"\n[anajak] Unarchive {archive.name}: extracted={stats.get('extracted')} folder={stats.get('folder')} promote={promo}\n")
    except Exception:
        pass
    # auto-fill start_command if empty
    if not (p.start_command or "").strip():
        cmd = _detect_start_command(root)
        if cmd:
            p.start_command = cmd
            await db.commit()
            stats["start_command"] = cmd
    await audit(db, user.id, "unarchive", f"project={project_id} file={path} folder={stats.get('folder')} promote={promo.get('promoted')}")
    return stats


@app.get("/api/projects/{project_id}/files/download")
async def download_file(
    project_id: int, path: str = "",
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    p = await db.get(Project, project_id)
    if not p or (p.user_id != user.id and user.role != "admin"):
        raise HTTPException(404)
    base = process_manager.project_dir(p.user_id, p.folder)
    target = _safe_path(base, path)
    if not target.exists() or not target.is_file():
        raise HTTPException(404, "File not found")
    return FileResponse(path=str(target), filename=target.name, media_type="application/octet-stream")


@app.post("/api/projects/{project_id}/files/mkdir")
async def mkdir_file(
    project_id: int, path: str = Form(""), name: str = Form(...),
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    p = await db.get(Project, project_id)
    if not p or (p.user_id != user.id and user.role != "admin"):
        raise HTTPException(404)
    base = process_manager.project_dir(p.user_id, p.folder)
    target = _safe_path(base, f"{path}/{name}".strip("/"))
    target.mkdir(parents=True, exist_ok=True)
    return {"ok": True}


@app.delete("/api/projects/{project_id}/files")
async def delete_file(
    project_id: int, path: str = "",
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    p = await db.get(Project, project_id)
    if not p or (p.user_id != user.id and user.role != "admin"):
        raise HTTPException(404)
    base = process_manager.project_dir(p.user_id, p.folder)
    target = _safe_path(base, path)
    if target == base:
        raise HTTPException(400, "Cannot delete project root")
    if target.is_dir():
        shutil.rmtree(target)
    elif target.exists():
        target.unlink()
    return {"ok": True}



# ─── Multi-delete + Trash ──────────────────────────────────
# "Move to trash" keeps files recoverable in data/userNNN/trash/<bot>/<id>/; "Permanently delete" removes them.

_TRASH_ID = re.compile(r"^[0-9a-f]{32}$")


def _trash_root(p: Project) -> Path:
    d = process_manager.user_data_dir(p.user_id) / "trash" / p.folder
    d.mkdir(parents=True, exist_ok=True)
    return d


def _json_list(raw: str, limit: int = 500) -> list[str]:
    try:
        v = json.loads(raw)
    except ValueError:
        raise HTTPException(400, "Invalid list")
    if not isinstance(v, list) or len(v) > limit or not all(isinstance(x, str) for x in v):
        raise HTTPException(400, "Invalid list")
    return v


@app.post("/api/projects/{project_id}/files/delete")
async def delete_files(
    project_id: int, paths: str = Form(...), mode: str = Form("trash"),
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    p = await _own_project(db, project_id, user)
    if mode not in ("trash", "permanent"):
        raise HTTPException(400, "Invalid mode")
    rels = _json_list(paths)
    base = process_manager.project_dir(p.user_id, p.folder)
    targets = []
    for rel in rels:  # validate everything first: either all paths are inside the project or nothing happens
        t = _safe_path(base, rel)
        if t == base.resolve():
            raise HTTPException(400, "Cannot delete the project root")
        targets.append((rel, t))
    done = 0
    for rel, t in targets:
        if not t.exists():
            continue
        if mode == "permanent":
            shutil.rmtree(t) if t.is_dir() else t.unlink()
        else:
            tid = uuid.uuid4().hex
            dest_dir = _trash_root(p) / tid
            dest_dir.mkdir(parents=True)
            is_dir = t.is_dir()
            size = _dir_bytes(t) if is_dir else t.stat().st_size
            shutil.move(str(t), str(dest_dir / t.name))
            (_trash_root(p) / f"{tid}.json").write_text(json.dumps({
                "id": tid, "name": t.name, "orig_path": rel.strip("/"), "is_dir": is_dir,
                "size": size, "deleted_at": utcnow().isoformat(),
            }))
        done += 1
    await audit(db, user.id, f"files_{mode}", f"project={p.id} count={done}")
    return {"ok": True, "deleted": done, "mode": mode}


@app.get("/api/projects/{project_id}/trash")
async def list_trash(project_id: int, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    p = await _own_project(db, project_id, user)
    items = []
    for f in _trash_root(p).glob("*.json"):
        try:
            m = json.loads(f.read_text())
        except (OSError, ValueError):
            continue
        if _TRASH_ID.match(str(m.get("id", ""))) and (_trash_root(p) / m["id"]).is_dir():
            items.append(m)
    items.sort(key=lambda m: m.get("deleted_at", ""), reverse=True)
    return {"items": items}


@app.post("/api/projects/{project_id}/trash/restore")
async def restore_trash(
    project_id: int, ids: str = Form(...),
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    p = await _own_project(db, project_id, user)
    base = process_manager.project_dir(p.user_id, p.folder)
    root = _trash_root(p)
    restored = 0
    for tid in _json_list(ids):
        if not _TRASH_ID.match(tid):
            continue
        meta_f = root / f"{tid}.json"
        try:
            m = json.loads(meta_f.read_text())
        except (OSError, ValueError):
            continue
        src = root / tid / Path(m["name"]).name
        if not src.exists():
            continue
        dest = _safe_path(base, m.get("orig_path") or m["name"])
        if dest.exists():
            dest = dest.with_name(f"{dest.stem} (restored){dest.suffix}")
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), str(dest))
        shutil.rmtree(root / tid, ignore_errors=True)
        meta_f.unlink(missing_ok=True)
        restored += 1
    return {"ok": True, "restored": restored}


@app.post("/api/projects/{project_id}/trash/purge")
async def purge_trash(
    project_id: int, ids: str = Form("[]"), all: str = Form("0"),
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    p = await _own_project(db, project_id, user)
    root = _trash_root(p)
    if all == "1":
        tids = [f.stem for f in root.glob("*.json")] + [d.name for d in root.iterdir() if d.is_dir()]
    else:
        tids = _json_list(ids)
    n = 0
    for tid in set(tids):
        if not _TRASH_ID.match(tid):
            continue
        shutil.rmtree(root / tid, ignore_errors=True)
        (root / f"{tid}.json").unlink(missing_ok=True)
        n += 1
    return {"ok": True, "purged": n}


@app.post("/api/projects/{project_id}/backup")
async def create_backup(project_id: int, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    p = await db.get(Project, project_id)
    if not p or (p.user_id != user.id and user.role != "admin"):
        raise HTTPException(404)
    base = process_manager.project_dir(p.user_id, p.folder)
    fname = f"backup_{p.folder}_{int(utcnow().timestamp())}.zip"
    out = process_manager.backup_dir(p.user_id) / fname
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in base.rglob("*"):
            if f.is_file():
                zf.write(f, f.relative_to(base))
    b = Backup(project_id=p.id, filename=fname, size_bytes=out.stat().st_size)
    db.add(b)
    await db.commit()
    return {"ok": True, "filename": fname, "size": b.size_bytes}


# ─── Billing ───────────────────────────────────────────────

@app.post("/api/orders/create")
async def create_order(
    plan_id: int = Form(...),
    project_id: int = Form(0),
    payment_method: str = Form("aba"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    plan = await db.get(HostingPlan, plan_id)
    if not plan:
        raise HTTPException(400, "Invalid plan")

    # Admin gets free instant
    if user.role == "admin":
        order = Order(
            user_id=user.id, plan_id=plan.id,
            project_id=project_id or None,
            amount=0, status="paid", payment_method="free_admin",
            paid_at=utcnow(),
        )
        db.add(order)
        if project_id:
            p = await db.get(Project, project_id)
            if p and p.user_id == user.id:
                p.plan_id = plan.id
                p.ram_mb = plan.ram_mb
                p.cpu = plan.cpu
                p.storage_gb = plan.storage_gb
                p.expires_at = utcnow() + timedelta(days=30)
        await db.commit()
        await notify(db, user.id, "Order completed", f"Admin free plan: {plan.name}")
        return {"ok": True, "status": "paid", "amount": 0}

    order = Order(
        user_id=user.id, plan_id=plan.id,
        project_id=project_id or None,
        amount=plan.price_monthly,
        status="awaiting_confirm",
        payment_method=payment_method,
    )
    db.add(order)
    await db.commit()
    await db.refresh(order)
    return {"ok": True, "status": "awaiting_confirm", "order_id": order.id, "amount": order.amount}


@app.post("/api/orders/{order_id}/cancel")
async def cancel_order(order_id: int, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    o = await db.get(Order, order_id)
    if not o or o.user_id != user.id:
        raise HTTPException(404)
    if o.status not in ("pending", "awaiting_confirm"):
        raise HTTPException(400, "Cannot cancel")
    o.status = "cancelled"
    await db.commit()
    return {"ok": True}


# ─── Support ───────────────────────────────────────────────

@app.post("/api/support/create")
async def create_ticket(
    subject: str = Form(...), message: str = Form(...),
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    t = SupportTicket(user_id=user.id, subject=subject.strip())
    db.add(t)
    await db.flush()
    db.add(TicketMessage(ticket_id=t.id, user_id=user.id, message=message.strip(), is_admin=False))
    await db.commit()
    return {"ok": True, "id": t.id}


@app.post("/api/support/{ticket_id}/reply")
async def reply_ticket(
    ticket_id: int, message: str = Form(...),
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    t = await db.get(SupportTicket, ticket_id)
    if not t or (t.user_id != user.id and user.role != "admin"):
        raise HTTPException(404)
    is_admin = user.role == "admin"
    db.add(TicketMessage(ticket_id=t.id, user_id=user.id, message=message.strip(), is_admin=is_admin))
    t.status = "answered" if is_admin else "open"
    t.updated_at = utcnow()
    await db.commit()
    if is_admin:
        await notify(db, t.user_id, "Support reply", f"Ticket: {t.subject}")
    return {"ok": True}


@app.post("/api/support/{ticket_id}/close")
async def close_ticket(ticket_id: int, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    t = await db.get(SupportTicket, ticket_id)
    if not t or (t.user_id != user.id and user.role != "admin"):
        raise HTTPException(404)
    t.status = "closed"
    await db.commit()
    return {"ok": True}


# ─── Notifications ─────────────────────────────────────────

@app.post("/api/notifications/read-all")
async def read_all_notifications(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    r = await db.execute(select(Notification).where(Notification.user_id == user.id, Notification.is_read == False))
    for n in r.scalars().all():
        n.is_read = True
    await db.commit()
    return {"ok": True}


@app.post("/api/notifications/{nid}/read")
async def read_notification(nid: int, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    n = await db.get(Notification, nid)
    if n and n.user_id == user.id:
        n.is_read = True
        await db.commit()
    return {"ok": True}


# ─── Admin API ─────────────────────────────────────────────

@app.post("/api/admin/orders/{order_id}/confirm")
async def admin_confirm_order(order_id: int, user: User = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    o = await db.get(Order, order_id)
    if not o:
        raise HTTPException(404)
    await mark_order_paid(db, o, user.id, "admin")
    await audit(db, user.id, "confirm_order", str(order_id))
    return {"ok": True}


@app.post("/api/admin/orders/{order_id}/reject")
async def admin_reject_order(order_id: int, user: User = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    o = await db.get(Order, order_id)
    if not o:
        raise HTTPException(404)
    o.status = "failed"
    await db.commit()
    await notify(db, o.user_id, "Payment rejected", f"Order #{o.id} was rejected.")
    return {"ok": True}


@app.post("/api/admin/users/{uid}/suspend")
async def admin_suspend(uid: int, user: User = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    u = await db.get(User, uid)
    if not u or u.role == "admin":
        raise HTTPException(400)
    u.is_suspended = True
    await db.commit()
    await audit(db, user.id, "suspend_user", str(uid))
    return {"ok": True}


@app.post("/api/admin/users/{uid}/activate")
async def admin_activate(uid: int, user: User = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    u = await db.get(User, uid)
    if not u:
        raise HTTPException(404)
    u.is_suspended = False
    u.is_active = True
    await db.commit()
    return {"ok": True}


@app.post("/api/admin/plans")
async def admin_create_plan(
    name: str = Form(...), slug: str = Form(...), ram_mb: int = Form(512),
    cpu: float = Form(1.0), storage_gb: int = Form(5), max_hostings: int = Form(1),
    price_monthly: float = Form(1.0), description: str = Form(""),
    user: User = Depends(require_admin), db: AsyncSession = Depends(get_db),
):
    db.add(HostingPlan(
        name=name, slug=slug, ram_mb=ram_mb, cpu=cpu, storage_gb=storage_gb,
        max_hostings=max_hostings, price_monthly=price_monthly, description=description or None,
    ))
    await db.commit()
    return {"ok": True}


@app.post("/api/admin/plans/{pid}/toggle")
async def admin_toggle_plan(pid: int, user: User = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    plan = await db.get(HostingPlan, pid)
    if not plan:
        raise HTTPException(404)
    plan.is_active = not plan.is_active
    await db.commit()
    return {"ok": True, "is_active": plan.is_active}


@app.post("/api/admin/games")
async def admin_create_game(
    name: str = Form(...), slug: str = Form(...), docker_image: str = Form(""),
    default_port: int = Form(25565), ram_mb: int = Form(1024),
    cpu: float = Form(1.0), storage_gb: int = Form(5),
    user: User = Depends(require_admin), db: AsyncSession = Depends(get_db),
):
    db.add(GameTemplate(
        name=name, slug=slug, docker_image=docker_image or None,
        default_port=default_port, ram_mb=ram_mb, cpu=cpu, storage_gb=storage_gb,
    ))
    await db.commit()
    return {"ok": True}


@app.post("/api/admin/broadcast")
async def admin_broadcast(
    title: str = Form(...), body: str = Form(...),
    user: User = Depends(require_admin), db: AsyncSession = Depends(get_db),
):
    users = (await db.execute(select(User))).scalars().all()
    for u in users:
        db.add(Notification(user_id=u.id, title=title, body=body))
    await db.commit()
    await audit(db, user.id, "broadcast", title)
    return {"ok": True, "sent": len(users)}


@app.get("/api/admin/system")
async def admin_system(user: User = Depends(require_admin)):
    import psutil
    import time as _time
    disk = psutil.disk_usage("/")
    mem = psutil.virtual_memory()
    boot = psutil.boot_time()
    uptime_sec = int(_time.time() - boot)
    try:
        load = psutil.getloadavg()
    except Exception:
        load = (0, 0, 0)
    return {
        "cpu_percent": psutil.cpu_percent(interval=0.2),
        "ram_percent": mem.percent,
        "ram_used_gb": round(mem.used / (1024**3), 2),
        "ram_total_gb": round(mem.total / (1024**3), 2),
        "disk_percent": disk.percent,
        "disk_used_gb": round(disk.used / (1024**3), 2),
        "disk_total_gb": round(disk.total / (1024**3), 2),
        "running_processes": len([k for k, v in process_manager._procs.items() if v.returncode is None]),
        "uptime_seconds": uptime_sec,
        "uptime": _uptime(uptime_sec),
        "load_avg": [round(x, 2) for x in load],
        "status": "online",
    }


@app.get("/api/admin/dashboard")
async def admin_dashboard_api(user: User = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    """Real-time dashboard stats from DB."""
    now = datetime.now(timezone.utc)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    async def cnt(q):
        return (await db.execute(q)).scalar() or 0

    revenue_total = float((await db.execute(select(func.coalesce(func.sum(Order.amount), 0)).where(Order.status == "paid"))).scalar() or 0)
    revenue_today = float((await db.execute(select(func.coalesce(func.sum(Order.amount), 0)).where(Order.status == "paid", Order.paid_at >= today_start))).scalar() or 0)
    revenue_month = float((await db.execute(select(func.coalesce(func.sum(Order.amount), 0)).where(Order.status == "paid", Order.paid_at >= month_start))).scalar() or 0)

    # Chart data: last 7 days
    chart_days = []
    for i in range(6, -1, -1):
        day = (now - timedelta(days=i)).replace(hour=0, minute=0, second=0, microsecond=0)
        day_end = day + timedelta(days=1)
        rev = float((await db.execute(select(func.coalesce(func.sum(Order.amount), 0)).where(Order.status == "paid", Order.paid_at >= day, Order.paid_at < day_end))).scalar() or 0)
        new_users = await cnt(select(func.count()).select_from(User).where(User.created_at >= day, User.created_at < day_end))
        new_hosting = await cnt(select(func.count()).select_from(Project).where(Project.created_at >= day, Project.created_at < day_end))
        new_orders = await cnt(select(func.count()).select_from(Order).where(Order.created_at >= day, Order.created_at < day_end))
        chart_days.append({
            "date": day.strftime("%Y-%m-%d"),
            "label": day.strftime("%m/%d"),
            "revenue": rev,
            "users": new_users,
            "hosting": new_hosting,
            "orders": new_orders,
        })

    return {
        "users_total": await cnt(select(func.count()).select_from(User)),
        "users_active": await cnt(select(func.count()).select_from(User).where(User.is_suspended == False, User.is_active == True)),
        "users_suspended": await cnt(select(func.count()).select_from(User).where(User.is_suspended == True)),
        "hosting_total": await cnt(select(func.count()).select_from(Project)),
        "hosting_running": await cnt(select(func.count()).select_from(Project).where(Project.status == "running")),
        "hosting_stopped": await cnt(select(func.count()).select_from(Project).where(Project.status == "stopped")),
        "hosting_error": await cnt(select(func.count()).select_from(Project).where(Project.status == "error")),
        "hosting_expired": await cnt(select(func.count()).select_from(Project).where(Project.expires_at != None, Project.expires_at < now)),
        "revenue_total": revenue_total,
        "revenue_today": revenue_today,
        "revenue_month": revenue_month,
        "orders_pending": await cnt(select(func.count()).select_from(Order).where(Order.status.in_(["pending", "awaiting_confirm"]))),
        "orders_paid": await cnt(select(func.count()).select_from(Order).where(Order.status == "paid")),
        "orders_failed": await cnt(select(func.count()).select_from(Order).where(Order.status.in_(["failed", "cancelled"]))),
        "domains_total": await cnt(select(func.count()).select_from(DomainRecord)),
        "domains_active": await cnt(select(func.count()).select_from(DomainRecord).where(DomainRecord.status == "active")),
        "tickets_open": await cnt(select(func.count()).select_from(SupportTicket).where(SupportTicket.status.in_(["open", "answered"]))),
        "chart": chart_days,
    }


@app.get("/api/admin/users/{uid}")
async def admin_user_detail(uid: int, user: User = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    u = await db.get(User, uid)
    if not u:
        raise HTTPException(404, "User not found")
    projects = (await db.execute(select(Project).where(Project.user_id == uid).order_by(desc(Project.created_at)))).scalars().all()
    orders = (await db.execute(select(Order).where(Order.user_id == uid).order_by(desc(Order.created_at)).limit(50))).scalars().all()
    logins = (await db.execute(select(LoginHistory).where(LoginHistory.user_id == uid).order_by(desc(LoginHistory.created_at)).limit(30))).scalars().all()
    domains = (await db.execute(select(DomainRecord).where(DomainRecord.user_id == uid))).scalars().all()
    spent = float((await db.execute(select(func.coalesce(func.sum(Order.amount), 0)).where(Order.user_id == uid, Order.status == "paid"))).scalar() or 0)
    last_login = logins[0].created_at.isoformat() if logins else None
    return {
        "id": u.id,
        "email": u.email,
        "username": u.username,
        "full_name": u.full_name,
        "role": u.role,
        "is_active": u.is_active,
        "is_suspended": u.is_suspended,
        "auth_provider": u.auth_provider,
        "created_at": u.created_at.isoformat() if u.created_at else None,
        "last_login": last_login,
        "spent": spent,
        "projects": [{"id": p.id, "name": p.name, "status": p.status, "ram_mb": p.ram_mb, "cpu": p.cpu, "storage_gb": p.storage_gb, "expires_at": p.expires_at.isoformat() if p.expires_at else None, "created_at": p.created_at.isoformat() if p.created_at else None} for p in projects],
        "orders": [{"id": o.id, "amount": o.amount, "status": o.status, "payment_method": o.payment_method, "created_at": o.created_at.isoformat() if o.created_at else None} for o in orders],
        "logins": [{"ip": l.ip, "user_agent": l.user_agent, "success": l.success, "method": l.method, "created_at": l.created_at.isoformat() if l.created_at else None} for l in logins],
        "domains": [{"id": d.id, "domain": d.domain, "status": d.status, "ssl_status": d.ssl_status} for d in domains],
    }


@app.post("/api/admin/users/{uid}/delete")
async def admin_delete_user(uid: int, user: User = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    u = await db.get(User, uid)
    if not u or u.role == "admin":
        raise HTTPException(400, "Cannot delete this user")
    # stop and remove projects folders
    projects = (await db.execute(select(Project).where(Project.user_id == uid))).scalars().all()
    for p in projects:
        try:
            await process_manager.stop(p.id)
        except Exception:
            pass
        try:
            if p.folder:
                folder = process_manager.project_dir(p.user_id, p.folder)
                if folder.exists():
                    shutil.rmtree(folder, ignore_errors=True)
        except Exception:
            pass
        await db.delete(p)
    await db.delete(u)
    await db.commit()
    await audit(db, user.id, "delete_user", str(uid))
    return {"ok": True}


@app.post("/api/admin/users/{uid}/reset-password")
async def admin_reset_password(uid: int, password: str = Form(...), user: User = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    u = await db.get(User, uid)
    if not u:
        raise HTTPException(404)
    if len(password) < 6:
        raise HTTPException(400, "Password min 6 characters")
    u.hashed_password = hash_password(password)
    await db.commit()
    await audit(db, user.id, "reset_password", str(uid))
    return {"ok": True}


@app.post("/api/admin/projects/{project_id}/extend")
async def admin_extend_project(
    project_id: int, days: int = Form(30),
    user: User = Depends(require_admin), db: AsyncSession = Depends(get_db),
):
    p = await db.get(Project, project_id)
    if not p:
        raise HTTPException(404)
    now = datetime.now(timezone.utc)
    base = p.expires_at if p.expires_at and p.expires_at > now else now
    if base.tzinfo is None:
        base = base.replace(tzinfo=timezone.utc)
    p.expires_at = base + timedelta(days=int(days))
    await db.commit()
    await audit(db, user.id, "extend_hosting", f"project={project_id} days={days}")
    return {"ok": True, "expires_at": p.expires_at.isoformat()}


@app.post("/api/admin/projects/{project_id}/resources")
async def admin_change_resources(
    project_id: int,
    ram_mb: Optional[int] = Form(None),
    cpu: Optional[float] = Form(None),
    storage_gb: Optional[int] = Form(None),
    plan_id: Optional[int] = Form(None),
    user: User = Depends(require_admin), db: AsyncSession = Depends(get_db),
):
    p = await db.get(Project, project_id)
    if not p:
        raise HTTPException(404)
    if ram_mb is not None:
        p.ram_mb = int(ram_mb)
    if cpu is not None:
        p.cpu = float(cpu)
    if storage_gb is not None:
        p.storage_gb = int(storage_gb)
    if plan_id is not None:
        plan = await db.get(HostingPlan, plan_id)
        if plan:
            p.plan_id = plan.id
            p.ram_mb = plan.ram_mb
            p.cpu = plan.cpu
            p.storage_gb = plan.storage_gb
    await db.commit()
    await audit(db, user.id, "change_resources", f"project={project_id}")
    return {"ok": True}


@app.post("/api/admin/projects/{project_id}/auto")
async def admin_toggle_auto(
    project_id: int,
    auto_start: Optional[bool] = Form(None),
    auto_restart: Optional[bool] = Form(None),
    user: User = Depends(require_admin), db: AsyncSession = Depends(get_db),
):
    p = await db.get(Project, project_id)
    if not p:
        raise HTTPException(404)
    if auto_start is not None:
        p.auto_start = bool(auto_start)
    if auto_restart is not None:
        p.auto_restart = bool(auto_restart)
    await db.commit()
    return {"ok": True, "auto_start": p.auto_start, "auto_restart": p.auto_restart}


@app.get("/api/admin/search")
async def admin_global_search(q: str = "", user: User = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    q = (q or "").strip()
    if len(q) < 1:
        return {"users": [], "hosting": [], "orders": [], "domains": [], "tickets": []}
    like = f"%{q}%"
    users = (await db.execute(select(User).where((User.email.ilike(like)) | (User.username.ilike(like))).limit(10))).scalars().all()
    hosting = (await db.execute(select(Project).where(Project.name.ilike(like)).limit(10))).scalars().all()
    try:
        oid = int(q.replace("#", ""))
        orders = (await db.execute(select(Order).where(Order.id == oid).limit(5))).scalars().all()
    except ValueError:
        orders = (await db.execute(select(Order).where(Order.payment_id.ilike(like)).limit(10))).scalars().all()
    domains = (await db.execute(select(DomainRecord).where(DomainRecord.domain.ilike(like)).limit(10))).scalars().all()
    tickets = (await db.execute(select(SupportTicket).where(SupportTicket.subject.ilike(like)).limit(10))).scalars().all()
    return {
        "users": [{"id": u.id, "email": u.email, "username": u.username, "status": "suspended" if u.is_suspended else "active"} for u in users],
        "hosting": [{"id": p.id, "name": p.name, "status": p.status, "user_id": p.user_id} for p in hosting],
        "orders": [{"id": o.id, "amount": o.amount, "status": o.status, "user_id": o.user_id} for o in orders],
        "domains": [{"id": d.id, "domain": d.domain, "status": d.status} for d in domains],
        "tickets": [{"id": t.id, "subject": t.subject, "status": t.status} for t in tickets],
    }


@app.post("/api/admin/tickets/{tid}/close")
async def admin_close_ticket(tid: int, user: User = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    t = await db.get(SupportTicket, tid)
    if not t:
        raise HTTPException(404)
    t.status = "closed"
    await db.commit()
    return {"ok": True}


@app.post("/api/admin/tickets/{tid}/reopen")
async def admin_reopen_ticket(tid: int, user: User = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    t = await db.get(SupportTicket, tid)
    if not t:
        raise HTTPException(404)
    t.status = "open"
    await db.commit()
    return {"ok": True}


@app.get("/api/admin/settings")
async def admin_get_settings(user: User = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(select(SystemSetting))).scalars().all()
    return {r.key: r.value for r in rows}


@app.post("/api/admin/settings")
async def admin_save_settings(request: Request, user: User = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    form = await request.form()
    for key, value in form.items():
        if key.startswith("_"):
            continue
        row = (await db.execute(select(SystemSetting).where(SystemSetting.key == key))).scalar_one_or_none()
        if row:
            row.value = str(value)
        else:
            db.add(SystemSetting(key=key, value=str(value)))
    await db.commit()
    await audit(db, user.id, "update_settings", ",".join(form.keys()))
    return {"ok": True}


@app.get("/api/admin/domains")
async def admin_list_domains(user: User = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(select(DomainRecord).order_by(desc(DomainRecord.created_at)).limit(200))).scalars().all()
    return {"items": [{"id": d.id, "domain": d.domain, "user_id": d.user_id, "project_id": d.project_id, "status": d.status, "ssl_status": d.ssl_status, "created_at": d.created_at.isoformat() if d.created_at else None} for d in rows]}


@app.get("/api/admin/deployments")
async def admin_list_deployments(user: User = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(select(Deployment).order_by(desc(Deployment.created_at)).limit(100))).scalars().all()
    return {"items": [{"id": d.id, "project_id": d.project_id, "user_id": d.user_id, "repo_url": d.repo_url, "branch": d.branch, "status": d.status, "created_at": d.created_at.isoformat() if d.created_at else None, "finished_at": d.finished_at.isoformat() if d.finished_at else None} for d in rows]}


@app.get("/api/admin/backups")
async def admin_list_backups(user: User = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(select(Backup).order_by(desc(Backup.created_at)).limit(100))).scalars().all()
    return {"items": [{"id": b.id, "project_id": b.project_id, "filename": b.filename, "size": b.size_bytes, "created_at": b.created_at.isoformat() if b.created_at else None} for b in rows]}


@app.get("/api/admin/audit")
async def admin_audit_list(
    q: str = "", action: str = "", limit: int = 100,
    user: User = Depends(require_admin), db: AsyncSession = Depends(get_db),
):
    stmt = select(AuditLog).order_by(desc(AuditLog.created_at)).limit(min(limit, 500))
    rows = (await db.execute(stmt)).scalars().all()
    items = []
    for a in rows:
        if action and action not in (a.action or ""):
            continue
        if q and q.lower() not in ((a.action or "") + (a.detail or "")).lower():
            continue
        items.append({"id": a.id, "user_id": a.user_id, "action": a.action, "detail": a.detail, "created_at": a.created_at.isoformat() if a.created_at else None})
    return {"items": items}


# Health


# ═══════════════════════════════════════════════════════════
# Professional features: File ops, Backup restore, Domain,
# Git deploy, Coupons, Admin force-stop
# ═══════════════════════════════════════════════════════════

@app.post("/api/projects/{project_id}/files/rename")
async def rename_file(
    project_id: int, path: str = Form(...), new_name: str = Form(...),
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    p = await db.get(Project, project_id)
    if not p or (p.user_id != user.id and user.role != "admin"):
        raise HTTPException(404)
    base = process_manager.project_dir(p.user_id, p.folder)
    src = _safe_path(base, path)
    if not src.exists():
        raise HTTPException(404, "Not found")
    safe_name = Path(new_name).name
    if not safe_name or safe_name in (".", ".."):
        raise HTTPException(400, "Invalid name")
    dest = src.parent / safe_name
    if dest.exists():
        raise HTTPException(400, "Target exists")
    src.rename(dest)
    return {"ok": True}


@app.post("/api/projects/{project_id}/files/copy")
async def copy_file(
    project_id: int, path: str = Form(...), dest_path: str = Form(""),
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    p = await db.get(Project, project_id)
    if not p or (p.user_id != user.id and user.role != "admin"):
        raise HTTPException(404)
    base = process_manager.project_dir(p.user_id, p.folder)
    src = _safe_path(base, path)
    if not src.exists():
        raise HTTPException(404)
    target_dir = _safe_path(base, dest_path) if dest_path else src.parent
    target_dir.mkdir(parents=True, exist_ok=True)
    dest = target_dir / src.name
    if dest.exists():
        dest = target_dir / f"{src.stem}_copy{src.suffix}"
    if src.is_dir():
        shutil.copytree(src, dest)
    else:
        shutil.copy2(src, dest)
    return {"ok": True, "name": dest.name}


@app.post("/api/projects/{project_id}/files/move")
async def move_file(
    project_id: int, path: str = Form(...), dest_path: str = Form(...),
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    p = await db.get(Project, project_id)
    if not p or (p.user_id != user.id and user.role != "admin"):
        raise HTTPException(404)
    base = process_manager.project_dir(p.user_id, p.folder)
    src = _safe_path(base, path)
    target_dir = _safe_path(base, dest_path)
    if not src.exists():
        raise HTTPException(404)
    if src == base.resolve():
        raise HTTPException(400, "Cannot move the root folder")
    if src.is_dir() and (target_dir == src or src in target_dir.parents):
        raise HTTPException(400, "Cannot move a folder into itself")
    target_dir.mkdir(parents=True, exist_ok=True)
    dest = target_dir / src.name
    if dest == src:
        return {"ok": True}
    if dest.exists():
        raise HTTPException(400, f"'{src.name}' already exists in the destination")
    shutil.move(str(src), str(dest))
    return {"ok": True}


@app.post("/api/projects/{project_id}/files/write")
async def write_file(
    project_id: int, path: str = Form(...), content: str = Form(""),
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    p = await db.get(Project, project_id)
    if not p or (p.user_id != user.id and user.role != "admin"):
        raise HTTPException(404)
    base = process_manager.project_dir(p.user_id, p.folder)
    target = _safe_path(base, path)
    if target.exists() and target.is_dir():
        raise HTTPException(400, "Path is a directory")
    target.parent.mkdir(parents=True, exist_ok=True)
    # limit edit size 2MB
    data = content.encode("utf-8")
    if len(data) > 2 * 1024 * 1024:
        raise HTTPException(400, "File too large (max 2MB for editor)")
    target.write_bytes(data)
    return {"ok": True, "size": len(data)}


@app.get("/api/projects/{project_id}/files/read")
async def read_file_content(
    project_id: int, path: str = "",
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    p = await db.get(Project, project_id)
    if not p or (p.user_id != user.id and user.role != "admin"):
        raise HTTPException(404)
    base = process_manager.project_dir(p.user_id, p.folder)
    target = _safe_path(base, path)
    if not target.exists() or not target.is_file():
        raise HTTPException(404)
    if target.stat().st_size > 2 * 1024 * 1024:
        raise HTTPException(400, "File too large to edit")
    try:
        content = target.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        raise HTTPException(400, "Binary file cannot be edited as text")
    return {"ok": True, "content": content, "name": target.name}


@app.post("/api/projects/{project_id}/files/compress")
async def compress_files(
    project_id: int, path: str = Form(""), names: str = Form(...),
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    """names = comma-separated relative names in current path"""
    p = await db.get(Project, project_id)
    if not p or (p.user_id != user.id and user.role != "admin"):
        raise HTTPException(404)
    base = process_manager.project_dir(p.user_id, p.folder)
    cwd = _safe_path(base, path)
    items = [n.strip() for n in names.split(",") if n.strip()]
    if not items:
        raise HTTPException(400, "Nothing to compress")
    out_name = f"archive_{int(utcnow().timestamp())}.zip"
    out = cwd / out_name
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        for name in items:
            src = _safe_path(cwd, name)
            if not src.exists():
                continue
            if src.is_file():
                zf.write(src, src.name)
            else:
                for f in src.rglob("*"):
                    if f.is_file():
                        zf.write(f, str(f.relative_to(cwd)))
    return {"ok": True, "filename": out_name}


@app.post("/api/projects/{project_id}/backup/restore")
async def restore_backup(
    project_id: int, backup_id: int = Form(...),
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    p = await db.get(Project, project_id)
    if not p or (p.user_id != user.id and user.role != "admin"):
        raise HTTPException(404)
    b = await db.get(Backup, backup_id)
    if not b or b.project_id != project_id:
        raise HTTPException(404, "Backup not found")
    path = _backup_file(p.user_id, b.filename)
    if not path.exists():
        raise HTTPException(400, "Backup file missing on disk")
    # stop server first
    await process_manager.stop(p.id)
    p.status = "stopped"
    p.pid = None
    dest = process_manager.project_dir(p.user_id, p.folder)
    # extract over project dir (keep dir itself)
    try:
        with zipfile.ZipFile(path, "r") as zf:
            for info in zf.infolist():
                member_name = info.filename.replace("\\", "/").lstrip("/")
                if not member_name or ".." in member_name.split("/"):
                    continue
                target = _safe_path(dest, member_name)
                if info.is_dir() or member_name.endswith("/"):
                    target.mkdir(parents=True, exist_ok=True)
                else:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with zf.open(info) as src, open(target, "wb") as out:
                        shutil.copyfileobj(src, out)
    except zipfile.BadZipFile:
        raise HTTPException(400, "Corrupt backup")
    await db.commit()
    await audit(db, user.id, "restore_backup", f"project={project_id} backup={backup_id}")
    await notify(db, user.id, "Backup restored", f"Project {p.name} restored from backup #{backup_id}")
    return {"ok": True}


@app.get("/api/projects/{project_id}/domains")
async def list_domains(project_id: int, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    p = await db.get(Project, project_id)
    if not p or (p.user_id != user.id and user.role != "admin"):
        raise HTTPException(404)
    rows = (await db.execute(select(DomainRecord).where(DomainRecord.project_id == project_id))).scalars().all()
    return {"items": [{"id": d.id, "domain": d.domain, "status": d.status, "ssl_status": d.ssl_status} for d in rows]}


@app.post("/api/projects/{project_id}/domains")
async def add_domain(
    project_id: int, domain: str = Form(...),
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    p = await db.get(Project, project_id)
    if not p or (p.user_id != user.id and user.role != "admin"):
        raise HTTPException(404)
    dom = domain.strip().lower().replace("https://", "").replace("http://", "").split("/")[0]
    if not re.match(r"^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?(\.[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?)+$", dom):
        raise HTTPException(400, "Invalid domain")
    exists = (await db.execute(select(DomainRecord).where(DomainRecord.domain == dom))).scalar_one_or_none()
    if exists:
        raise HTTPException(400, "Domain already registered")
    rec = DomainRecord(project_id=p.id, user_id=user.id, domain=dom, status="pending", ssl_status="none")
    db.add(rec)
    # also set project.domain primary
    if not p.domain:
        p.domain = dom
    await db.commit()
    await db.refresh(rec)
    await audit(db, user.id, "add_domain", dom)
    return {
        "ok": True, "id": rec.id, "domain": dom, "status": "pending",
        "dns_instructions": f"Point A/CNAME of {dom} to your tunnel / server host, then mark verify.",
    }


@app.post("/api/projects/{project_id}/domains/{domain_id}/verify")
async def verify_domain(
    project_id: int, domain_id: int,
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    p = await db.get(Project, project_id)
    if not p or (p.user_id != user.id and user.role != "admin"):
        raise HTTPException(404)
    d = await db.get(DomainRecord, domain_id)
    if not d or d.project_id != project_id:
        raise HTTPException(404)
    # DNS resolution check (best-effort)
    import socket
    try:
        socket.getaddrinfo(d.domain, 80)
        d.status = "active"
        d.verified_at = utcnow()
        # SSL via Cloudflare Tunnel is external — mark pending unless tunnel handles it
        d.ssl_status = "pending"
        p.domain = d.domain
        await db.commit()
        return {"ok": True, "status": "active", "ssl_status": d.ssl_status,
                "note": "DNS resolves. Enable SSL via Cloudflare / reverse proxy on the host."}
    except socket.gaierror:
        d.status = "failed"
        await db.commit()
        raise HTTPException(400, "DNS does not resolve yet — check A/CNAME records")


@app.delete("/api/projects/{project_id}/domains/{domain_id}")
async def delete_domain(
    project_id: int, domain_id: int,
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    p = await db.get(Project, project_id)
    if not p or (p.user_id != user.id and user.role != "admin"):
        raise HTTPException(404)
    d = await db.get(DomainRecord, domain_id)
    if not d or d.project_id != project_id:
        raise HTTPException(404)
    if p.domain == d.domain:
        p.domain = None
    await db.delete(d)
    await db.commit()
    return {"ok": True}


@app.post("/api/projects/{project_id}/deploy/git")
async def deploy_git(
    project_id: int,
    repo_url: str = Form(...),
    branch: str = Form("main"),
    token: str = Form(""),
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    """Clone or pull git repo into project directory. Token is used only for this request (not stored)."""
    p = await db.get(Project, project_id)
    if not p or (p.user_id != user.id and user.role != "admin"):
        raise HTTPException(404)
    repo = repo_url.strip()
    if not (repo.startswith("https://") or repo.startswith("git@")):
        raise HTTPException(400, "Only https or git@ URLs allowed")
    # sanitize branch
    br = re.sub(r"[^a-zA-Z0-9._/-]", "", branch) or "main"
    dep = Deployment(project_id=p.id, user_id=user.id, repo_url=repo.split("@")[-1] if token else repo,
                     branch=br, status="running")
    db.add(dep)
    await db.commit()
    await db.refresh(dep)

    await process_manager.stop(p.id)
    p.status = "stopped"
    work = process_manager.project_dir(p.user_id, p.folder)
    work.mkdir(parents=True, exist_ok=True)
    log_lines = []
    try:
        # Build authenticated URL without persisting token
        clone_url = repo
        if token and repo.startswith("https://"):
            # https://TOKEN@github.com/...
            clone_url = repo.replace("https://", f"https://x-access-token:{token}@", 1)
        git_dir = work / ".git"
        if git_dir.exists():
            cmd = f'git fetch origin {br} && git checkout {br} && git pull origin {br}'
        else:
            # empty dir clone
            cmd = f'git clone --branch {br} --depth 1 "{clone_url}" .'
        proc = await asyncio.create_subprocess_shell(
            cmd, cwd=str(work),
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
        )
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=180)
        log_lines.append(out.decode("utf-8", errors="replace")[-8000:])
        if proc.returncode != 0:
            dep.status = "failed"
            dep.log = "\n".join(log_lines)
            dep.finished_at = utcnow()
            await db.commit()
            return {"ok": False, "error": "git failed", "log": dep.log, "id": dep.id}
        dep.status = "success"
        dep.log = "\n".join(log_lines)
        dep.finished_at = utcnow()
        await db.commit()
        await audit(db, user.id, "git_deploy", f"project={project_id} branch={br}")
        await notify(db, user.id, "Deploy success", f"{p.name} deployed from git ({br})")
        return {"ok": True, "id": dep.id, "log": dep.log}
    except asyncio.TimeoutError:
        dep.status = "failed"
        dep.log = "Timeout"
        dep.finished_at = utcnow()
        await db.commit()
        raise HTTPException(400, "Deploy timed out")
    except Exception as e:
        dep.status = "failed"
        dep.log = str(e)
        dep.finished_at = utcnow()
        await db.commit()
        raise HTTPException(400, str(e))


@app.get("/api/projects/{project_id}/deployments")
async def list_deployments(project_id: int, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    p = await db.get(Project, project_id)
    if not p or (p.user_id != user.id and user.role != "admin"):
        raise HTTPException(404)
    rows = (await db.execute(
        select(Deployment).where(Deployment.project_id == project_id).order_by(desc(Deployment.created_at)).limit(20)
    )).scalars().all()
    return {"items": [{"id": d.id, "repo_url": d.repo_url, "branch": d.branch, "status": d.status,
                       "created_at": d.created_at.isoformat() if d.created_at else None} for d in rows]}


@app.post("/api/coupons/validate")
async def validate_coupon(
    code: str = Form(...), amount: float = Form(0),
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    c = (await db.execute(select(Coupon).where(Coupon.code == code.strip().upper()))).scalar_one_or_none()
    if not c or not c.is_active:
        raise HTTPException(400, "Invalid coupon")
    if c.expires_at and _aware(c.expires_at) < utcnow():
        raise HTTPException(400, "Coupon expired")
    if c.max_uses and c.used_count >= c.max_uses:
        raise HTTPException(400, "Coupon usage limit reached")
    if amount < c.min_amount:
        raise HTTPException(400, f"Minimum amount ${c.min_amount}")
    if c.discount_type == "percent":
        discount = round(amount * (c.discount_value / 100.0), 2)
    else:
        discount = min(c.discount_value, amount)
    return {"ok": True, "code": c.code, "discount": discount, "final": max(0, round(amount - discount, 2))}


@app.post("/api/admin/coupons")
async def admin_create_coupon(
    code: str = Form(...), discount_type: str = Form("percent"), discount_value: float = Form(...),
    max_uses: int = Form(0), user: User = Depends(require_admin), db: AsyncSession = Depends(get_db),
):
    code = code.strip().upper()
    if (await db.execute(select(Coupon).where(Coupon.code == code))).scalar_one_or_none():
        raise HTTPException(400, "Code exists")
    c = Coupon(code=code, discount_type=discount_type, discount_value=discount_value, max_uses=max_uses)
    db.add(c)
    await db.commit()
    await audit(db, user.id, "create_coupon", code)
    return {"ok": True, "id": c.id}


@app.get("/api/admin/coupons")
async def admin_list_coupons(user: User = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(select(Coupon).order_by(desc(Coupon.id)))).scalars().all()
    return {"items": [{"id": c.id, "code": c.code, "discount_type": c.discount_type,
                       "discount_value": c.discount_value, "used_count": c.used_count,
                       "max_uses": c.max_uses, "is_active": c.is_active} for c in rows]}



# ─── Admin: Plans edit/delete ─────────────────────────────

@app.post("/api/admin/plans/{pid}/edit")
async def admin_edit_plan(
    pid: int,
    name: str = Form(...),
    ram_mb: int = Form(512),
    cpu: float = Form(1.0),
    storage_gb: int = Form(5),
    max_hostings: int = Form(1),
    price_monthly: float = Form(1.0),
    description: str = Form(""),
    user: User = Depends(require_admin), db: AsyncSession = Depends(get_db),
):
    plan = await db.get(HostingPlan, pid)
    if not plan:
        raise HTTPException(404)
    plan.name = name
    plan.ram_mb = ram_mb
    plan.cpu = cpu
    plan.storage_gb = storage_gb
    plan.max_hostings = max_hostings
    plan.price_monthly = price_monthly
    plan.description = description or None
    await db.commit()
    await audit(db, user.id, "edit_plan", str(pid))
    return {"ok": True}


@app.post("/api/admin/plans/{pid}/delete")
async def admin_delete_plan(pid: int, user: User = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    plan = await db.get(HostingPlan, pid)
    if not plan:
        raise HTTPException(404)
    # don't delete if projects still use it — just disable
    used = (await db.execute(select(func.count()).select_from(Project).where(Project.plan_id == pid))).scalar() or 0
    if used:
        plan.is_active = False
        await db.commit()
        return {"ok": True, "disabled": True, "message": f"Plan in use by {used} hostings — disabled instead of deleted"}
    await db.delete(plan)
    await db.commit()
    await audit(db, user.id, "delete_plan", str(pid))
    return {"ok": True}


# ─── Admin: Coupons manage ────────────────────────────────

@app.post("/api/admin/coupons/{cid}/toggle")
async def admin_coupon_toggle(cid: int, user: User = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    c = await db.get(Coupon, cid)
    if not c:
        raise HTTPException(404)
    c.is_active = not c.is_active
    await db.commit()
    return {"ok": True, "is_active": c.is_active}


@app.post("/api/admin/coupons/{cid}/delete")
async def admin_coupon_delete(cid: int, user: User = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    c = await db.get(Coupon, cid)
    if not c:
        raise HTTPException(404)
    await db.delete(c)
    await db.commit()
    await audit(db, user.id, "delete_coupon", str(cid))
    return {"ok": True}


@app.post("/api/admin/coupons/{cid}/edit")
async def admin_coupon_edit(
    cid: int,
    discount_value: float = Form(...),
    max_uses: int = Form(0),
    min_amount: float = Form(0),
    user: User = Depends(require_admin), db: AsyncSession = Depends(get_db),
):
    c = await db.get(Coupon, cid)
    if not c:
        raise HTTPException(404)
    c.discount_value = discount_value
    c.max_uses = max_uses
    c.min_amount = min_amount
    await db.commit()
    return {"ok": True}


# ─── Admin: Domains manage ────────────────────────────────

@app.post("/api/admin/domains/{domain_id}/verify")
async def admin_verify_domain(domain_id: int, user: User = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    d = await db.get(DomainRecord, domain_id)
    if not d:
        raise HTTPException(404)
    import socket
    try:
        socket.getaddrinfo(d.domain, 80)
        d.status = "active"
        d.verified_at = utcnow()
        d.ssl_status = "pending"
        p = await db.get(Project, d.project_id)
        if p and not p.domain:
            p.domain = d.domain
        await db.commit()
        await audit(db, user.id, "verify_domain", d.domain)
        return {"ok": True, "status": "active"}
    except socket.gaierror:
        d.status = "failed"
        await db.commit()
        raise HTTPException(400, "DNS does not resolve yet")


@app.post("/api/admin/domains/{domain_id}/ssl")
async def admin_domain_ssl(
    domain_id: int, ssl_status: str = Form("active"),
    user: User = Depends(require_admin), db: AsyncSession = Depends(get_db),
):
    d = await db.get(DomainRecord, domain_id)
    if not d:
        raise HTTPException(404)
    if ssl_status not in ("none", "pending", "active", "error"):
        raise HTTPException(400, "Invalid SSL status")
    d.ssl_status = ssl_status
    await db.commit()
    await audit(db, user.id, "ssl_domain", f"{d.domain}={ssl_status}")
    return {"ok": True, "ssl_status": d.ssl_status}


@app.post("/api/admin/domains/{domain_id}/remove")
async def admin_remove_domain(domain_id: int, user: User = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    d = await db.get(DomainRecord, domain_id)
    if not d:
        raise HTTPException(404)
    dom = d.domain
    p = await db.get(Project, d.project_id)
    if p and p.domain == dom:
        p.domain = None
    await db.delete(d)
    await db.commit()
    await audit(db, user.id, "remove_domain", dom)
    return {"ok": True}


@app.post("/api/admin/domains/add")
async def admin_add_domain(
    domain: str = Form(...), project_id: int = Form(...),
    user: User = Depends(require_admin), db: AsyncSession = Depends(get_db),
):
    p = await db.get(Project, project_id)
    if not p:
        raise HTTPException(404, "Project not found")
    dom = domain.strip().lower().replace("https://", "").replace("http://", "").split("/")[0]
    if not re.match(r"^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?(\.[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?)+$", dom):
        raise HTTPException(400, "Invalid domain")
    exists = (await db.execute(select(DomainRecord).where(DomainRecord.domain == dom))).scalar_one_or_none()
    if exists:
        raise HTTPException(400, "Domain already registered")
    rec = DomainRecord(project_id=p.id, user_id=p.user_id, domain=dom, status="pending", ssl_status="none")
    db.add(rec)
    if not p.domain:
        p.domain = dom
    await db.commit()
    await audit(db, user.id, "admin_add_domain", dom)
    return {"ok": True, "id": rec.id}


# ─── Admin: Deployments ───────────────────────────────────

@app.get("/api/admin/deployments/{dep_id}")
async def admin_deployment_detail(dep_id: int, user: User = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    d = await db.get(Deployment, dep_id)
    if not d:
        raise HTTPException(404)
    return {
        "id": d.id, "project_id": d.project_id, "user_id": d.user_id,
        "repo_url": d.repo_url, "branch": d.branch, "status": d.status,
        "log": d.log or "", "created_at": d.created_at.isoformat() if d.created_at else None,
        "finished_at": d.finished_at.isoformat() if d.finished_at else None,
    }


@app.post("/api/admin/deployments/{dep_id}/cancel")
async def admin_deployment_cancel(dep_id: int, user: User = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    d = await db.get(Deployment, dep_id)
    if not d:
        raise HTTPException(404)
    if d.status in ("success", "failed", "cancelled"):
        raise HTTPException(400, "Already finished")
    d.status = "cancelled"
    d.finished_at = utcnow()
    await db.commit()
    await audit(db, user.id, "cancel_deployment", str(dep_id))
    return {"ok": True}


@app.post("/api/admin/deployments/{dep_id}/retry")
async def admin_deployment_retry(dep_id: int, user: User = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    d = await db.get(Deployment, dep_id)
    if not d:
        raise HTTPException(404)
    # create new deployment record pointing same repo
    new = Deployment(
        project_id=d.project_id, user_id=d.user_id,
        repo_url=d.repo_url, branch=d.branch, status="pending",
    )
    db.add(new)
    await db.commit()
    await db.refresh(new)
    await audit(db, user.id, "retry_deployment", f"from={dep_id} new={new.id}")
    return {"ok": True, "id": new.id, "note": "Pending — trigger deploy from project page or redeploy endpoint"}


# ─── Admin: Backups manage ────────────────────────────────

@app.post("/api/admin/backups/create")
async def admin_backup_create(
    project_id: int = Form(...),
    user: User = Depends(require_admin), db: AsyncSession = Depends(get_db),
):
    p = await db.get(Project, project_id)
    if not p:
        raise HTTPException(404)
    # reuse existing backup logic via internal call pattern
    from pathlib import Path as P
    base = process_manager.project_dir(p.user_id, p.folder)
    if not base.exists():
        raise HTTPException(400, "Project folder missing")
    bdir = process_manager.backup_dir(p.user_id)
    bdir.mkdir(parents=True, exist_ok=True)
    fname = f"backup_{p.id}_{int(utcnow().timestamp())}.zip"
    out = bdir / fname
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in base.rglob("*"):
            if f.is_file():
                zf.write(f, str(f.relative_to(base)))
    size = out.stat().st_size
    b = Backup(project_id=p.id, filename=fname, size_bytes=size)
    db.add(b)
    await db.commit()
    await db.refresh(b)
    await audit(db, user.id, "admin_backup", f"project={project_id} backup={b.id}")
    return {"ok": True, "id": b.id, "filename": fname, "size": size}


@app.post("/api/admin/backups/{backup_id}/delete")
async def admin_backup_delete(backup_id: int, user: User = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    b = await db.get(Backup, backup_id)
    if not b:
        raise HTTPException(404)
    p = await db.get(Project, b.project_id)
    if p:
        path = process_manager.backup_dir(p.user_id) / b.filename
        if path.exists():
            path.unlink(missing_ok=True)
    await db.delete(b)
    await db.commit()
    await audit(db, user.id, "delete_backup", str(backup_id))
    return {"ok": True}


@app.post("/api/admin/backups/{backup_id}/restore")
async def admin_backup_restore(backup_id: int, user: User = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    b = await db.get(Backup, backup_id)
    if not b:
        raise HTTPException(404)
    p = await db.get(Project, b.project_id)
    if not p:
        raise HTTPException(404, "Project missing")
    path = process_manager.backup_dir(p.user_id) / b.filename
    if not path.exists():
        raise HTTPException(400, "Backup file missing on disk")
    await process_manager.stop(p.id)
    p.status = "stopped"
    p.pid = None
    dest = process_manager.project_dir(p.user_id, p.folder)
    try:
        with zipfile.ZipFile(path, "r") as zf:
            for info in zf.infolist():
                member_name = info.filename.replace("\\", "/").lstrip("/")
                if not member_name or ".." in member_name.split("/"):
                    continue
                target = _safe_path(dest, member_name)
                if info.is_dir() or member_name.endswith("/"):
                    target.mkdir(parents=True, exist_ok=True)
                else:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with zf.open(info) as src, open(target, "wb") as out:
                        shutil.copyfileobj(src, out)
    except zipfile.BadZipFile:
        raise HTTPException(400, "Corrupt backup")
    await db.commit()
    await audit(db, user.id, "admin_restore_backup", f"backup={backup_id} project={p.id}")
    return {"ok": True}


# ─── Admin: Orders refund ─────────────────────────────────

@app.post("/api/admin/orders/{order_id}/refund")
async def admin_refund_order(order_id: int, user: User = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    o = await db.get(Order, order_id)
    if not o:
        raise HTTPException(404)
    if o.status != "paid":
        raise HTTPException(400, "Only paid orders can be refunded")
    o.status = "refunded"
    await db.commit()
    await notify(db, o.user_id, "Order refunded", f"Order #{o.id} has been refunded.")
    await audit(db, user.id, "refund_order", str(order_id))
    return {"ok": True}


@app.post("/api/admin/orders/{order_id}/cancel")
async def admin_cancel_order(order_id: int, user: User = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    o = await db.get(Order, order_id)
    if not o:
        raise HTTPException(404)
    if o.status == "paid":
        raise HTTPException(400, "Use refund for paid orders")
    o.status = "cancelled"
    await db.commit()
    await audit(db, user.id, "cancel_order", str(order_id))
    return {"ok": True}


# ─── Admin: Users edit ────────────────────────────────────

@app.post("/api/admin/users/{uid}/edit")
async def admin_edit_user(
    uid: int,
    email: Optional[str] = Form(None),
    username: Optional[str] = Form(None),
    full_name: Optional[str] = Form(None),
    user: User = Depends(require_admin), db: AsyncSession = Depends(get_db),
):
    u = await db.get(User, uid)
    if not u:
        raise HTTPException(404)
    if email:
        email = email.strip().lower()
        exists = (await db.execute(select(User).where(User.email == email, User.id != uid))).scalar_one_or_none()
        if exists:
            raise HTTPException(400, "Email already used")
        u.email = email
    if username:
        username = username.strip()
        exists = (await db.execute(select(User).where(User.username == username, User.id != uid))).scalar_one_or_none()
        if exists:
            raise HTTPException(400, "Username already used")
        u.username = username
    if full_name is not None:
        u.full_name = full_name.strip() or None
    await db.commit()
    await audit(db, user.id, "edit_user", str(uid))
    return {"ok": True}


# ─── Admin: Tickets priority / assign ─────────────────────

@app.post("/api/admin/tickets/{tid}/priority")
async def admin_ticket_priority(
    tid: int, priority: str = Form(...),
    user: User = Depends(require_admin), db: AsyncSession = Depends(get_db),
):
    t = await db.get(SupportTicket, tid)
    if not t:
        raise HTTPException(404)
    if priority not in ("low", "normal", "high", "urgent"):
        raise HTTPException(400, "Invalid priority")
    t.priority = priority
    await db.commit()
    return {"ok": True}


@app.post("/api/admin/tickets/{tid}/assign")
async def admin_ticket_assign(
    tid: int, admin_id: int = Form(...),
    user: User = Depends(require_admin), db: AsyncSession = Depends(get_db),
):
    t = await db.get(SupportTicket, tid)
    if not t:
        raise HTTPException(404)
    t.assigned_to = admin_id
    await db.commit()
    return {"ok": True}


# ─── Admin: Broadcast targeted ────────────────────────────

@app.post("/api/admin/broadcast/targeted")
async def admin_broadcast_targeted(
    title: str = Form(...),
    body: str = Form(...),
    target: str = Form("all"),  # all | active | selected | expiring | expired
    user_ids: str = Form(""),  # comma-separated for selected
    user: User = Depends(require_admin), db: AsyncSession = Depends(get_db),
):
    now = datetime.now(timezone.utc)
    recipients = []
    if target == "all":
        recipients = (await db.execute(select(User))).scalars().all()
    elif target == "active":
        recipients = (await db.execute(select(User).where(User.is_suspended == False, User.is_active == True))).scalars().all()
    elif target == "selected":
        ids = [int(x) for x in user_ids.split(",") if x.strip().isdigit()]
        if ids:
            recipients = (await db.execute(select(User).where(User.id.in_(ids)))).scalars().all()
    elif target == "expiring":
        soon = now + timedelta(days=7)
        pids = (await db.execute(select(Project.user_id).where(Project.expires_at != None, Project.expires_at > now, Project.expires_at <= soon).distinct())).scalars().all()
        if pids:
            recipients = (await db.execute(select(User).where(User.id.in_(pids)))).scalars().all()
    elif target == "expired":
        pids = (await db.execute(select(Project.user_id).where(Project.expires_at != None, Project.expires_at < now).distinct())).scalars().all()
        if pids:
            recipients = (await db.execute(select(User).where(User.id.in_(pids)))).scalars().all()
    else:
        raise HTTPException(400, "Invalid target")
    for u in recipients:
        db.add(Notification(user_id=u.id, title=title, body=body))
    await db.commit()
    await audit(db, user.id, "broadcast_targeted", f"{target}:{title}")
    return {"ok": True, "sent": len(recipients)}


# ─── Admin: IP block ──────────────────────────────────────

@app.get("/api/admin/blocked-ips")
async def admin_list_blocked_ips(user: User = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(select(BlockedIP).order_by(desc(BlockedIP.created_at)).limit(200))).scalars().all()
    return {"items": [{"id": r.id, "ip": r.ip, "reason": r.reason, "created_by": r.created_by, "created_at": r.created_at.isoformat() if r.created_at else None} for r in rows]}


@app.post("/api/admin/blocked-ips")
async def admin_block_ip(
    ip: str = Form(...), reason: str = Form(""),
    user: User = Depends(require_admin), db: AsyncSession = Depends(get_db),
):
    ip = ip.strip()
    if not ip:
        raise HTTPException(400, "IP required")
    exists = (await db.execute(select(BlockedIP).where(BlockedIP.ip == ip))).scalar_one_or_none()
    if exists:
        raise HTTPException(400, "Already blocked")
    db.add(BlockedIP(ip=ip, reason=reason or None, created_by=user.id))
    await db.commit()
    await audit(db, user.id, "block_ip", ip)
    return {"ok": True}


@app.post("/api/admin/blocked-ips/{bid}/unblock")
async def admin_unblock_ip(bid: int, user: User = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    r = await db.get(BlockedIP, bid)
    if not r:
        raise HTTPException(404)
    ip = r.ip
    await db.delete(r)
    await db.commit()
    await audit(db, user.id, "unblock_ip", ip)
    return {"ok": True}


# ─── Admin: Server processes & health ─────────────────────

@app.get("/api/admin/processes")
async def admin_processes(user: User = Depends(require_admin)):
    import psutil
    procs = []
    for p in psutil.process_iter(["pid", "name", "cpu_percent", "memory_percent", "status", "create_time"]):
        try:
            info = p.info
            if info.get("cpu_percent", 0) > 0.1 or info.get("memory_percent", 0) > 0.5:
                procs.append({
                    "pid": info["pid"],
                    "name": info.get("name") or "?",
                    "cpu": round(info.get("cpu_percent") or 0, 1),
                    "mem": round(info.get("memory_percent") or 0, 1),
                    "status": info.get("status"),
                })
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    procs.sort(key=lambda x: x["cpu"], reverse=True)
    # also managed hostings
    managed = []
    for pid_key, proc in list(process_manager._procs.items()):
        try:
            running = proc.returncode is None
            managed.append({"project_id": pid_key, "running": running, "pid": getattr(proc, "pid", None)})
        except Exception:
            managed.append({"project_id": pid_key, "running": False})
    return {"top": procs[:40], "managed": managed}


@app.get("/api/admin/server-logs")
async def admin_server_logs(lines: int = 100, user: User = Depends(require_admin)):
    """Return recent application log lines if a log file exists."""
    log_candidates = [
        BASE_DIR / "logs" / "app.log",
        BASE_DIR / "data" / "app.log",
        Path("/tmp/anajak-host.log"),
    ]
    content = ""
    for lp in log_candidates:
        if lp.exists():
            try:
                text = lp.read_text(errors="ignore")
                content = "\n".join(text.splitlines()[-min(lines, 500):])
                break
            except Exception:
                pass
    if not content:
        content = "(No app log file found. Process stdout is not captured to disk by default.)"
    return {"log": content}


# ─── Admin: Hosting logs (admin view any) ─────────────────

@app.get("/api/admin/projects/{project_id}/logs")
async def admin_project_logs(project_id: int, lines: int = 200, user: User = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    p = await db.get(Project, project_id)
    if not p:
        raise HTTPException(404)
    log = process_manager.read_logs(p.user_id, p.folder or "", lines=lines)
    return {"log": log, "project_id": project_id, "name": p.name}




# ─── Admin: Sessions (remote logout) ──────────────────────

@app.get("/api/admin/sessions")
async def admin_list_sessions(user: User = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(
        select(UserSession, User.email, User.role)
        .join(User, User.id == UserSession.user_id)
        .where(UserSession.is_revoked == False)
        .order_by(desc(UserSession.created_at))
        .limit(200)
    )).all()
    return {"items": [{
        "id": s.id, "user_id": s.user_id, "email": email, "role": role,
        "ip": s.ip, "user_agent": s.user_agent,
        "created_at": s.created_at.isoformat() if s.created_at else None,
        "expires_at": s.expires_at.isoformat() if s.expires_at else None,
    } for s, email, role in rows]}


@app.post("/api/admin/sessions/{sid}/revoke")
async def admin_revoke_session(sid: int, user: User = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    s = await db.get(UserSession, sid)
    if not s:
        raise HTTPException(404)
    s.is_revoked = True
    await db.commit()
    await audit(db, user.id, "revoke_session", f"session={sid} user={s.user_id}")
    return {"ok": True}


@app.post("/api/admin/sessions/revoke-user/{uid}")
async def admin_revoke_user_sessions(uid: int, user: User = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(select(UserSession).where(UserSession.user_id == uid, UserSession.is_revoked == False))).scalars().all()
    for s in rows:
        s.is_revoked = True
    await db.commit()
    await audit(db, user.id, "revoke_user_sessions", str(uid))
    return {"ok": True, "revoked": len(rows)}


# ─── Admin: Paginated lists ───────────────────────────────

@app.get("/api/admin/users")
async def admin_list_users(
    q: str = "", status: str = "", page: int = 1, per_page: int = 30,
    user: User = Depends(require_admin), db: AsyncSession = Depends(get_db),
):
    page = max(1, page)
    per_page = min(max(1, per_page), 100)
    stmt = select(User)
    count_stmt = select(func.count()).select_from(User)
    if q:
        like = f"%{q}%"
        stmt = stmt.where((User.email.ilike(like)) | (User.username.ilike(like)))
        count_stmt = count_stmt.where((User.email.ilike(like)) | (User.username.ilike(like)))
    if status == "active":
        stmt = stmt.where(User.is_suspended == False, User.is_active == True)
        count_stmt = count_stmt.where(User.is_suspended == False, User.is_active == True)
    elif status == "suspended":
        stmt = stmt.where(User.is_suspended == True)
        count_stmt = count_stmt.where(User.is_suspended == True)
    total = (await db.execute(count_stmt)).scalar() or 0
    rows = (await db.execute(stmt.order_by(desc(User.created_at)).offset((page - 1) * per_page).limit(per_page))).scalars().all()
    return {
        "items": [{"id": u.id, "email": u.email, "username": u.username, "role": u.role,
                   "is_suspended": u.is_suspended, "is_active": u.is_active,
                   "auth_provider": u.auth_provider,
                   "created_at": u.created_at.isoformat() if u.created_at else None} for u in rows],
        "total": total, "page": page, "per_page": per_page, "pages": max(1, (total + per_page - 1) // per_page),
    }


@app.get("/api/admin/projects")
async def admin_list_projects(
    q: str = "", status: str = "", page: int = 1, per_page: int = 30,
    user: User = Depends(require_admin), db: AsyncSession = Depends(get_db),
):
    page = max(1, page)
    per_page = min(max(1, per_page), 100)
    stmt = select(Project)
    count_stmt = select(func.count()).select_from(Project)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(Project.name.ilike(like))
        count_stmt = count_stmt.where(Project.name.ilike(like))
    if status:
        stmt = stmt.where(Project.status == status)
        count_stmt = count_stmt.where(Project.status == status)
    total = (await db.execute(count_stmt)).scalar() or 0
    rows = (await db.execute(stmt.order_by(desc(Project.created_at)).offset((page - 1) * per_page).limit(per_page))).scalars().all()
    return {
        "items": [{"id": p.id, "name": p.name, "user_id": p.user_id, "status": p.status,
                   "project_type": p.project_type, "ram_mb": p.ram_mb, "cpu": p.cpu,
                   "storage_gb": p.storage_gb,
                   "expires_at": p.expires_at.isoformat() if p.expires_at else None,
                   "created_at": p.created_at.isoformat() if p.created_at else None} for p in rows],
        "total": total, "page": page, "per_page": per_page, "pages": max(1, (total + per_page - 1) // per_page),
    }


@app.get("/api/admin/orders")
async def admin_list_orders(
    status: str = "", page: int = 1, per_page: int = 30,
    user: User = Depends(require_admin), db: AsyncSession = Depends(get_db),
):
    page = max(1, page)
    per_page = min(max(1, per_page), 100)
    stmt = select(Order)
    count_stmt = select(func.count()).select_from(Order)
    if status:
        stmt = stmt.where(Order.status == status)
        count_stmt = count_stmt.where(Order.status == status)
    total = (await db.execute(count_stmt)).scalar() or 0
    rows = (await db.execute(stmt.order_by(desc(Order.created_at)).offset((page - 1) * per_page).limit(per_page))).scalars().all()
    return {
        "items": [{"id": o.id, "user_id": o.user_id, "amount": o.amount, "status": o.status,
                   "payment_method": o.payment_method, "payment_id": o.payment_id,
                   "created_at": o.created_at.isoformat() if o.created_at else None} for o in rows],
        "total": total, "page": page, "per_page": per_page, "pages": max(1, (total + per_page - 1) // per_page),
    }


# ─── Admin: Integrations / Webhooks ───────────────────────

@app.get("/api/admin/integrations")
async def admin_get_integrations(user: User = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    keys = [
        "github_token", "github_client_id", "github_client_secret",
        "cloudflare_api_token", "cloudflare_zone_id", "cloudflare_account_id",
        "telegram_notify_chat_id", "webhook_signing_secret",
        "auto_backup_enabled", "auto_backup_hour", "auto_backup_interval_hours",
    ]
    rows = (await db.execute(select(SystemSetting).where(SystemSetting.key.in_(keys)))).scalars().all()
    data = {r.key: r.value for r in rows}
    # mask secrets
    for k in list(data.keys()):
        if data[k] and any(x in k for x in ("token", "secret", "password", "key")):
            v = data[k]
            data[k + "_set"] = "1"
            data[k] = (v[:4] + "…" + v[-2:]) if len(v) > 8 else "••••"
    hooks = (await db.execute(select(WebhookEndpoint).order_by(desc(WebhookEndpoint.id)).limit(50))).scalars().all()
    return {
        "settings": data,
        "webhooks": [{"id": h.id, "name": h.name, "url": h.url, "events": h.events, "is_active": h.is_active,
                      "has_secret": bool(h.secret)} for h in hooks],
    }


@app.post("/api/admin/integrations")
async def admin_save_integrations(request: Request, user: User = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    form = await request.form()
    allowed = {
        "github_token", "github_client_id", "github_client_secret",
        "cloudflare_api_token", "cloudflare_zone_id", "cloudflare_account_id",
        "telegram_notify_chat_id", "webhook_signing_secret",
        "auto_backup_enabled", "auto_backup_hour", "auto_backup_interval_hours",
    }
    for key, value in form.items():
        if key not in allowed:
            continue
        val = str(value).strip()
        # skip if masked placeholder
        if "…" in val or val == "••••":
            continue
        row = (await db.execute(select(SystemSetting).where(SystemSetting.key == key))).scalar_one_or_none()
        if row:
            row.value = val
        else:
            db.add(SystemSetting(key=key, value=val))
    await db.commit()
    await audit(db, user.id, "update_integrations", ",".join(form.keys()))
    return {"ok": True}


@app.post("/api/admin/webhooks")
async def admin_create_webhook(
    name: str = Form(...), url: str = Form(...), events: str = Form("order.paid"),
    secret: str = Form(""),
    user: User = Depends(require_admin), db: AsyncSession = Depends(get_db),
):
    h = WebhookEndpoint(name=name, url=url, events=events, secret=secret or None)
    db.add(h)
    await db.commit()
    await db.refresh(h)
    await audit(db, user.id, "create_webhook", name)
    return {"ok": True, "id": h.id}


@app.post("/api/admin/webhooks/{hid}/toggle")
async def admin_toggle_webhook(hid: int, user: User = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    h = await db.get(WebhookEndpoint, hid)
    if not h:
        raise HTTPException(404)
    h.is_active = not h.is_active
    await db.commit()
    return {"ok": True, "is_active": h.is_active}


@app.post("/api/admin/webhooks/{hid}/delete")
async def admin_delete_webhook(hid: int, user: User = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    h = await db.get(WebhookEndpoint, hid)
    if not h:
        raise HTTPException(404)
    await db.delete(h)
    await db.commit()
    return {"ok": True}


@app.post("/api/admin/webhooks/{hid}/test")
async def admin_test_webhook(hid: int, user: User = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    h = await db.get(WebhookEndpoint, hid)
    if not h:
        raise HTTPException(404)
    import httpx
    payload = {"event": "test", "source": "anajak-host", "time": utcnow().isoformat()}
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.post(h.url, json=payload, headers={"X-Anajak-Event": "test"})
        return {"ok": True, "status_code": r.status_code, "body": r.text[:500]}
    except Exception as e:
        raise HTTPException(400, f"Webhook failed: {e}")


# ─── Admin: Auto-backup all hostings once ─────────────────

@app.post("/api/admin/backups/run-all")
async def admin_backup_all(user: User = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    projects = (await db.execute(select(Project))).scalars().all()
    created = 0
    errors = []
    for p in projects:
        try:
            base = process_manager.project_dir(p.user_id, p.folder)
            if not base.exists():
                continue
            bdir = process_manager.backup_dir(p.user_id)
            bdir.mkdir(parents=True, exist_ok=True)
            fname = f"auto_{p.id}_{int(utcnow().timestamp())}.zip"
            out = bdir / fname
            with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
                for f in base.rglob("*"):
                    if f.is_file():
                        zf.write(f, str(f.relative_to(base)))
            b = Backup(project_id=p.id, filename=fname, size_bytes=out.stat().st_size)
            db.add(b)
            created += 1
        except Exception as e:
            errors.append(f"#{p.id}: {e}")
    await db.commit()
    await audit(db, user.id, "backup_all", f"created={created}")
    return {"ok": True, "created": created, "errors": errors[:20]}



@app.post("/api/admin/projects/{project_id}/force-stop")
async def admin_force_stop(project_id: int, user: User = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    p = await db.get(Project, project_id)
    if not p:
        raise HTTPException(404)
    await process_manager.force_kill(p.id)
    p.status = "stopped"
    p.pid = None
    await db.commit()
    await audit(db, user.id, "force_stop", str(project_id))
    return {"ok": True}


@app.get("/api/settings/login-history")
async def my_login_history(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(
        select(LoginHistory).where(LoginHistory.user_id == user.id).order_by(desc(LoginHistory.created_at)).limit(20)
    )).scalars().all()
    return {"items": [{"ip": r.ip, "success": r.success, "user_agent": r.user_agent,
                       "at": r.created_at.isoformat() if r.created_at else None} for r in rows]}


@app.get("/api/dashboard/stats")
async def dashboard_stats(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    projects = (await db.execute(select(Project).where(Project.user_id == user.id))).scalars().all()
    running = sum(1 for p in projects if p.status == "running")
    stopped = sum(1 for p in projects if p.status == "stopped")
    suspended = sum(1 for p in projects if p.status == "suspended")
    return {
        "total": len(projects), "running": running, "stopped": stopped, "suspended": suspended,
        "projects": [{"id": p.id, "name": p.name, "status": p.status, "cpu": p.cpu, "ram_mb": p.ram_mb} for p in projects],
    }



# ─── Extra panel endpoints (backups / env / live stats) ────

async def _own_project(db: AsyncSession, project_id: int, user: User) -> Project:
    p = await db.get(Project, project_id)
    if not p or (p.user_id != user.id and user.role != "admin"):
        raise HTTPException(404)
    return p


@app.get("/api/projects/{project_id}/backups")
async def list_backups(project_id: int, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    p = await _own_project(db, project_id, user)
    rows = (await db.execute(select(Backup).where(Backup.project_id == project_id).order_by(desc(Backup.created_at)))).scalars().all()
    return {"items": [{
        "id": b.id, "filename": b.filename, "size_bytes": b.size_bytes or 0,
        "created_at": _aware(b.created_at).isoformat() if b.created_at else None,
        "exists": _backup_file(p.user_id, b.filename).exists(),
    } for b in rows]}


@app.get("/api/projects/{project_id}/backups/{backup_id}/download")
async def download_backup(project_id: int, backup_id: int, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    p = await _own_project(db, project_id, user)
    b = await db.get(Backup, backup_id)
    if not b or b.project_id != project_id:
        raise HTTPException(404, "Backup not found")
    path = _backup_file(p.user_id, b.filename)
    if not path.exists():
        raise HTTPException(404, "Backup file missing on disk")
    return FileResponse(path, filename=b.filename, media_type="application/zip")


@app.delete("/api/projects/{project_id}/backups/{backup_id}")
async def delete_backup(project_id: int, backup_id: int, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    p = await _own_project(db, project_id, user)
    b = await db.get(Backup, backup_id)
    if not b or b.project_id != project_id:
        raise HTTPException(404, "Backup not found")
    try:
        _backup_file(p.user_id, b.filename).unlink(missing_ok=True)
    except OSError:
        pass
    await db.delete(b)
    await db.commit()
    await audit(db, user.id, "delete_backup", f"project={project_id} backup={backup_id}")
    return {"ok": True}


@app.get("/api/projects/{project_id}/env")
async def list_env(project_id: int, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    p = await _own_project(db, project_id, user)
    return {"items": [{"key": k, "value": "" if v is None else str(v)} for k, v in (p.env_vars or {}).items()]}


@app.get("/api/dashboard/live")
async def dashboard_live(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """Live status + usage for every server of the current user (used by the Servers page)."""
    projects = (await db.execute(select(Project).where(Project.user_id == user.id))).scalars().all()
    out = {}
    for p in projects:
        i = _srv_info(p)
        out[str(p.id)] = {
            "status": i["status"], "tag": i["tag"], "label": i["label"],
            "cpu": i["cpu"] or 0, "ram": i["ram"] or 0, "disk_mb": round(i["disk_mb"], 2),
        }
    return {"items": out}



# ═══════════════════════════════════════════════════════════
# Hosting Manager API (server_id based)
# Every call is checked against the logged-in user: a user can
# only reach user_bots/<own user>/ and data/<own user>/.
# The browser never touches those folders directly.
# ═══════════════════════════════════════════════════════════

@app.get("/api/servers")
async def api_servers(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(select(Project).where(Project.user_id == user.id).order_by(Project.id))).scalars().all()
    return {"user": process_manager.user_code(user.id), "servers": [{
        "id": p.id, "name": p.name, "folder": p.folder, "runtime": p.project_type,
        "start_command": p.start_command, "pid": process_manager.status(p.id).get("pid"),
        "path": f"user_bots/{process_manager.user_code(p.user_id)}/{p.folder}",
        "cpu": p.cpu, "ram_mb": p.ram_mb, "storage_gb": p.storage_gb,
        "created_at": p.created_at.isoformat() if p.created_at else None,
        "expires_at": p.expires_at.isoformat() if p.expires_at else None,
        **_srv_info(p),
    } for p in rows]}


@app.post("/api/servers/create")
async def api_servers_create(
    name: str = Form(...), project_type: str = Form("custom"), plan_id: int = Form(...),
    start_command: str = Form(""), port: int = Form(0),
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    return await create_project(name, project_type, plan_id, start_command, port, "upload", "", 1, user, db)


@app.post("/api/servers/start")
async def api_servers_start(server_id: int = Form(...), user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return await start_project(server_id, user, db)


@app.post("/api/servers/stop")
async def api_servers_stop(server_id: int = Form(...), user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return await stop_project(server_id, user, db)


@app.post("/api/servers/restart")
async def api_servers_restart(server_id: int = Form(...), user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return await restart_project(server_id, user, db)


@app.get("/api/files")
async def api_files(server_id: int, path: str = "", user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return await list_files(server_id, path, user, db)


@app.get("/api/files/download")
async def api_files_download(server_id: int, path: str = "", user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return await download_file(server_id, path, user, db)


@app.get("/api/files/search")
async def api_files_search(server_id: int, q: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    p = await _own_project(db, server_id, user)
    base = process_manager.project_dir(p.user_id, p.folder).resolve()
    needle = q.strip().lower()
    if not needle:
        return {"items": []}
    items = []
    for root, dirs, files in os.walk(base, followlinks=False):
        for name in dirs + files:
            if needle in name.lower():
                full = Path(root) / name
                if full.is_symlink():
                    continue
                items.append({"name": name, "path": str(full.relative_to(base)).replace("\\", "/"), "is_dir": full.is_dir()})
                if len(items) >= 200:
                    return {"items": items, "truncated": True}
    return {"items": items}


@app.post("/api/files/upload")
async def api_files_upload(
    server_id: int = Form(...), path: str = Form(""), file: UploadFile = File(...), extract: str = Form("false"),
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    return await upload_file(server_id, path, file, extract, user, db)


@app.post("/api/files/create")
async def api_files_create(
    server_id: int = Form(...), path: str = Form(""), name: str = Form(...), type: str = Form("file"), content: str = Form(""),
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    if type == "folder":
        return await mkdir_file(server_id, path, name, user, db)
    return await write_file(server_id, f"{path}/{name}".strip("/"), content, user, db)


@app.put("/api/files/update")
async def api_files_update(
    server_id: int = Form(...), path: str = Form(...), content: str = Form(""),
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    return await write_file(server_id, path, content, user, db)


@app.delete("/api/files/delete")
async def api_files_delete(server_id: int, path: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return await delete_file(server_id, path, user, db)


@app.get("/api/console")
async def api_console(server_id: int, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return await get_logs(server_id, user, db)


@app.post("/api/console/command")
async def api_console_command(server_id: int = Form(...), command: str = Form(...), user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return await send_command(server_id, command, user, db)


@app.get("/api/backups")
async def api_backups(server_id: int, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return await list_backups(server_id, user, db)


@app.post("/api/backups/create")
async def api_backups_create(server_id: int = Form(...), user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return await create_backup(server_id, user, db)


@app.post("/api/backups/restore")
async def api_backups_restore(server_id: int = Form(...), backup_id: int = Form(...), user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return await restore_backup(server_id, backup_id, user, db)



@app.get("/favicon.ico")
async def favicon():
    logo = BASE_DIR / "static" / "img" / "logo.png"
    if logo.exists():
        return FileResponse(logo)
    raise HTTPException(404)

@app.get("/health")
async def health():
    return {"status": "ok", "app": "Anajak Host"}


if __name__ == "__main__":
    import uvicorn
    import os
    port = int(os.getenv("PORT", str(PORT)))
    print(f"Anajak Host → http://127.0.0.1:{port}", flush=True)
    # Pass app object directly (avoids import path issues). reload=False for stable hosting.
    uvicorn.run(app, host="0.0.0.0", port=port, reload=False)


