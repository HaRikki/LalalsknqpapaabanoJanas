"""Cloudflare Turnstile human verification + signed session cookie."""
from __future__ import annotations

import hashlib
import hmac
import time
from typing import Optional

import httpx
from fastapi import Request

from core.config import (
    SECRET_KEY,
    TURNSTILE_SITE_KEY,
    TURNSTILE_SECRET_KEY,
    HUMAN_VERIFY_ENABLED,
    HUMAN_COOKIE_NAME,
    HUMAN_COOKIE_HOURS,
)

TURNSTILE_VERIFY_URL = "https://challenges.cloudflare.com/turnstile/v0/siteverify"

# Simple in-memory rate limit: ip -> list of timestamps
_rate: dict[str, list[float]] = {}
RATE_WINDOW = 60.0
RATE_MAX = 20  # max verify attempts per minute per IP


def is_enabled() -> bool:
    return bool(HUMAN_VERIFY_ENABLED and TURNSTILE_SITE_KEY and TURNSTILE_SECRET_KEY)


def _sign(payload: str) -> str:
    return hmac.new(SECRET_KEY.encode(), payload.encode(), hashlib.sha256).hexdigest()


def make_human_cookie_value() -> str:
    """payload = exp_ts.signature"""
    exp = int(time.time()) + max(1, HUMAN_COOKIE_HOURS) * 3600
    body = f"1.{exp}"
    return f"{body}.{_sign(body)}"


def validate_human_cookie(value: Optional[str]) -> bool:
    if not value:
        return False
    parts = value.split(".")
    if len(parts) != 3:
        return False
    flag, exp_s, sig = parts
    if flag != "1":
        return False
    try:
        exp = int(exp_s)
    except ValueError:
        return False
    if exp < int(time.time()):
        return False
    body = f"{flag}.{exp_s}"
    expected = _sign(body)
    return hmac.compare_digest(expected, sig)


def rate_limit_ok(ip: str) -> bool:
    now = time.time()
    bucket = _rate.get(ip) or []
    bucket = [t for t in bucket if now - t < RATE_WINDOW]
    if len(bucket) >= RATE_MAX:
        _rate[ip] = bucket
        return False
    bucket.append(now)
    _rate[ip] = bucket
    return True


async def verify_turnstile_token(token: str, remoteip: Optional[str] = None) -> tuple[bool, str]:
    """Call Cloudflare siteverify. Returns (ok, error_message)."""
    if not TURNSTILE_SECRET_KEY:
        return False, "Turnstile is not configured"
    if not token or len(token) < 10:
        return False, "Missing verification token"
    data = {
        "secret": TURNSTILE_SECRET_KEY,
        "response": token,
    }
    if remoteip:
        data["remoteip"] = remoteip
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.post(TURNSTILE_VERIFY_URL, data=data)
            result = r.json()
    except Exception as e:
        return False, f"Verification service error: {e}"
    if result.get("success"):
        return True, ""
    codes = result.get("error-codes") or []
    return False, "Verification failed: " + (", ".join(codes) if codes else "invalid token")


# Paths that skip human gate (static, health, verify itself, optional webhooks)
SKIP_PREFIXES = (
    "/static/",
    "/api/verify/",
    "/health",
    "/favicon",
)

SKIP_EXACT = {
    "/verify",
    "/api/docs",
    "/openapi.json",
}


def should_skip_path(path: str) -> bool:
    if path in SKIP_EXACT:
        return True
    for p in SKIP_PREFIXES:
        if path.startswith(p) or path == p.rstrip("/"):
            return True
    return False


def request_has_human(request: Request) -> bool:
    return validate_human_cookie(request.cookies.get(HUMAN_COOKIE_NAME))
