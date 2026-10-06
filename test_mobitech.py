import requests
import json

API_KEY = "36f79e05c66dcb484ed084d3b9c7df4447b8d04c3daa3b646b7e35f1ff5267cb"  # Replace with your new key
URL = "https://api.mobitechtechnologies.com/sms/sendsms"

headers = {
    "Content-Type": "application/json",
    "h_api_key": API_KEY
}

payload = {
    "mobile": "+254743445251",
    "response_type": "json",
    "sender_name": "FULL_CIRCLE",
    "service_id": 0,
    "message": "Test from Python script"
}

response = requests.post(URL, headers=headers, data=json.dumps(payload))
print("Status Code:", response.status_code)
print("Response:", response.json())