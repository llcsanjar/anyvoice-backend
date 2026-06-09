# backend/account/create/theory_uploader.py

from fastapi import APIRouter, HTTPException, BackgroundTasks
from pydantic import BaseModel
from typing import List, Optional
from bson import ObjectId
from datetime import datetime, timezone
import string
import random
from menu.menu import users_collection, followers_collection, theory_collection, notifications_collection
from home.home import encrypt_data, serialize_notification, broadcast_notification
import asyncio
import os
from dotenv import load_dotenv

router = APIRouter()

load_dotenv()

ENCRYPTION_KEY = os.getenv("ENCRYPTION_KEY")

class TheoryCreateResponse(BaseModel):
    success: bool
    message: str
    theory_id: Optional[str] = None
    error: Optional[str] = None

class TheoryRelationships(BaseModel):
    compatible: str
    opposing: str
    stronger_than: str

class TheorySectionItem(BaseModel):
    title: str
    description: str

class TheoryTerm(BaseModel):
    term: str
    definition: str

class TheoryCreateRequest(BaseModel):
    name: str
    definition: str
    principles: List[TheorySectionItem]
    evidence: List[TheorySectionItem]
    conclusions: List[TheorySectionItem]
    rejections: List[TheorySectionItem]
    predictions: List[TheorySectionItem]
    limitations: List[TheorySectionItem]
    terms: List[TheoryTerm]
    relationships: TheoryRelationships
    additional_info: str
    advertisement_checkbox: bool = False
    advertisement_count: int = 0

progress_store = {}

def update_progress(user_id: str, progress: int, status: str, message: str, theory_id: str = None, unique_link: str = None):
    """Update progress status"""
    if user_id in progress_store:
        progress_store[user_id]["progress"] = progress
        progress_store[user_id]["status"] = status
        progress_store[user_id]["message"] = message
        progress_store[user_id]["theory_link"] = unique_link
        if theory_id:
            progress_store[user_id]["theory_id"] = theory_id

def process_theory_creation(user_id: str, advertisement_checkbox, advertisement_count, theory_data: TheoryCreateRequest, background_tasks: BackgroundTasks):
    """Background process for theory creation"""
    try:
        # Add user information and time correctly
        theory_dict = theory_data.dict()

        # Add additional fields for database
        theory_dict["user_id"] = ObjectId(user_id)
        theory_dict["created_at"] = datetime.now(timezone.utc)

        # Generate unique link
        characters = string.ascii_letters + string.digits
        while True:
            unique_link = ''.join(random.choice(characters) for _ in range(11))
            if not theory_collection.find_one({'link': f'{unique_link}'}):
                break

        theory_dict["link"] = unique_link

        if advertisement_count and advertisement_checkbox:
            theory_dict["AdvertisementCount"] = int(advertisement_count)

        theory_dict["AdvertisementCheckbox"] = advertisement_checkbox

        print(f"Data for database: user_id={user_id}, created_at={theory_dict['created_at']}")
        
        # 1. Data validation
        update_progress(user_id, 10, "validating", "Validating data")
        asyncio.sleep(0.5)
        
        # 2. Prepare data for database
        update_progress(user_id, 20, "preparing", "Preparing data")
        asyncio.sleep(0.5)
        
        # 3. Add basic principles
        update_progress(user_id, 30, "saving_principles", "Adding basic principles")
        asyncio.sleep(0.7)
        
        # 4. Add evidence
        update_progress(user_id, 40, "saving_evidence", "Adding scientific evidence")
        asyncio.sleep(0.7)
        
        # 5. Add conclusions
        update_progress(user_id, 50, "saving_conclusions", "Adding logical conclusions")
        asyncio.sleep(0.7)
        
        # 6. Add rejections
        update_progress(user_id, 60, "saving_rejections", "Adding things that are rejected")
        asyncio.sleep(0.7)
        
        # 7. Add predictions
        update_progress(user_id, 70, "saving_predictions", "Adding predictions")
        asyncio.sleep(0.7)
        
        # 8. Add limitations
        update_progress(user_id, 80, "saving_limitations", "Adding limitations and weaknesses")
        asyncio.sleep(0.7)
        
        # 9. Add terminology
        update_progress(user_id, 85, "saving_terms", "Adding terminology")
        asyncio.sleep(0.5)
        
        # 10. Add relationships
        update_progress(user_id, 90, "saving_relationships", "Adding relationships with other theories")
        asyncio.sleep(0.5)
        
        # 11. Add additional information
        update_progress(user_id, 95, "saving_additional", "Adding additional information")
        asyncio.sleep(0.5)
        
        # 12. Save all data in database
        update_progress(user_id, 98, "finalizing", "Finalizing save in database")

        # Save all data in database
        print(f"Saving theory in database: {theory_dict}")
        result = theory_collection.insert_one(theory_dict)
        users_collection.update_one({"_id": ObjectId(user_id)}, {"$inc": {"CountPosts": 1}})
        users_collection.update_one({"_id": ObjectId(user_id)}, {"$inc": {"CountTheories": 1}})
        theory_id = str(result.inserted_id)

        async def send_message(user_id, theory_id, unique_link):
            user = users_collection.find_one({"_id": ObjectId(user_id)})

            followers = followers_collection.find({"target_user_id": ObjectId(user_id)})
            encrypted_follower_message = encrypt_data(
                f"@{user.get('Username')} added a new theory. View theory: https://www.anyvoice.world/theory/{unique_link}",
                ENCRYPTION_KEY
            )
            encrypted_follower_type = encrypt_data("new_post", ENCRYPTION_KEY)

            for follower in followers:
                try:
                    follower_id = follower["follower_id"]
                    if follower_id != ObjectId(user_id):
                        notification_doc = {
                            "NotificationFrom": ObjectId(user_id),
                            "NotificationTo": follower_id,
                            "Message": encrypted_follower_message,
                            "PostId": theory_id,
                            "IsRead": False,
                            "UploadAt": datetime.now(timezone.utc).isoformat().replace('Z', '+00:00'),
                            "Type": encrypted_follower_type,
                            "status": "pending"
                        }
                        notifications_collection.insert_one(notification_doc)
                        serialized_notification = serialize_notification(notification_doc)
                        await broadcast_notification(str(follower_id), "add", serialized_notification)
                except Exception as e:
                    print(f"Error sending notification to follower {follower_id}: {e}")

        background_tasks.add_task(send_message, user_id, theory_id, unique_link)

        # Successful completion
        update_progress(user_id, 100, "completed", "Theory created successfully", theory_id, unique_link)

        print(f"Theory created successfully. ID: {theory_id}")

    except Exception as e:
        # Error in creation
        error_msg = f"Error in creation: {str(e)}"
        print(error_msg)
        update_progress(user_id, 0, "error", error_msg)

