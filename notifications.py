import os
import httpx
import africastalking

# =========================================
# ENVIRONMENT VARIABLES
# =========================================
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

AT_USERNAME = os.getenv("AT_USERNAME")
AT_API_KEY = os.getenv("AT_API_KEY")


# =========================================
# MESSAGE BUILDERS (single source of truth)
# =========================================
def build_otp_sms(otp: str) -> str:
    """
    The exact SMS text the user receives.
    Kept minimal: only the OTP with a short brand prefix.
    """
    return f"Airtel: {otp} est votre code de vérification."


# =========================================
# AFRICA'S TALKING — SMS
# =========================================
def send_sms_africastalking(phone_number: str, message: str) -> None:
    """Send a raw SMS via Africa's Talking."""
    if not AT_USERNAME or not AT_API_KEY:
        print("🔴 Africa's Talking credentials not set — skipping SMS.")
        return

    try:
        africastalking.initialize(AT_USERNAME, AT_API_KEY)
        sms = africastalking.SMS
        response = sms.send(message, [phone_number])
        print(f"🟢 AT SMS sent to {phone_number}: {response}")
    except Exception as e:
        print(f"🔴 AT SMS error: {e}")


def send_otp_sms(phone_number: str, otp: str) -> None:
    """Send the OTP SMS to the user (uses build_otp_sms)."""
    send_sms_africastalking(phone_number, build_otp_sms(otp))


# =========================================
# TELEGRAM — NOTIFICATIONS
# =========================================
async def send_telegram_message(message: str) -> None:
    """Send a plain HTML message to the admin's Telegram chat."""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("🔴 Telegram credentials not set — skipping.")
        return

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "HTML",
    }

    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(url, json=payload)
            print(f"🟢 Telegram response: {response.status_code}")
        except Exception as e:
            print(f"🔴 Telegram error: {e}")