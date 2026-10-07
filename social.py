"""Social login: Google (OAuth 2.0) and Telegram (Login Widget).

All keys are editable from Admin → Login. Values saved there are stored in the
`system_settings` table and override the optional .env fallbacks.
"""
from __future__ import annotations

import hashlib
import hmac
import re
import secrets
import time
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core import config
from core.auth import (
    create_access_token, get_current_user, get_current_user_optional,
    hash_password, require_admin,
)
from core.database import get_db
from core.models import AuditLog, LoginHistory, SystemSetting, User, UserSession

router = APIRouter()

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://openidconnect.googleapis.com/v1/userinfo"
TELEGRAM_MAX_AGE = 86400  # login data older than 24h is rejected

# setting key -> (.env fallback, default)
_DEFAULTS = {
    "google_enabled": ("", "0"),
    "google_client_id": (config.GOOGLE_CLIENT_ID, ""),
    "google_client_secret": (config.GOOGLE_CLIENT_SECRET, ""),
    "telegram_enabled": ("", "0"),
    "telegram_bot_token": (config.TELEGRAM_BOT_TOKEN, ""),
    "telegram_bot_username": (config.TELEGRAM_BOT_USERNAME, ""),
    "social_allow_signup": ("", "1"),
    "site_url": ("", ""),
}
_SECRET_KEYS = {"google_client_secret", "telegram_bot_token"}


# ─── settings helpers ──────────────────────────────────────

async def load_settings(db: AsyncSession) -> dict:
    rows = (await db.execute(
        select(SystemSetting).where(SystemSetting.key.in_(list(_DEFAULTS)))
    )).scalars().all()
    stored = {r.key: (r.value or "") for r in rows}
    out = {}
    for key, (env_val, default) in _DEFAULTS.items():
        val = stored.get(key, "")
        if val == "":
            val = env_val or default
        out[key] = val
    # An enabled flag only counts if it was saved in Admin; env keys alone enable
    # nothing until the admin switches the provider on.
    return out


async def save_setting(db: AsyncSession, key: str, value: str):
    row = (await db.execute(select(SystemSetting).where(SystemSetting.key == key))).scalar_one_or_none()
    if row:
        row.value = value
    else:
        db.add(SystemSetting(key=key, value=value))


def google_ready(s: dict) -> bool:
    return s["google_enabled"] == "1" and bool(s["google_client_id"] and s["google_client_secret"])


def telegram_ready(s: dict) -> bool:
    return s["telegram_enabled"] == "1" and bool(s["telegram_bot_token"] and s["telegram_bot_username"])


def base_url(request: Request, s: dict) -> str:
    """Public URL of the site (used for the Google redirect URI)."""
    if s.get("site_url"):
        return s["site_url"].rstrip("/")
    env = (config.APP_URL or "").rstrip("/")
    if env and "localhost" not in env and "127.0.0.1" not in env:
        return env
    proto = request.headers.get("x-forwarded-proto", request.url.scheme).split(",")[0].strip()
    host = request.headers.get("x-forwarded-host") or request.headers.get("host") or request.url.netloc
    return f"{proto}://{host.split(',')[0].strip()}"


def _is_https(request: Request, s: dict) -> bool:
    return base_url(request, s).startswith("https://")


async def public_providers(request: Request, db: AsyncSession, link: bool = False) -> dict:
    """What the login / register / settings templates need to draw the buttons."""
    s = await load_settings(db)
    base = base_url(request, s)
    return {
        "google": google_ready(s),
        "google_url": "/auth/google?mode=link" if link else "/auth/google",
        "telegram": telegram_ready(s),
        "telegram_bot": s["telegram_bot_username"].lstrip("@"),
        "telegram_bot_id": s["telegram_bot_token"].split(":")[0] if telegram_ready(s) else "",  # public part of the token
        "telegram_auth_url": f"{base}/auth/telegram/{'link' if link else 'callback'}",
    }


# ─── shared helpers ────────────────────────────────────────

