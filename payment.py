"""ABA KHQR payments through the khmer-system.com "ABA Merchant API".

Flow
  1. User opens an unpaid invoice and presses "Pay with ABA KHQR"
       -> POST /api/orders/{id}/pay/aba      (server calls /aba-api/generate-qr, stores payment_id on the order)
  2. The browser shows the card_image and polls
       -> POST /api/orders/{id}/pay/check    (server calls /aba-api/check-payment)
  3. status PAID and amount matches -> the order is marked paid, the plan is activated,
     and /aba-api/mark-credited is called (exactly-once on the provider side).

The Profile Key (api_key) is stored in system_settings and is only ever used server-side; it is never
sent to a browser. Everything is configured in Admin -> Payment.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone

import httpx
from fastapi import APIRouter, Depends, Form, HTTPException
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.auth import get_current_user, require_admin
from core.database import get_db
from core.models import AuditLog, HostingPlan, Notification, Order, Project, SystemSetting, User

router = APIRouter()

_DEFAULTS = {
    "pay_aba_enabled": "0",
    "pay_aba_base_url": "https://khmer-system.com",
    "pay_aba_merchant_id": "gSk5rq",
    "pay_aba_api_key": "",
    "pay_aba_fixed_username": "",  # if set, every QR credits this account instead of the customer's username
}
UNPAID = ("pending", "awaiting_confirm")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


async def load_pay_settings(db: AsyncSession) -> dict:
    rows = (await db.execute(select(SystemSetting).where(SystemSetting.key.in_(list(_DEFAULTS))))).scalars().all()
    stored = {r.key: (r.value or "") for r in rows}
    return {k: (stored.get(k) or d) for k, d in _DEFAULTS.items()}


def aba_ready(s: dict) -> bool:
    return s["pay_aba_enabled"] == "1" and bool(s["pay_aba_api_key"] and s["pay_aba_merchant_id"] and s["pay_aba_base_url"])


async def aba_enabled(db: AsyncSession) -> bool:
    return aba_ready(await load_pay_settings(db))


async def _save(db: AsyncSession, key: str, value: str):
    row = (await db.execute(select(SystemSetting).where(SystemSetting.key == key))).scalar_one_or_none()
    if row:
        row.value = value
    else:
        db.add(SystemSetting(key=key, value=value))


# ─── provider client ───────────────────────────────────────

class AbaError(Exception):
    def __init__(self, message: str, code: str = "", http: int = 502):
        super().__init__(message)
        self.code, self.http = code, http


async def aba_call(s: dict, endpoint: str, payload: dict | None = None) -> dict:
    """POST https://<base>/aba-api/<endpoint> with api_key + merchant_id. Raises AbaError."""
    url = f"{s['pay_aba_base_url'].rstrip('/')}/aba-api/{endpoint}"
    body = {"api_key": s["pay_aba_api_key"], "merchant_id": s["pay_aba_merchant_id"], **(payload or {})}
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            r = await client.post(url, json=body)
    except httpx.HTTPError:
        raise AbaError("Payment gateway unreachable", "GATEWAY_DOWN", 502)
    try:
        j = r.json()
    except ValueError:
        raise AbaError(f"Gateway returned an invalid response (HTTP {r.status_code})", "BAD_RESPONSE", 502)
    if r.status_code != 200 or not j.get("ok"):
        raise AbaError(str(j.get("error") or f"HTTP {r.status_code}"), str(j.get("code") or ""), r.status_code)
    return j


def _user_facing(e: AbaError) -> str:
    """Never leak provider internals (wallet balance, key problems) to customers."""
    if e.code in ("RATE_LIMITED", "DAILY_LIMIT_REACHED"):
        return "Too many payment requests, please try again in a moment."
    return "Payment is temporarily unavailable. Please try again later or contact support."


# ─── order helpers ─────────────────────────────────────────

async def mark_order_paid(db: AsyncSession, o: Order, actor: int | None = None, how: str = "manual") -> bool:
    """Idempotent: activates the plan once. Returns True only the first time."""
    await db.refresh(o)
    if o.status == "paid":
        return False
    o.status = "paid"
    o.paid_at = datetime.utcnow()
    if o.project_id and o.plan_id:
        p = await db.get(Project, o.project_id)
        plan = await db.get(HostingPlan, o.plan_id)
        if p and plan:
            p.plan_id = plan.id
            p.ram_mb, p.cpu, p.storage_gb = plan.ram_mb, plan.cpu, plan.storage_gb
            start = _now()
            cur = _aware(p.expires_at)
            if cur and cur > start:  # renewing before expiry extends from the current end date
                start = cur
            p.expires_at = (start + timedelta(days=30 * max(1, o.months or 1))).replace(tzinfo=None)
    db.add(Notification(user_id=o.user_id, title="Payment confirmed", body=f"Order #{o.id} paid. Plan activated."))
    db.add(AuditLog(user_id=actor, action=f"order_paid_{how}", detail=f"order={o.id} payment_id={o.payment_id or ''}"))
    await db.commit()
    return True


