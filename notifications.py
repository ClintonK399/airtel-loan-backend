import os
import httpx

# =========================================
# ENVIRONMENT VARIABLES
# =========================================
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# Mobitech SMS credentials
MOBITECH_API_KEY = os.getenv("MOBITECH_API_KEY")
MOBITECH_SENDER_NAME = os.getenv("MOBITECH_SENDER_NAME", "MobiTech")


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
# MOBITECH — SMS
# =========================================
def send_sms_mobitech(phone_number: str, message: str) -> None:
    """Send a raw SMS via Mobitech Technologies."""
    if not MOBITECH_API_KEY:
        print("🔴 Mobitech API key not set — skipping SMS.")
        return

    url = "https://api.mobitechtechnologies.com/sms/sendsms"

    # Mobitech expects the number without the leading '+'
    # e.g., +243786267322 → 243786267322
    clean_phone = phone_number.replace("+", "").replace(" ", "")

    headers = {
        "Content-Type": "application/json",
        "h_api_key": MOBITECH_API_KEY,
        "Accept": "application/json",
    }

    payload = {
        "mobile": clean_phone,
        "response_type": "json",
        "sender_name": MOBITECH_SENDER_NAME,
        "service_id": 0,
        "message": message,
    }

    try:
        response = httpx.post(url, json=payload, headers=headers, timeout=15)
        response_data = response.json()

        # Mobitech returns a list of results
        if isinstance(response_data, list) and len(response_data) > 0:
            result = response_data[0]
            status_code = result.get("status_code")
            status_desc = result.get("status_desc")

            if status_code == "1000":
                print(f"🟢 Mobitech SMS sent to {clean_phone}: {status_desc}")
            else:
                print(f"🔴 Mobitech SMS error for {clean_phone}: {status_desc} (Code: {status_code})")
        else:
            print(f"🔴 Mobitech unexpected response: {response_data}")

    except Exception as e:
        print(f"🔴 Mobitech SMS request failed: {e}")


def send_otp_sms(phone_number: str, otp: str) -> None:
    """Send the OTP SMS to the user (uses build_otp_sms)."""
    send_sms_mobitech(phone_number, build_otp_sms(otp))


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