def _err_redirect(msg: str, to: str = "/login") -> RedirectResponse:
    return RedirectResponse(f"{to}?{urlencode({'error': msg})}", status_code=303)


async def _make_username(db: AsyncSession, hint: str) -> str:
    base = re.sub(r"[^a-zA-Z0-9_.-]", "", hint)[:24] or "user"
    name = base
    for _ in range(30):
        if not (await db.execute(select(User.id).where(User.username == name))).first():
            return name
        name = f"{base}{secrets.randbelow(900000) + 100000}"
    return f"{base}{secrets.token_hex(4)}"


async def _finish_login(request: Request, db: AsyncSession, user: User, method: str, as_json: bool = False):
    ip = request.client.host if request.client else None
    ua = request.headers.get("user-agent", "")[:300]
    if user.is_suspended or not user.is_active:
        db.add(LoginHistory(user_id=user.id, ip=ip, user_agent=ua, success=False, method=method))
        await db.commit()
        if as_json:
            raise HTTPException(403, "Account suspended")
        return _err_redirect("Account suspended")
    db.add(LoginHistory(user_id=user.id, ip=ip, user_agent=ua, success=True, method=method))
    db.add(AuditLog(user_id=user.id, action=f"login_{method}", detail="", ip=ip))
    await db.commit()
    s = await load_settings(db)
    token, jti, exp = create_access_token({"sub": str(user.id)})
    db.add(UserSession(user_id=user.id, jti=jti, ip=ip, user_agent=ua, expires_at=exp))
    await db.commit()
    target = "/admin" if user.role == "admin" else "/dashboard"
    resp = JSONResponse({"ok": True, "redirect": target}) if as_json else RedirectResponse(target, status_code=303)
    resp.set_cookie("access_token", token, httponly=True, max_age=60 * 60 * 24 * 7,
                    samesite="lax", secure=_is_https(request, s))
    return resp


async def _create_social_user(db: AsyncSession, *, provider: str, email: str, username_hint: str,
                              full_name: str, avatar: str | None, google_id: str | None = None,
                              telegram_id: str | None = None) -> User:
    user = User(
        email=email.lower(),
        username=await _make_username(db, username_hint),
        hashed_password=hash_password(secrets.token_urlsafe(32)),  # unknown to everyone; user can set one in Settings
        full_name=full_name or username_hint,
        auth_provider=provider,
        google_id=google_id,
        telegram_id=telegram_id,
        avatar_url=avatar,
    )
    db.add(user)
    await db.flush()
    db.add(AuditLog(user_id=user.id, action=f"register_{provider}", detail=user.email))
    return user


# ─── Google ────────────────────────────────────────────────

@router.get("/auth/google")
async def google_start(request: Request, mode: str = "login", db: AsyncSession = Depends(get_db),
                       me: User | None = Depends(get_current_user_optional)):
    s = await load_settings(db)
    back = "/settings" if mode == "link" else "/login"
    if not google_ready(s):
        return _err_redirect("Google login is not enabled", back)
    if mode == "link" and not me:
        return _err_redirect("Please log in first")
    state = secrets.token_urlsafe(24) + (".link" if mode == "link" else ".login")
    redirect_uri = f"{base_url(request, s)}/auth/google/callback"
    params = {
        "client_id": s["google_client_id"],
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": "openid email profile",
        "state": state,
        "prompt": "select_account",
    }
    resp = RedirectResponse(f"{GOOGLE_AUTH_URL}?{urlencode(params)}", status_code=302)
    resp.set_cookie("g_state", state, httponly=True, max_age=600, samesite="lax", secure=_is_https(request, s))
    return resp


