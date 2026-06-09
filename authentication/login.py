# backend/authentication/login.py

from fastapi import HTTPException, APIRouter, Response
from pydantic import BaseModel
from dotenv import load_dotenv
import uuid
from datetime import datetime, timedelta
from menu.menu import sessions, users_collection
import os
from menu.menu import encrypt_data, decrypt_data

# Load environment variables
load_dotenv()
ENCRYPTION_KEY = os.getenv("ENCRYPTION_KEY")

router = APIRouter()

class UserLogin(BaseModel):
    Username: str
    Password: str

@router.post("/login")
async def login(user: UserLogin, response: Response):
    db_user = users_collection.find_one({"Username": user.Username})
    if not db_user:
        raise HTTPException(status_code=400, detail="User not found")

    try:
        decrypted_password = decrypt_data(db_user["Password"], ENCRYPTION_KEY)
    except Exception:
        raise HTTPException(status_code=400, detail="Password decryption failed")

    if user.Password != decrypted_password:
        raise HTTPException(status_code=400, detail="Incorrect password")

    access_token = str(uuid.uuid4())

    encrypted_token = encrypt_data(access_token, ENCRYPTION_KEY)

    print("ENCRYPTED:", encrypted_token)

    sessions.insert_one({
        "token": access_token,
        "user_id": db_user['_id'],
        "expires": datetime.utcnow() + timedelta(minutes=15)
    })

    return {
        "message": "Login successful",
        "user_id": str(db_user['_id']),
        "access_token": encrypted_token
    }
