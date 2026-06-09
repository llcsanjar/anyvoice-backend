# backend/authentication/signup.py

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from io import BytesIO
import base64
from dotenv import load_dotenv
from cryptography.fernet import Fernet
from datetime import datetime, timezone
import os
import random
import string
from menu.menu import users_collection, users_fs, recovery_codes_collection

load_dotenv()

router = APIRouter()

ENCRYPTION_KEY = os.getenv("ENCRYPTION_KEY")

def encrypt_data(data: str, key: bytes) -> str:
    if data:
        fernet = Fernet(key)
        return fernet.encrypt(data.encode()).decode()
    return ""

def generate_recovery_code() -> str:
    """Generate a secure 8-character recovery code"""
    characters = string.ascii_uppercase + string.digits
    # Remove similar looking characters
    characters = characters.replace('O', '').replace('0', '').replace('I', '').replace('1', '')
    return ''.join(random.choices(characters, k=8))

class UserSignup(BaseModel):
    Username: str
    Password: str
    Display: str
    ProfileImage: str

@router.post("/signup")
async def register(user: UserSignup):
    # Username validation
    if users_collection.find_one({"Username": user.Username}):
        raise HTTPException(status_code=401, detail="Username already exists")
    
    # Process profile image
    try:
        image_data = base64.b64decode(user.ProfileImage.split(",")[1])
        image_file = BytesIO(image_data)
        file_id = users_fs.put(image_file, filename=f"{user.Username}_profile_image.png")
    except Exception as e:
        raise HTTPException(status_code=400, detail="Image processing error")
    
    # Generate recovery code
    recovery_code = generate_recovery_code()
    
    # Prepare user data
    current_time = datetime.now(timezone.utc)
    
    final_user_data = {
        "Username": user.Username,
        "Password": encrypt_data(user.Password, ENCRYPTION_KEY),
        "Display": encrypt_data(user.Display, ENCRYPTION_KEY) if user.Display else "",
        "ProfileImageId": file_id,
        "CountPosts": 0,
        "CountFollowers": 0,
        "CountFollowing": 0,
        "Balance": 0,
        "CreatedAt": current_time,
    }
    
    # Save to database
    result = users_collection.insert_one(final_user_data)
    
    # Save recovery code to collection (encrypted)
    recovery_data = {
        "user_id": str(result.inserted_id),
        "username": user.Username,
        "recovery_code": encrypt_data(recovery_code, ENCRYPTION_KEY),
        "created_at": current_time,
        "used": False
    }
    recovery_codes_collection.insert_one(recovery_data)
    
    return {
        "message": "User created successfully",
        "user_id": str(result.inserted_id),
        "recovery_code": recovery_code
    }