async def check_order_payment(db: AsyncSession, s: dict, o: Order, actor: int | None = None) -> dict:
    """Ask the provider about this order's QR and settle the order if it was paid."""
    if o.status == "paid":
        return {"status": "PAID", "paid": True, "project_id": o.project_id}
    if not o.payment_id:
        raise AbaError("No QR has been generated for this order", "NO_PAYMENT", 400)
    j = await aba_call(s, "check-payment", {"payment_id": o.payment_id})
    status = str(j.get("status", "PENDING")).upper()
    if status == "PAID" or j.get("paid") is True:
        paid_amount = float(j.get("amount") or 0)
        if abs(paid_amount - float(o.amount or 0)) > 0.009:
            db.add(AuditLog(user_id=actor, action="payment_amount_mismatch",
                            detail=f"order={o.id} expected={o.amount} got={paid_amount}"))
            await db.commit()
            return {"status": "MISMATCH", "paid": False,
                    "message": "Paid amount does not match the invoice. Contact support."}
        first = await mark_order_paid(db, o, actor, "aba")
        if first:
            try:  # tell the provider we credited it (exactly-once on their side)
                await aba_call(s, "mark-credited", {"payment_id": o.payment_id})
            except AbaError:
                pass
        return {"status": "PAID", "paid": True, "project_id": o.project_id}
    if status == "EXPIRED":
        o.payment_id, o.pay_data = None, None  # a fresh QR may be generated
        await db.commit()
        return {"status": "EXPIRED", "paid": False}
    return {"status": "PENDING", "paid": False}


def _own_order_checks(o: Order | None, user: User) -> Order:
    if not o or (o.user_id != user.id and user.role != "admin"):
        raise HTTPException(404, "Order not found")
    return o


# ─── customer API ──────────────────────────────────────────

