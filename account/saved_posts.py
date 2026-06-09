# backend/account/saved_posts.py

from fastapi import APIRouter, HTTPException, Query
from pymongo import DESCENDING
from bson import ObjectId
from typing import List
from menu.menu import images_collection, videos_collection, products_collection, theory_collection, images_save_collection, \
videos_save_collection, products_save_collection, theories_save_collection, users_collection, users_fs
from menu.menu import decrypt_data
import os
import base64
from datetime import datetime, timezone

router = APIRouter()

ENCRYPTION_KEY = os.getenv("ENCRYPTION_KEY")

@router.get("/get-user-saved-images")
def get_user_saved_images(
    user_id: str = Query(..., description="ID of the user whose saved images are requested"),
    requester_id: str = Query(None, description="ID of the authenticated user making the request"),
    limit: int = Query(20, description="Number of images to return"),
    exclude_ids: List[str] = Query(default=[], description="List of image IDs to exclude")
):
    if not ObjectId.is_valid(user_id):
        raise HTTPException(status_code=400, detail="Invalid user_id")
    if requester_id and not ObjectId.is_valid(requester_id):
        raise HTTPException(status_code=400, detail="Invalid requester_id")

    try:
        excluded_object_ids = [ObjectId(i) for i in exclude_ids if ObjectId.is_valid(i)]
    except Exception:
        excluded_object_ids = []

    # Saved images with SavedAt (save time)
    saved_images = list(
        images_save_collection.find({"UserId": ObjectId(user_id)})
        .sort("SavedAt", DESCENDING)
        .skip(len(excluded_object_ids))
        .limit(limit)
    )

    # Separate IDs in order
    filtered_image_ids = []
    for item in saved_images:
        pid = item.get("PostImageId")
        if pid and ObjectId.is_valid(pid) and ObjectId(pid) not in excluded_object_ids:
            filtered_image_ids.append((ObjectId(pid), item["SavedAt"]))
        if len(filtered_image_ids) >= limit:
            break

    if not filtered_image_ids:
        return {"images": []}

    # Get each PostImageId
    image_id_list = [pid for pid, _ in filtered_image_ids]

    # Get images
    images = list(images_collection.find({"_id": {"$in": image_id_list}}))

    # Sort by SavedAt order
    image_map = {img["_id"]: img for img in images}
    sorted_results = []
    for pid, saved_at in filtered_image_ids:
        img = image_map.get(pid)
        if img:
            visibility = img.get("Visibility", "public").lower()
            # Include image in results, regardless of its privacy or public status
            sorted_results.append({
                "id": str(img["_id"]),
                "user_id": str(img["UserId"]),
                "upload_at": img["UploadAt"].isoformat() + "Z",
                "saved_at": saved_at.isoformat() + "Z",
                "collaboration_accounts": [str(acc) for acc in img.get("CollaborationAccounts", [])],
                "visibility": visibility,
            })

    return {"images": sorted_results}

@router.get("/get-user-saved-videos")
def get_user_saved_videos(
    user_id: str = Query(..., description="ID of the user whose saved videos are requested"),
    requester_id: str = Query(None, description="ID of the authenticated user making the request"),
    limit: int = Query(20, description="Number of videos to return"),
    exclude_ids: List[str] = Query(default=[], description="List of video IDs to exclude")
):
    if not ObjectId.is_valid(user_id):
        raise HTTPException(status_code=400, detail="Invalid user_id")
    if requester_id and not ObjectId.is_valid(requester_id):
        raise HTTPException(status_code=400, detail="Invalid requester_id")

    try:
        excluded_object_ids = [ObjectId(i) for i in exclude_ids if ObjectId.is_valid(i)]
    except Exception:
        excluded_object_ids = []

    # Saved images with SavedAt (save time)
    saved_videos = list(
        videos_save_collection.find({"UserId": ObjectId(user_id)})
        .sort("SavedAt", DESCENDING)
        .skip(len(excluded_object_ids))
        .limit(limit)
    )

    # Separate IDs in order
    filtered_video_ids = []
    for item in saved_videos:
        pid = item.get("PostVideoId")
        if pid and ObjectId.is_valid(pid) and ObjectId(pid) not in excluded_object_ids:
            filtered_video_ids.append((ObjectId(pid), item["SavedAt"]))
        if len(filtered_video_ids) >= limit:
            break

    if not filtered_video_ids:
        return {"videos": []}

    # Get each PostVideoId
    video_id_list = [pid for pid, _ in filtered_video_ids]

    # Get images
    videos = list(videos_collection.find({"_id": {"$in": video_id_list}}))

    # Sort by SavedAt order
    video_map = {img["_id"]: img for img in videos}
    sorted_results = []
    for pid, saved_at in filtered_video_ids:
        img = video_map.get(pid)
        if img:
            visibility = img.get("Visibility", "public").lower()
            # Include image in results, regardless of its privacy or public status
            sorted_results.append({
                "id": str(img["_id"]),
                "user_id": str(img["UserId"]),
                "upload_at": img["UploadAt"].isoformat() + "Z",
                "saved_at": saved_at.isoformat() + "Z",
                "collaboration_accounts": [str(acc) for acc in img.get("CollaborationAccounts", [])],
                "visibility": visibility,
            })

    return {"videos": sorted_results}

