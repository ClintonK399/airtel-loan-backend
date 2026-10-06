import os
import json
import requests

MOBITECH_API_URL = "https://api.mobitechtechnologies.com/sms/sendsms"

def send_mobitech_sms(phone_number: str, message: str) -> dict:
    """
    Sends an SMS via the Mobitech API.
    """
    # Retrieve and strip any accidental whitespace from environment variables
    api_key = os.getenv("MOBITECH_API_KEY", "").strip()
    sender_name = os.getenv("MOBITECH_SENDER_NAME", "").strip()
    
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
    
    # --- DEBUG: Print what we are sending ---
    print("=== MOBITECH REQUEST DEBUG ===")
    print(f"API Key: '{api_key}'")
    print(f"Sender Name: '{sender_name}'")
    print(f"Payload: {json.dumps(payload, indent=2)}")
    print(f"Headers: {headers}")
    print("==============================")
    # ----------------------------------------
    
    try:
        response = requests.post(MOBITECH_API_URL, data=json.dumps(payload), headers=headers)
        response.raise_for_status()
        
        # Try to parse JSON, but log raw text if it fails
        try:
            result = response.json()
        except json.JSONDecodeError:
            print(f"Mobitech API returned non-JSON response: {response.text}")
            return {"status_code": "9998", "status_desc": "Invalid JSON response from API"}
            
        # Log the full response for debugging
        print(f"Mobitech API Response: {result}")
        return result
        
    except requests.exceptions.RequestException as e:
        print(f"Mobitech API request failed: {e}")
        return {"status_code": "9999", "status_desc": f"Request failed: {e}"}