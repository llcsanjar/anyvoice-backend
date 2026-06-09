# backend/account/reaction_to_theories.py

from fastapi import HTTPException, Query, APIRouter
from bson import ObjectId
from typing import List
from menu.menu import theory_confirmations_collection, theory_rejections_collection, theory_collection, users_collection, users_fs
from menu.menu import decrypt_data
import os
from pymongo import DESCENDING
import base64
from datetime import datetime, timezone

router = APIRouter()

ENCRYPTION_KEY = os.getenv("ENCRYPTION_KEY")

@router.get("/get-user-confirmed-theory")
def get_user_confirmed_theories(
    user_id: str = Query(..., description="ID of the user whose confirmed theories are requested"),
    requester_id: str = Query(None, description="ID of the authenticated user making the request"),
    limit: int = Query(20, description="Number of theories to return"),
    exclude_ids: List[str] = Query(default=[], description="List of theory IDs to exclude")
):
    if not ObjectId.is_valid(user_id):
        raise HTTPException(status_code=400, detail="Invalid user_id")
    if requester_id and not ObjectId.is_valid(requester_id):
        raise HTTPException(status_code=400, detail="Invalid requester_id")

    try:
        excluded_object_ids = [ObjectId(i) for i in exclude_ids if ObjectId.is_valid(i)]
    except Exception:
        excluded_object_ids = []

    # Saved images with UploadAt (save time)
    confirmed_theories = list(
        theory_confirmations_collection.find({"UserId": ObjectId(user_id)})
        .sort("UploadAt", DESCENDING)
        .skip(len(excluded_object_ids))
        .limit(limit)
    )

    # Separate IDs in order
    filtered_theory_ids = []
    for item in confirmed_theories:
        pid = item.get("PostTheoryId")
        if pid and ObjectId.is_valid(pid) and ObjectId(pid) not in excluded_object_ids:
            filtered_theory_ids.append((ObjectId(pid)))
        if len(filtered_theory_ids) >= limit:
            break

    if not filtered_theory_ids:
        return {"theories": []}

    # Get each PostTheoryId
    theory_id_list = [pid for pid in filtered_theory_ids]

    # Get images
    theories = list(theory_collection.find({"_id": {"$in": theory_id_list}}))

    # Sort by UploadAt order
    theory_map = {the["_id"]: the for the in theories}
    sorted_results = []
    for pid in filtered_theory_ids:

        the = theory_map.get(pid)

        user_info = users_collection.find_one({'_id': ObjectId(the["user_id"])})
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

        # Normalize created_at
        created_at = the.get("created_at")

        # If created_at is string, convert it
        if isinstance(created_at, str):
            try:
                created_at = datetime.fromisoformat(created_at)
            except:
                # If string format is broken
                created_at = datetime.now(timezone.utc)

        # If created_at doesn't exist at all
        if not isinstance(created_at, datetime):
            created_at = datetime.now(timezone.utc)

        created_at_iso = created_at.isoformat() + "Z"

        theory_data = {
            "id": str(the["_id"]),
            "user_id": str(the["user_id"]),
            "username": username,
            "display": decrypted_display,
            "avatar": avatar_base64,
            "name": the.get("name", "Theory name"),
            "definition": the.get("definition", "Theory definition"),
            "count_readings": the.get("count_readings", 0),
            "count_confirmations": the.get("count_confirmations", 0),
            "count_rejections": the.get("count_rejections", 0),
            "questions": the.get("questions", 0),
            "created_at": created_at_iso,
            "link": the.get("link", ""),
            "is_basic": True,
            "CountComment": the.get("CountComment", 0),
        }

        if the:
            # Include image in results, regardless of its privacy or public status
            sorted_results.append({
                "id": str(the["_id"]),
                "user_id": str(the["user_id"]),
                "upload_at": the["created_at"],
                "theory_data": theory_data,
            })

    return {"theories": sorted_results}

@router.get("/get-user-rejected-theory")
def get_user_rejected_theories(
    user_id: str = Query(..., description="ID of the user whose rejected theories are requested"),
    requester_id: str = Query(None, description="ID of the authenticated user making the request"),
    limit: int = Query(20, description="Number of theories to return"),
    exclude_ids: List[str] = Query(default=[], description="List of theory IDs to exclude")
):
    if not ObjectId.is_valid(user_id):
        raise HTTPException(status_code=400, detail="Invalid user_id")
    if requester_id and not ObjectId.is_valid(requester_id):
        raise HTTPException(status_code=400, detail="Invalid requester_id")

    try:
        excluded_object_ids = [ObjectId(i) for i in exclude_ids if ObjectId.is_valid(i)]
    except Exception:
        excluded_object_ids = []

    # Saved images with UploadAt (save time)
    rejected_theories = list(
        theory_rejections_collection.find({"UserId": ObjectId(user_id)})
        .sort("UploadAt", DESCENDING)
        .skip(len(excluded_object_ids))
        .limit(limit)
    )

    # Separate IDs in order
    filtered_theory_ids = []
    for item in rejected_theories:
        pid = item.get("PostTheoryId")
        if pid and ObjectId.is_valid(pid) and ObjectId(pid) not in excluded_object_ids:
            filtered_theory_ids.append((ObjectId(pid)))
        if len(filtered_theory_ids) >= limit:
            break

    if not filtered_theory_ids:
        return {"theories": []}

    # Get each PostTheoryId
    theory_id_list = [pid for pid in filtered_theory_ids]

    # Get images
    theories = list(theory_collection.find({"_id": {"$in": theory_id_list}}))

    # Sort by UploadAt order
    theory_map = {the["_id"]: the for the in theories}
    sorted_results = []
    for pid in filtered_theory_ids:

        the = theory_map.get(pid)

        user_info = users_collection.find_one({'_id': ObjectId(the["user_id"])})
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

        # Normalize created_at
        created_at = the.get("created_at")

        # If created_at is string, convert it
        if isinstance(created_at, str):
            try:
                created_at = datetime.fromisoformat(created_at)
            except:
                # If string format is broken
                created_at = datetime.now(timezone.utc)

        # If created_at doesn't exist at all
        if not isinstance(created_at, datetime):
            created_at = datetime.now(timezone.utc)

        created_at_iso = created_at.isoformat() + "Z"

        theory_data = {
            "id": str(the["_id"]),
            "user_id": str(the["user_id"]),
            "username": username,
            "display": decrypted_display,
            "avatar": avatar_base64,
            "name": the.get("name", "Theory name"),
            "definition": the.get("definition", "Theory definition"),
            "count_readings": the.get("count_readings", 0),
            "count_confirmations": the.get("count_confirmations", 0),
            "count_rejections": the.get("count_rejections", 0),
            "questions": the.get("questions", 0),
            "created_at": created_at_iso,
            "link": the.get("link", ""),
            "is_basic": True,
            "CountComment": the.get("CountComment", 0),
        }

        if the:
            # Include image in results, regardless of its privacy or public status
            sorted_results.append({
                "id": str(the["_id"]),
                "user_id": str(the["user_id"]),
                "upload_at": the["created_at"].isoformat() + "Z",
                "theory_data": theory_data,
            })

    return {"theories": sorted_results}