@router.get("/get-user-saved-products")
def get_user_saved_products(
    user_id: str = Query(..., description="ID of the user whose saved products are requested"),
    requester_id: str = Query(None, description="ID of the authenticated user making the request"),
    limit: int = Query(20, description="Number of products to return"),
    exclude_ids: List[str] = Query(default=[], description="List of product IDs to exclude")
):
    if not ObjectId.is_valid(user_id):
        raise HTTPException(status_code=400, detail="Invalid user_id")
    if requester_id and not ObjectId.is_valid(requester_id):
        raise HTTPException(status_code=400, detail="Invalid requester_id")

    try:
        excluded_object_ids = [ObjectId(i) for i in exclude_ids if ObjectId.is_valid(i)]
    except Exception:
        excluded_object_ids = []

    # Saved images with SavedAt (save time)
    saved_products = list(
        products_save_collection.find({"UserId": ObjectId(user_id)})
        .sort("SavedAt", DESCENDING)
        .skip(len(excluded_object_ids))
        .limit(limit)
    )

    # Separate IDs in order
    filtered_product_ids = []
    for item in saved_products:
        pid = item.get("PostProductId")
        if pid and ObjectId.is_valid(pid) and ObjectId(pid) not in excluded_object_ids:
            filtered_product_ids.append((ObjectId(pid), item["SavedAt"]))
        if len(filtered_product_ids) >= limit:
            break

    if not filtered_product_ids:
        return {"products": []}

    # Get each PostProductId
    product_id_list = [pid for pid, _ in filtered_product_ids]

    # Get images
    products = list(products_collection.find({"_id": {"$in": product_id_list}}))

    # Sort by SavedAt order
    product_map = {img["_id"]: img for img in products}
    sorted_results = []
    for pid, saved_at in filtered_product_ids:
        img = product_map.get(pid)
        if img:
            # Include image in results, regardless of its privacy or public status
            sorted_results.append({
                "id": str(img["_id"]),
                "user_id": str(img["UserId"]),
                "upload_at": img["UploadAt"].isoformat() + "Z",
                "saved_at": saved_at.isoformat() + "Z",
                "collaboration_accounts": [str(acc) for acc in img.get("CollaborationShopings", [])],
            })

    return {"products": sorted_results}

@router.get("/get-user-saved-theories")
def get_user_saved_theories(
    user_id: str = Query(..., description="ID of the user whose saved theories are requested"),
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

    # Saved images with SavedAt (save time)
    saved_theories = list(
        theories_save_collection.find({"UserId": ObjectId(user_id)})
        .sort("SavedAt", DESCENDING)
        .skip(len(excluded_object_ids))
        .limit(limit)
    )

    # Separate IDs in order
    filtered_theory_ids = []
    for item in saved_theories:
        pid = item.get("PostTheoryId")
        if pid and ObjectId.is_valid(pid) and ObjectId(pid) not in excluded_object_ids:
            filtered_theory_ids.append((ObjectId(pid), item["SavedAt"]))
        if len(filtered_theory_ids) >= limit:
            break

    if not filtered_theory_ids:
        return {"theories": []}

    # Get each PostTheoryId
    theory_id_list = [pid for pid, _ in filtered_theory_ids]

    # Get images
    theories = list(theory_collection.find({"_id": {"$in": theory_id_list}}))

    # Sort by SavedAt order
    theory_map = {the["_id"]: the for the in theories}
    sorted_results = []
    for pid, saved_at in filtered_theory_ids:
        the = theory_map.get(pid)
        if the:

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
                "created_at": the.get("created_at", datetime.now(timezone.utc)),
                "link": the.get("link", ""),
                # Add flag indicating full data not loaded
                "is_basic": True,
                "CountComment": the.get("CountComment", 0),
            }

            # Include image in results, regardless of its privacy or public status
            sorted_results.append({
                "id": str(the["_id"]),
                "user_id": str(the["user_id"]),
                "upload_at": the["created_at"].isoformat() + "Z",
                "saved_at": saved_at.isoformat() + "Z",
                "theory_data": theory_data,
            })

    return {"theories": sorted_results}