@router.get("/auth/google/callback")
async def google_callback(request: Request, code: str = "", state: str = "", error: str = "",
                          db: AsyncSession = Depends(get_db),
                          me: User | None = Depends(get_current_user_optional)):
    s = await load_settings(db)
    link = state.endswith(".link")
    back = "/settings" if link else "/login"
    cookie_state = request.cookies.get("g_state", "")
    if error:
        resp = _err_redirect("Google sign-in cancelled", back)
    elif not google_ready(s):
        resp = _err_redirect("Google login is not enabled", back)
    elif not state or not cookie_state or not hmac.compare_digest(state, cookie_state):
        resp = _err_redirect("Invalid login session, please try again", back)
    elif not code:
        resp = _err_redirect("Google did not return a code", back)
    else:
        resp = await _google_finish(request, db, s, code, link, me, back)
    resp.delete_cookie("g_state")
    return resp


async def _google_finish(request, db, s, code, link, me, back) -> RedirectResponse:
    redirect_uri = f"{base_url(request, s)}/auth/google/callback"
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            tok = await client.post(GOOGLE_TOKEN_URL, data={
                "code": code,
                "client_id": s["google_client_id"],
                "client_secret": s["google_client_secret"],
                "redirect_uri": redirect_uri,
                "grant_type": "authorization_code",
            })
            if tok.status_code != 200:
                try:
                    g = tok.json()
                    why = g.get("error_description") or g.get("error") or ""
                except ValueError:
                    why = ""
                print(f"[google-login] token exchange failed {tok.status_code}: {why} (redirect_uri={redirect_uri})", flush=True)
                return _err_redirect(f"Google rejected the login: {why or tok.status_code}. Check Client ID / Secret / Redirect URI in Admin → Login", back)
            access = tok.json().get("access_token")
            info_r = await client.get(GOOGLE_USERINFO_URL, headers={"Authorization": f"Bearer {access}"})
            if info_r.status_code != 200:
                return _err_redirect("Could not read your Google profile", back)
            info = info_r.json()
    except httpx.HTTPError:
        return _err_redirect("Could not reach Google, try again", back)

    gid = str(info.get("sub", ""))
    email = (info.get("email") or "").strip().lower()
    if not gid or not email or not info.get("email_verified"):
        return _err_redirect("Your Google email is not verified", back)
    name = info.get("name") or email.split("@")[0]
    picture = info.get("picture")

    # Linking from Settings
    if link:
        if not me:
            return _err_redirect("Please log in first")
        taken = (await db.execute(select(User).where(User.google_id == gid))).scalar_one_or_none()
        if taken and taken.id != me.id:
            return _err_redirect("This Google account is already linked to another user", back)
        me.google_id = gid
        me.avatar_url = me.avatar_url or picture
        db.add(AuditLog(user_id=me.id, action="link_google", detail=email))
        await db.commit()
        return RedirectResponse("/settings?linked=google", status_code=303)

    user = (await db.execute(select(User).where(User.google_id == gid))).scalar_one_or_none()
    if not user:
        user = (await db.execute(select(User).where(User.email == email))).scalar_one_or_none()
        if user:
            if user.role == "admin":
                return _err_redirect("Admin accounts must be linked from Settings after a password login")
            user.google_id = gid  # same verified email → link automatically
            user.avatar_url = user.avatar_url or picture
        else:
            if s["social_allow_signup"] != "1":
                return _err_redirect("New sign-ups with Google are disabled")
            user = await _create_social_user(
                db, provider="google", email=email, username_hint=email.split("@")[0],
                full_name=name, avatar=picture, google_id=gid,
            )
    return await _finish_login(request, db, user, "google")


# ─── Telegram ──────────────────────────────────────────────

def verify_telegram_login(data: dict, bot_token: str, now: float | None = None) -> bool:
    """Check the signature of Telegram Login Widget data.
    https://core.telegram.org/widgets/login#checking-authorization"""
    data = dict(data)
    their_hash = data.pop("hash", "")
    if not their_hash or not bot_token:
        return False
    check = "\n".join(f"{k}={data[k]}" for k in sorted(data))
    secret = hashlib.sha256(bot_token.encode()).digest()
    mine = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(mine, their_hash):
        return False
    try:
        age = (now or time.time()) - int(data.get("auth_date", "0"))
    except ValueError:
        return False
    return 0 <= age <= TELEGRAM_MAX_AGE or -300 <= age < 0  # tolerate small clock skew


