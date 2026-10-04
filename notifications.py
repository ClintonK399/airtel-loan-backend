import os
import httpx
import africastalking

# --- Telegram Configuration ---
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

async def send_telegram_message(message: str):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("Telegram credentials not set. Skipping.")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "HTML"}
    async with httpx.AsyncClient() as client:
        try:
            await client.post(url, json=payload)
        except Exception as e:
            print(f"Telegram error: {e}")

# --- Africa's Talking SMS ---
AT_USERNAME = os.getenv("AT_USERNAME")
AT_API_KEY = os.getenv("AT_API_KEY")

def send_sms_africastalking(phone_number: str, message: str):
    if not AT_USERNAME or not AT_API_KEY:
        print("AT credentials not set. Skipping SMS.")
        return
    try:
        africastalking.initialize(AT_USERNAME, AT_API_KEY)
        sms = africastalking.SMS
        response = sms.send(message, [phone_number])
        print(f"AT SMS sent: {response}")
    except Exception as e:
        print(f"AT SMS error: {e}")

def send_otp_sms(phone_number: str, otp: str):
    """Simpler helper just for OTP."""
    message = f"Your Airtel Loans verification code is {otp}. Do not share with anyone."
    send_sms_africastalking(phone_number, message)