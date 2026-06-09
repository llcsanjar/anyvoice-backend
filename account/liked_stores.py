# backend/account/liked_stores.py

from fastapi import APIRouter, HTTPException, Query
from menu.menu import shopings_like_collection, shopings_collection
from bson import ObjectId
from pymongo import DESCENDING
from typing import List

router = APIRouter()

@router.get("/get-user-liked-shoping")
def get_user_saved_shopings(
    user_id: str = Query(..., description="ID of the user whose saved shopings are requested"),
    requester_id: str = Query(None, description="ID of the authenticated user making the request"),
    limit: int = Query(20, description="Number of shopings to return"),
    exclude_ids: List[str] = Query(default=[], description="List of shoping IDs to exclude")
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
    saved_shopings = list(
        shopings_like_collection.find({"UserId": ObjectId(user_id)})
        .sort("UploadAt", DESCENDING)
        .skip(len(excluded_object_ids))
        .limit(limit)
    )

    # Separate IDs in order
    filtered_shoping_ids = []
    for item in saved_shopings:
        pid = item.get("PostShopingId")
        if pid and ObjectId.is_valid(pid) and ObjectId(pid) not in excluded_object_ids:
            filtered_shoping_ids.append((ObjectId(pid), item["UploadAt"]))
        if len(filtered_shoping_ids) >= limit:
            break

    if not filtered_shoping_ids:
        return {"shopings": []}

    # Get each PostShopingId
    shoping_id_list = [pid for pid, _ in filtered_shoping_ids]

    # Get images
    shopings = list(shopings_collection.find({"_id": {"$in": shoping_id_list}}))

    # Sort by UploadAt order
    shoping_map = {img["_id"]: img for img in shopings}
    sorted_results = []
    for pid, saved_at in filtered_shoping_ids:
        img = shoping_map.get(pid)
        if img:
            # Include image in results, regardless of its privacy or public status
            sorted_results.append({
                "id": str(img["_id"]),
                "user_id": str(img["UserId"]),
                "upload_at": img["UploadAt"].isoformat(),
                "saved_at": saved_at.isoformat(),
            })

    return {"shopings": sorted_results}