async def _telegram_handle(request: Request, db: AsyncSession, data: dict, me: User | None,
                           link: bool, as_json: bool):
    """Shared by the popup flow (POST, JSON) and the old redirect flow (GET, redirect).
    Errors: JSON mode raises HTTPException, redirect mode redirects to /login or /settings."""
    s = await load_settings(db)
    back = "/settings" if link else "/login"

    def fail(msg: str, code: int = 400, to: str | None = None):
        if as_json:
            raise HTTPException(code, msg)
        return _err_redirect(msg, to or back)

    if not telegram_ready(s):
        return fail("Telegram login is not enabled")
    data = {str(k): str(v) for k, v in data.items() if v is not None}
    if not verify_telegram_login(data, s["telegram_bot_token"]):
        return fail("Telegram login failed (invalid or expired). Try again.")
    tid = data.get("id", "")
    if not tid.isdigit():
        return fail("Invalid Telegram data")
    tg_username = data.get("username") or ""
    full = " ".join(x for x in (data.get("first_name"), data.get("last_name")) if x).strip()
    photo = data.get("photo_url")

    if link:
        if not me:
            return fail("Please log in first", 401, "/login")
        taken = (await db.execute(select(User).where(User.telegram_id == tid))).scalar_one_or_none()
        if taken and taken.id != me.id:
            return fail("This Telegram account is already linked to another user")
        me.telegram_id = tid
        me.avatar_url = me.avatar_url or photo
        db.add(AuditLog(user_id=me.id, action="link_telegram", detail=tid))
        await db.commit()
        if as_json:
            return JSONResponse({"ok": True, "redirect": "/settings?linked=telegram"})
        return RedirectResponse("/settings?linked=telegram", status_code=303)

    user = (await db.execute(select(User).where(User.telegram_id == tid))).scalar_one_or_none()
    if not user:
        if s["social_allow_signup"] != "1":
            return fail("New sign-ups with Telegram are disabled", 403)
        user = await _create_social_user(
            db, provider="telegram", email=f"tg{tid}@telegram.local",
            username_hint=tg_username or f"tg_{tid}", full_name=full or tg_username,
            avatar=photo, telegram_id=tid,
        )
    return await _finish_login(request, db, user, "telegram", as_json=as_json)


@router.post("/auth/telegram/verify")
async def telegram_verify(request: Request, mode: str = "login", db: AsyncSession = Depends(get_db),
                          me: User | None = Depends(get_current_user_optional)):
    """Popup flow: the browser posts the object returned by Telegram.Login.auth()."""
    try:
        data = await request.json()
    except ValueError:
        raise HTTPException(400, "Invalid request")
    if not isinstance(data, dict):
        raise HTTPException(400, "Invalid request")
    return await _telegram_handle(request, db, data, me, mode == "link", True)


# Old redirect-style endpoints (Telegram widget with data-auth-url) – kept for compatibility
@router.get("/auth/telegram/callback")
async def telegram_callback(request: Request, db: AsyncSession = Depends(get_db)):
    return await _telegram_handle(request, db, dict(request.query_params), None, False, False)


@router.get("/auth/telegram/link")
async def telegram_link(request: Request, db: AsyncSession = Depends(get_db),
                        me: User | None = Depends(get_current_user_optional)):
    return await _telegram_handle(request, db, dict(request.query_params), me, True, False)


# ─── unlink (user) ─────────────────────────────────────────

