import os
import httpx
import asyncio
from fastapi import BackgroundTasks
import africastalking
from twilio.rest import Client
from dotenv import load_dotenv

# Ensure environment variables are loaded
load_dotenv()

# --- Telegram Configuration ---
# Fix: Pass the variable name, not the token string
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

async def send_telegram_message(message: str):
    """Sends an async notification to the configured Telegram chat."""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("Telegram credentials not set. Skipping.")
        return
        
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "HTML"}
    
    async with httpx.AsyncClient() as client:
        try:
            await client.post(url, json=payload, timeout=10.0)
            print("Telegram message sent successfully.")
        except Exception as e:
            print(f"Telegram error: {e}")

# --- Africa's Talking SMS Configuration ---
AT_USERNAME = os.getenv("AT_USERNAME")
AT_API_KEY = os.getenv("AT_API_KEY")

def send_sms_africastalking(phone_number: str, message: str):
    """Sends an SMS using Africa's Talking SDK."""
    if not AT_USERNAME or not AT_API_KEY:
        print("Africa's Talking credentials not set. Skipping SMS.")
        return
        
    africastalking.initialize(AT_USERNAME, AT_API_KEY)
    sms = africastalking.SMS
    
    try:
        # Phone number must be in international format (+254...)
        response = sms.send(message, [phone_number])
        print(f"AT SMS sent: {response}")
    except Exception as e:
        print(f"AT SMS error: {e}")

# --- Twilio SMS Configuration ---
# Fix: Pass the variable names here as well
TWILIO_SID = os.getenv("TWILIO_ACCOUNT_SID") 
TWILIO_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")
TWILIO_PHONE = os.getenv("TWILIO_PHONE_NUMBER")

def send_sms_twilio(phone_number: str, message: str):
    """Sends an SMS using the Twilio SDK."""
    if not all([TWILIO_SID, TWILIO_TOKEN, TWILIO_PHONE]):
        print("Twilio credentials not set. Skipping SMS.")
        return
        
    client = Client(TWILIO_SID, TWILIO_TOKEN)
    try:
        message = client.messages.create(body=message, from_=TWILIO_PHONE, to=phone_number)
        print(f"Twilio SMS sent: {message.sid}")
    except Exception as e:
        print(f"Twilio SMS error: {e}")

# --- Unified Dispatcher ---
def dispatch_notifications(phone_number: str, sms_message: str, tg_message: str):
    """
    A synchronous wrapper to run all notification tasks.
    Designed to be passed to FastAPI's BackgroundTasks.
    """
    # Send SMS (choose your provider)
    send_sms_africastalking(phone_number, sms_message)
    # send_sms_twilio(phone_number, sms_message)

    # Send Telegram Alert
    try:
        asyncio.run(send_telegram_message(tg_message))
    except Exception as e:
        print(f"Failed to send Telegram in background: {e}")