@router.get("/api/payment/status")
async def payment_status(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return {"aba": await aba_enabled(db)}


@router.post("/api/orders/{order_id}/pay/aba")
async def pay_with_aba(order_id: int, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    o = _own_order_checks(await db.get(Order, order_id), user)
    if o.status not in UNPAID:
        raise HTTPException(400, "This order is not waiting for payment")
    if (o.amount or 0) <= 0:
        raise HTTPException(400, "Nothing to pay")
    s = await load_pay_settings(db)
    if not aba_ready(s):
        raise HTTPException(400, "ABA payment is not available right now")

    # Re-use a still-valid QR: every new QR costs money.
    if o.payment_id and o.pay_data:
        try:
            cached = json.loads(o.pay_data)
            exp = _aware(datetime.fromisoformat(cached["expires_at"].replace("Z", "+00:00"))) if cached.get("expires_at") else None
            if exp and exp > _now() + timedelta(seconds=15):
                return {"ok": True, "reused": True, **cached}
        except (ValueError, KeyError, TypeError):
            pass

    username = s["pay_aba_fixed_username"] or user.username
    try:
        j = await aba_call(s, "generate-qr", {"username": username, "amount": round(float(o.amount), 2)})
    except AbaError as e:
        print(f"[payment] generate-qr failed for order {o.id}: {e.code} {e}", flush=True)
        raise HTTPException(502 if e.http >= 500 else 400, _user_facing(e))
    data = {
        "payment_id": j.get("payment_id"),
        "card_image": j.get("card_image"),
        "qr_image": j.get("qr_image"),
        "qr_string": j.get("qr_string"),
        "pay_url": j.get("pay_url"),
        "amount": j.get("amount", o.amount),
        "currency": j.get("currency", "USD"),
        "expires_at": j.get("expires_at"),
    }
    if not data["payment_id"]:
        raise HTTPException(502, "Payment gateway returned no payment id")
    o.payment_id = str(data["payment_id"])
    o.pay_data = json.dumps(data)
    o.payment_method = "aba"
    db.add(AuditLog(user_id=user.id, action="aba_qr_created", detail=f"order={o.id} payment_id={o.payment_id}"))
    await db.commit()
    return {"ok": True, "reused": False, **data}


@router.post("/api/orders/{order_id}/pay/check")
async def pay_check(order_id: int, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    o = _own_order_checks(await db.get(Order, order_id), user)
    s = await load_pay_settings(db)
    if not aba_ready(s) and o.status != "paid":
        raise HTTPException(400, "ABA payment is not available right now")
    try:
        return {"ok": True, **(await check_order_payment(db, s, o, user.id))}
    except AbaError as e:
        if e.code == "NO_PAYMENT":
            raise HTTPException(400, str(e))
        if e.code == "NOT_FOUND":  # provider forgot it: let the user make a new QR
            o.payment_id, o.pay_data = None, None
            await db.commit()
            return {"ok": True, "status": "EXPIRED", "paid": False}
        print(f"[payment] check-payment failed for order {o.id}: {e.code} {e}", flush=True)
        raise HTTPException(502, "Could not check the payment right now, retrying…")


# ─── admin API ─────────────────────────────────────────────

@router.get("/api/admin/payment-settings")
async def admin_get_pay_settings(user: User = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    s = await load_pay_settings(db)
    out = {k: v for k, v in s.items() if k != "pay_aba_api_key"}
    out["pay_aba_api_key_set"] = bool(s["pay_aba_api_key"])
    out["ready"] = aba_ready(s)
    return out


@router.post("/api/admin/payment-settings")
async def admin_save_pay_settings(
    pay_aba_enabled: str = Form("0"), pay_aba_base_url: str = Form(""), pay_aba_merchant_id: str = Form(""),
    pay_aba_api_key: str = Form(""), pay_aba_fixed_username: str = Form(""),
    user: User = Depends(require_admin), db: AsyncSession = Depends(get_db),
):
    base = pay_aba_base_url.strip().rstrip("/") or _DEFAULTS["pay_aba_base_url"]
    if not re.match(r"^https://[A-Za-z0-9.-]+(:\d+)?$", base):
        raise HTTPException(400, "Base URL must look like https://khmer-system.com")
    mid = pay_aba_merchant_id.strip()
    if mid and not re.match(r"^[A-Za-z0-9_-]{3,40}$", mid):
        raise HTTPException(400, "Merchant ID looks wrong")
    values = {
        "pay_aba_enabled": "1" if pay_aba_enabled == "1" else "0",
        "pay_aba_base_url": base,
        "pay_aba_merchant_id": mid or _DEFAULTS["pay_aba_merchant_id"],
        "pay_aba_fixed_username": pay_aba_fixed_username.strip(),
    }
    if pay_aba_api_key.strip():  # blank = keep the saved key
        values["pay_aba_api_key"] = pay_aba_api_key.strip()
    for k, v in values.items():
        await _save(db, k, v)
    db.add(AuditLog(user_id=user.id, action="admin_payment_settings", detail=", ".join(sorted(values))))
    await db.commit()
    return {"ok": True}


@router.post("/api/admin/payment/test")
async def admin_test_payment(
    pay_aba_base_url: str = Form(""), pay_aba_merchant_id: str = Form(""), pay_aba_api_key: str = Form(""),
    user: User = Depends(require_admin), db: AsyncSession = Depends(get_db),
):
    """Checks key + merchant id with a read-only call (no QR is generated, nothing is charged)."""
    s = await load_pay_settings(db)
    if pay_aba_base_url.strip():
        s["pay_aba_base_url"] = pay_aba_base_url.strip().rstrip("/")
    if pay_aba_merchant_id.strip():
        s["pay_aba_merchant_id"] = pay_aba_merchant_id.strip()
    if pay_aba_api_key.strip():
        s["pay_aba_api_key"] = pay_aba_api_key.strip()
    if not s["pay_aba_api_key"]:
        raise HTTPException(400, "Enter the Profile Key first")
    if not re.match(r"^https://", s["pay_aba_base_url"]):
        raise HTTPException(400, "Base URL must start with https://")
    try:
        j = await aba_call(s, "transactions", {"limit": 1})
    except AbaError as e:
        raise HTTPException(400, f"{e} ({e.code or e.http})")
    return {"ok": True, "message": "Connection OK", "count": j.get("count", 0)}


@router.get("/api/admin/payment/transactions")
async def admin_pay_transactions(status: str = "", limit: int = 50, user: User = Depends(require_admin),
                                 db: AsyncSession = Depends(get_db)):
    """Local ABA orders + (when configured) the provider's own transaction list."""
    s = await load_pay_settings(db)
    orders = (await db.execute(
        select(Order, User.email).join(User, User.id == Order.user_id)
        .where(Order.payment_method == "aba").order_by(desc(Order.created_at)).limit(min(max(limit, 1), 200))
    )).all()
    local = [{
        "order_id": o.id, "email": email, "amount": o.amount, "status": o.status, "payment_id": o.payment_id,
        "created_at": o.created_at.isoformat() if o.created_at else None,
        "paid_at": o.paid_at.isoformat() if o.paid_at else None,
    } for o, email in orders]
    remote, remote_error = [], None
    if s["pay_aba_api_key"]:
        try:
            payload = {"limit": min(max(limit, 1), 200)}
            if status.upper() in ("PENDING", "PAID", "EXPIRED"):
                payload["status"] = status.upper()
            remote = (await aba_call(s, "transactions", payload)).get("transactions", [])
        except AbaError as e:
            remote_error = f"{e} ({e.code or e.http})"
    return {"local": local, "remote": remote, "remote_error": remote_error}


@router.post("/api/admin/payment/orders/{order_id}/check")
async def admin_recheck(order_id: int, user: User = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    o = await db.get(Order, order_id)
    if not o:
        raise HTTPException(404)
    s = await load_pay_settings(db)
    try:
        return {"ok": True, **(await check_order_payment(db, s, o, user.id))}
    except AbaError as e:
        raise HTTPException(400, f"{e} ({e.code or e.http})")