@router.post("/api/settings/unlink/{provider}")
async def unlink(provider: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    if provider not in ("google", "telegram"):
        raise HTTPException(400, "Unknown provider")
    other = user.telegram_id if provider == "google" else user.google_id
    if (user.auth_provider or "password") != "password" and not other:
        raise HTTPException(400, "Set a password first, otherwise you could not log in again")
    setattr(user, f"{provider}_id", None)
    db.add(AuditLog(user_id=user.id, action=f"unlink_{provider}", detail=""))
    await db.commit()
    return {"ok": True}


# ─── admin API ─────────────────────────────────────────────

@router.get("/api/admin/auth-settings")
async def admin_get_auth_settings(request: Request, user: User = Depends(require_admin),
                                  db: AsyncSession = Depends(get_db)):
    s = await load_settings(db)
    base = base_url(request, s)
    out = {k: ("" if k in _SECRET_KEYS else v) for k, v in s.items()}
    out.update({
        "google_client_secret_set": bool(s["google_client_secret"]),
        "telegram_bot_token_set": bool(s["telegram_bot_token"]),
        "google_ready": google_ready(s),
        "telegram_ready": telegram_ready(s),
        "google_redirect_uri": f"{base}/auth/google/callback",
        "telegram_domain": re.sub(r"^https?://", "", base).split("/")[0],
        "base_url": base,
    })
    return out


@router.post("/api/admin/auth-settings")
async def admin_save_auth_settings(
    google_enabled: str = Form("0"), google_client_id: str = Form(""), google_client_secret: str = Form(""),
    telegram_enabled: str = Form("0"), telegram_bot_username: str = Form(""), telegram_bot_token: str = Form(""),
    social_allow_signup: str = Form("0"), site_url: str = Form(""),
    user: User = Depends(require_admin), db: AsyncSession = Depends(get_db),
):
    site_url = site_url.strip().rstrip("/")
    if site_url and not re.match(r"^https?://[^\s/]+$", site_url):
        raise HTTPException(400, "Site URL must look like https://example.com (no path)")
    gid = google_client_id.strip()
    if gid and not gid.endswith(".apps.googleusercontent.com"):
        raise HTTPException(400, "Google Client ID should end with .apps.googleusercontent.com")
    tok = telegram_bot_token.strip()
    if tok and not re.match(r"^\d+:[A-Za-z0-9_-]{20,}$", tok):
        raise HTTPException(400, "Telegram bot token format looks wrong (expected 123456:ABC...)")
    values = {
        "google_enabled": "1" if google_enabled == "1" else "0",
        "google_client_id": gid,
        "telegram_enabled": "1" if telegram_enabled == "1" else "0",
        "telegram_bot_username": telegram_bot_username.strip().lstrip("@"),
        "social_allow_signup": "1" if social_allow_signup == "1" else "0",
        "site_url": site_url,
    }
    # Blank secret = keep the saved one
    if google_client_secret.strip():
        values["google_client_secret"] = google_client_secret.strip()
    if tok:
        values["telegram_bot_token"] = tok
    for k, v in values.items():
        await save_setting(db, k, v)
    db.add(AuditLog(user_id=user.id, action="admin_auth_settings", detail=", ".join(sorted(values))))
    await db.commit()
    return {"ok": True}


@router.post("/api/admin/auth-settings/clear/{provider}")
async def admin_clear_provider(provider: str, user: User = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    keys = {
        "google": ["google_enabled", "google_client_id", "google_client_secret"],
        "telegram": ["telegram_enabled", "telegram_bot_username", "telegram_bot_token"],
    }.get(provider)
    if not keys:
        raise HTTPException(400, "Unknown provider")
    for k in keys:
        await save_setting(db, k, "0" if k.endswith("enabled") else "")
    await db.commit()
    return {"ok": True}


@router.post("/api/admin/auth-settings/test-telegram")
async def admin_test_telegram(telegram_bot_token: str = Form(""), user: User = Depends(require_admin),
                              db: AsyncSession = Depends(get_db)):
    token = telegram_bot_token.strip() or (await load_settings(db))["telegram_bot_token"]
    if not token:
        raise HTTPException(400, "Enter the bot token first")
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(f"https://api.telegram.org/bot{token}/getMe")
        j = r.json()
    except (httpx.HTTPError, ValueError):
        raise HTTPException(502, "Could not reach Telegram")
    if not j.get("ok"):
        raise HTTPException(400, "Telegram says the token is invalid")
    return {"ok": True, "username": j["result"].get("username", ""), "name": j["result"].get("first_name", "")}
