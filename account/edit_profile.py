# backend/account/edit_profile.py

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from menu.menu import users_collection, users_fs
from menu.menu import decrypt_data
from datetime import datetime, timezone
import base64
from io import BytesIO
import os

router = APIRouter()

ENCRYPTION_KEY = os.getenv("ENCRYPTION_KEY")

def encrypt_data_func(data: str, key: bytes) -> str:
    if data:
        from cryptography.fernet import Fernet
        fernet = Fernet(key)
        return fernet.encrypt(data.encode()).decode()
    return ""

class UserUpdate(BaseModel):
    Username: str
    Password: str
    Display: str
    ProfileImage: str
    new_username: str

@router.post("/update-profile")
async def update_profile(update: UserUpdate):
    # Find existing user
    user = users_collection.find_one({"Username": update.Username})
    if not user:
        raise HTTPException(status_code=401, detail="User not found")

    updated_fields = {}
    changes_made = False

    # ✅ Username
    if update.new_username and update.new_username != update.Username:
        if users_collection.find_one({"Username": update.new_username}):
            raise HTTPException(status_code=402, detail="Username already exists")
        updated_fields["Username"] = update.new_username
        changes_made = True

    # ✅ Password
    if update.Password:
        try:
            decrypted = decrypt_data(user["Password"], ENCRYPTION_KEY)
            if decrypted != update.Password:
                encrypted = encrypt_data_func(update.Password, ENCRYPTION_KEY)
                updated_fields["Password"] = encrypted
                changes_made = True
        except Exception:
            raise HTTPException(status_code=403, detail="Password decryption failed")

    # ✅ Display
    if update.Display is not None:
        existing_display = user.get("Display", "")
        try:
            existing_decrypted = decrypt_data(existing_display, ENCRYPTION_KEY) if existing_display else ""
        except:
            existing_decrypted = ""
        
        if existing_decrypted != update.Display:
            updated_fields["Display"] = encrypt_data_func(update.Display, ENCRYPTION_KEY) if update.Display else ""
            changes_made = True

    # ✅ Profile Image
    if update.ProfileImage:
        try:
            image_data = base64.b64decode(update.ProfileImage.split(",")[1])
            image_file = BytesIO(image_data)
            
            file_id = users_fs.put(
                image_file,
                filename=f"{update.new_username or update.Username}_profile_image.png"
            )
            
            updated_fields["ProfileImageId"] = file_id
            changes_made = True
        except Exception as e:
            raise HTTPException(status_code=400, detail="Image processing error")

    # ✅ Final update
    if changes_made:
        updated_fields["UpdatedAt"] = datetime.now(timezone.utc)
        users_collection.update_one({"Username": update.Username}, {"$set": updated_fields})
        
        return {
            "message": "Profile updated successfully",
            "updated_fields": list(updated_fields.keys())
        }
    else:
        return {"message": "No changes detected"}