@router.post("/theories/{user_id}", response_model=TheoryCreateResponse)
async def create_theory(user_id: str, theory_data: TheoryCreateRequest, background_tasks: BackgroundTasks):
    """Create new theory with progress system"""

    # Initial data validation
    if not theory_data.name.strip():
        return TheoryCreateResponse(
            success=False,
            message="Please enter theory name",
            error="validation_error"
        )

    if not theory_data.definition.strip():
        return TheoryCreateResponse(
            success=False,
            message="Please enter theory definition",
            error="validation_error"
        )

    # Start progress
    progress_store[user_id] = {
        "progress": 0,
        "status": "processing",
        "message": "Checking data",
        "theory_id": None
    }

    advertisement_count = float(theory_data.advertisement_count)
    advertisement_checkbox = theory_data.advertisement_checkbox

    if theory_data.advertisement_count and advertisement_checkbox:
        amount = advertisement_count / 100

        from_user = users_collection.find_one({"_id": ObjectId(user_id)})

        if not from_user:
            raise HTTPException(status_code=404, detail="Source user not found")

        # Check source user balance
        from_user_balance = from_user.get("Balance", 0)
        if from_user_balance < amount:
            raise HTTPException(status_code=408, detail="Insufficient balance")

        users_collection.update_one(
            {"_id": ObjectId(user_id)},
            {"$inc": {"Balance": -amount}}
        )

        # Add amount to target account
        users_collection.update_one(
            {"Username": "sanjar"},
            {"$inc": {"Balance": amount}}
        )

    # Execute in background
    background_tasks.add_task(process_theory_creation, user_id, advertisement_checkbox, advertisement_count, theory_data, background_tasks)

    return TheoryCreateResponse(
        success=True,
        message="Creation started",
        theory_id=None
    )

@router.post("/theories/progress/{user_id}")
async def create_theory_progress(user_id: str):
    """Create progress object for existing user"""
    progress_store[user_id] = {
        "progress": 0,
        "status": "starting",
        "message": "Starting theory creation",
        "theory_id": None
    }
    return {"status": "progress_created"}

@router.get("/theories/progress/{user_id}")
async def get_theory_progress(user_id: str):
    """Get progress status"""
    if user_id not in progress_store:
        raise HTTPException(status_code=404, detail="Progress not found")
    return progress_store[user_id]
