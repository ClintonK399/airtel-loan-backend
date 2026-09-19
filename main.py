from fastapi import FastAPI
from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class LoginRequest(BaseModel):
    phone_number: str
    pin: str

@app.post("/api/login")
async def login(request: LoginRequest):
    # For demo purposes, any phone number and PIN works.
    # In a real app, you would verify this against a database.
    if len(request.pin) == 4:
        return {"status": "success", "message": "Login successful!"}
    return {"status": "error", "message": "Invalid PIN."}