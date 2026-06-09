# backend/dispute/theory/explore_theory.py

from fastapi import APIRouter
from bson import ObjectId
import os
import datetime
import base64
from fastapi import Query
from typing import List
from menu.menu import users_collection, theory_collection, users_fs
from menu.menu import decrypt_data
from datetime import timezone

ENCRYPTION_KEY = os.getenv("ENCRYPTION_KEY")

router = APIRouter()

@router.get("/get-random-theories")
def get_random_theories(
    limit: int = 10,
    exclude_ids: List[str] = Query(default=[]),
):
    try:
        excluded_object_ids = []
        for theory_id in exclude_ids:
            try:
                if ObjectId.is_valid(theory_id):
                    excluded_object_ids.append(ObjectId(theory_id))
            except:
                continue
    except Exception as e:
        excluded_object_ids = []

    # Build the match criteria
    match_criteria = {}
    if excluded_object_ids:
        match_criteria["_id"] = {"$nin": excluded_object_ids}

    try:
        pipeline = []
        if match_criteria:
            pipeline.append({"$match": match_criteria})
        
        pipeline.append({"$sample": {"size": limit}})
        
        results = list(theory_collection.aggregate(pipeline))
        
        # Add basic data for display in cards
        theories_with_basic_data = []
        for item in results:
            user_info = users_collection.find_one({'_id': ObjectId(item["user_id"])})
            if not user_info:
                continue

            username = user_info['Username']
            display = user_info.get('Display', '')
            decrypted_display = decrypt_data(display, ENCRYPTION_KEY) if display else ''

            profile_image_id = user_info.get("ProfileImageId")
            if profile_image_id:
                file_avatar = users_fs.get(ObjectId(profile_image_id))
                avatar_base64 = base64.b64encode(file_avatar.read()).decode('utf-8')
            else:
                avatar_base64 = ''

            # Only basic data for card display
            theory_data = {
                "id": str(item["_id"]),
                "user_id": str(item["user_id"]),
                "username": username,
                "display": decrypted_display,
                "avatar": avatar_base64,
                "name": item.get("name", "Theory name"),
                "definition": item.get("definition", "Theory definition"),
                "count_readings": item.get("count_readings", 0),
                "count_confirmations": item.get("count_confirmations", 0),
                "count_rejections": item.get("count_rejections", 0),
                "questions": item.get("questions", 0),
                "created_at": item.get("created_at", datetime.now(timezone.utc)),
                "link": item.get("link", ""),
                # Add flag indicating full data not loaded
                "is_basic": True,
                "CountComment": item.get("CountComment", 0),
            }
            theories_with_basic_data.append(theory_data)

        return {
            "theories": theories_with_basic_data,
            "total": len(theories_with_basic_data)
        }
        
    except Exception as e:
        print(f"Error getting theories: {e}")
        return {
            "theories": [],
            "total": 0
        }
