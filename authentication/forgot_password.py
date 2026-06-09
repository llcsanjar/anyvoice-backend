# backend/authentication/forgot_password.py

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from datetime import datetime, timezone, timedelta
import os
import random
import string
from dotenv import load_dotenv
from menu.menu import users_collection, recovery_codes_collection
from menu.menu import encrypt_data, decrypt_data

load_dotenv()

router = APIRouter()

ENCRYPTION_KEY = os.getenv("ENCRYPTION_KEY")

def generate_recovery_code() -> str:
    """Generate a secure 8-character recovery code"""
    characters = string.ascii_uppercase + string.digits
    # Remove similar looking characters
    characters = characters.replace('O', '').replace('0', '').replace('I', '').replace('1', '')
    return ''.join(random.choices(characters, k=8))

class RecoveryCodeRequest(BaseModel):
    username: str
    recovery_code: str

class UpdatePasswordRequest(BaseModel):
    username: str
    recovery_code: str
    new_password: str
    confirm_password: str

@router.post("/verify_recovery_code")
async def verify_recovery_code(request: RecoveryCodeRequest):
    """Verify recovery code and return success/failure"""
    
    # Find user by username
    user = users_collection.find_one({"Username": request.username})
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    # Find recovery code for this user (not used yet)
    recovery_record = recovery_codes_collection.find_one({
        "username": request.username,
        "used": False
    })
    
    if not recovery_record:
        raise HTTPException(status_code=404, detail="Recovery code not found for this user")
    
    # Decrypt stored recovery code
    try:
        stored_code = decrypt_data(recovery_record["recovery_code"], ENCRYPTION_KEY)
    except Exception:
        raise HTTPException(status_code=500, detail="Error decrypting recovery code")
    
    # Compare codes
    if stored_code != request.recovery_code.upper().strip():
        # Increment failed attempts
        failed_attempts = recovery_record.get("failed_attempts", 0) + 1
        recovery_codes_collection.update_one(
            {"_id": recovery_record["_id"]},
            {"$set": {"failed_attempts": failed_attempts}}
        )
        raise HTTPException(status_code=401, detail="Invalid recovery code")
    
    # Reset failed attempts on successful verification
    recovery_codes_collection.update_one(
        {"_id": recovery_record["_id"]},
        {"$set": {"failed_attempts": 0}}
    )
    
    # IMPORTANT: Do NOT mark as used yet! Only mark as verified temporarily
    # Store verification in a separate field, not "used"
    recovery_codes_collection.update_one(
        {"_id": recovery_record["_id"]},
        {"$set": {"verified_at": datetime.now(timezone.utc), "temp_verified": True}}
    )
    
    return {"message": "Recovery code verified successfully"}

@router.put("/update_password_with_recovery")
async def update_password_with_recovery(request: UpdatePasswordRequest):
    """Update password using recovery code and generate new recovery code"""
    
    # Validate passwords match
    if request.new_password != request.confirm_password:
        raise HTTPException(status_code=400, detail="Passwords do not match")
    
    # Validate password length
    if len(request.new_password) < 8 or len(request.new_password) > 30:
        raise HTTPException(status_code=400, detail="Password must be between 8 and 30 characters")
    
    # Find user
    user = users_collection.find_one({"Username": request.username})
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    # Find recovery code that is verified but not yet used
    recovery_record = recovery_codes_collection.find_one({
        "username": request.username,
        "used": False,
        "temp_verified": True
    })

    if not recovery_record:
        raise HTTPException(status_code=401, detail="Recovery code not verified. Please verify your recovery code first.")

    # Check if verification was within last 15 minutes
    verified_at = recovery_record.get("verified_at")

    if verified_at:
        if verified_at.tzinfo is None:
            verified_at = verified_at.replace(tzinfo=timezone.utc)

        if datetime.now(timezone.utc) - verified_at > timedelta(minutes=15):
            # Clean up expired verification
            recovery_codes_collection.update_one(
                {"_id": recovery_record["_id"]},
                {"$unset": {"verified_at": "", "temp_verified": ""}}
            )
            raise HTTPException(status_code=401, detail="Verification has expired. Please verify your recovery code again.")

    # Verify the recovery code matches (for extra security)
    try:
        stored_code = decrypt_data(recovery_record["recovery_code"], ENCRYPTION_KEY)
    except Exception:
        raise HTTPException(status_code=500, detail="Error decrypting recovery code")
    
    if stored_code != request.recovery_code.upper().strip():
        raise HTTPException(status_code=401, detail="Invalid recovery code")

    # Update password
    encrypted_password = encrypt_data(request.new_password, ENCRYPTION_KEY)
    users_collection.update_one(
        {"Username": request.username},
        {"$set": {"Password": encrypted_password}}
    )
    
    # Generate NEW recovery code for the user
    new_recovery_code = generate_recovery_code()
    
    # Save new recovery code to collection (encrypted)
    new_recovery_data = {
        "user_id": str(user["_id"]),
        "username": request.username,
        "recovery_code": encrypt_data(new_recovery_code, ENCRYPTION_KEY),
        "created_at": datetime.now(timezone.utc),
        "used": False,
        "failed_attempts": 0
    }
    recovery_codes_collection.insert_one(new_recovery_data)
    
    # Delete the old recovery code record (the one that was used)
    recovery_codes_collection.delete_one({"_id": recovery_record["_id"]})
    
    return {
        "message": "Password updated successfully",
        "new_recovery_code": new_recovery_code
    }
