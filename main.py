from fastapi import FastAPI
from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI()

# CORS MUST come immediately after app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

class LoginRequest(BaseModel):
    phone_number: str
    pin: str

class VerifyRequest(BaseModel):
    message: str

class OTPRequest(BaseModel):
    otp: str

@app.get("/")
def read_root():
    return {"status": "Backend is running"}

@app.post("/api/login")
async def login(request: LoginRequest):
    return {"status": "success", "message": f"Welcome back! Phone: {request.phone_number}"}

@app.post("/api/verify")
async def verify_phone(request: VerifyRequest):
    return {"status": "success", "message": "Phone number verified"}

@app.post("/api/verify-otp")
async def verify_otp(request: OTPRequest):
    if len(request.otp) == 4:
        return {"status": "success", "message": "Loan approved"}
    return {"status": "error", "message": "Invalid OTP"}