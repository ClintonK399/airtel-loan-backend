from fastapi import FastAPI
from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI()

# CORS middleware MUST be added BEFORE any routes
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],           # For dev; restrict in production
    allow_credentials=False,       # Must be False when origins is "*"
    allow_methods=["*"],           # This allows OPTIONS, POST, GET, etc.
    allow_headers=["*"],
)

class LoginRequest(BaseModel):
    phone_number: str
    pin: str

@app.get("/")
def read_root():
    return {"status": "Airtel backend is running"}

@app.post("/api/login")
async def login(request: LoginRequest):
    return {"status": "success", "message": f"Welcome back! Phone: {request.phone_number}"}