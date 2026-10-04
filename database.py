import sqlite3
from passlib.context import CryptContext

DB_PATH = "users.db"
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

def init_db():
    """Create the users table if it doesn't exist."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            phone_number TEXT PRIMARY KEY,
            pin_hash TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()

def hash_pin(pin: str) -> str:
    return pwd_context.hash(pin)

def verify_pin(plain_pin: str, hashed_pin: str) -> bool:
    return pwd_context.verify(plain_pin, hashed_pin)

def create_user(phone: str, pin: str):
    """Insert a new user with a hashed PIN."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    try:
        cursor.execute(
            "INSERT INTO users (phone_number, pin_hash) VALUES (?, ?)",
            (phone, hash_pin(pin))
        )
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False  # User already exists
    finally:
        conn.close()

def get_user(phone: str):
    """Retrieve a user by phone number."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute(
        "SELECT phone_number, pin_hash FROM users WHERE phone_number = ?",
        (phone,)
    )
    row = cursor.fetchone()
    conn.close()
    return row  # (phone_number, pin_hash) or None

def verify_user_pin(phone: str, pin: str) -> bool:
    """Check if the given PIN matches the stored hash."""
    user = get_user(phone)
    if not user:
        return False
    return verify_pin(pin, user[1])