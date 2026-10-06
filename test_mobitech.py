import requests
import json

api_key = "e2b58aebc76321ed84d5eda39951fd5bc854264bedd9377f5e7c56bb7df8d6d2"  # Replace with your actual key

url = "https://api.mobitechtechnologies.com/sms/sendsms"

headers = {
    "Content-Type": "application/json",
    "h_api_key": api_key,
    "Accept": "application/json"
}

payload = {
    "mobile": "243989894439",
    "response_type": "json",
    "sender_name": "MobiTech",
    "service_id": 0,
    "message": "Test message from Python script"
}

try:
    response = requests.post(url, headers=headers, json=payload, timeout=15)
    print("Status Code:", response.status_code)
    print("Response Body:", json.dumps(response.json(), indent=2))
except Exception as e:
    print("Error:", e)