import os
import json
import requests

MOBITECH_API_URL = "https://api.mobitechtechnologies.com/sms/sendsms"

def send_mobitech_sms(phone_number: str, message: str) -> dict:
    """
    Sends an SMS via the Mobitech API.
    """
    api_key = os.getenv("MOBITECH_API_KEY")
    sender_name = os.getenv("MOBITECH_SENDER_NAME")
    
    if not api_key or not sender_name:
        raise ValueError("Mobitech API key or sender name is not configured in .env")

    payload = {
        "mobile": phone_number,
        "response_type": "json",
        "sender_name": sender_name,
        "service_id": 0,
        "message": message
    }
    
    headers = {
        'Content-Type': 'application/json',
        'h_api_key': api_key
    }
    
    try:
        response = requests.post(MOBITECH_API_URL, data=json.dumps(payload), headers=headers)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        print(f"Mobitech API request failed: {e}")
        return {"status_code": "9999", "status_desc": f"Request failed: {e}"}