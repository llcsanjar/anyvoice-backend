# backend/account/supported_posts.py

from fastapi import APIRouter, HTTPException, Query
from pymongo import DESCENDING
from bson import ObjectId
from typing import List
from menu.menu import images_collection, images_support_collection, videos_collection, videos_support_collection

router = APIRouter()

@router.get("/get-user-supported-images")
def get_user_supported_images(
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

    try:
        # Saved images with UploadAt (save time)
        saved_images = list(
            images_support_collection.find({"UserId": ObjectId(user_id)})
            .sort("UploadAt", DESCENDING)
            .skip(len(excluded_object_ids))
            .limit(limit)
        )

        # Separate IDs in order
        filtered_image_ids = []
        for item in saved_images:
            pid = item.get("PostImageId")
            if pid and ObjectId.is_valid(pid) and ObjectId(pid) not in excluded_object_ids:
                filtered_image_ids.append((ObjectId(pid), item["UploadAt"]))
            if len(filtered_image_ids) >= limit:
                break

        if not filtered_image_ids:
            return {"images": []}

        # Get each PostImageId
        image_id_list = [pid for pid, _ in filtered_image_ids]

        # Get images
        images = list(images_collection.find({"_id": {"$in": image_id_list}}))

        # Sort by UploadAt order
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

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching saved images: {str(e)}")

@router.get("/get-user-supported-videos")
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

    try:
        # Saved images with UploadAt (save time)
        saved_videos = list(
            videos_support_collection.find({"UserId": ObjectId(user_id)})
            .sort("UploadAt", DESCENDING)
            .skip(len(excluded_object_ids))
            .limit(limit)
        )

        # Separate IDs in order
        filtered_video_ids = []
        for item in saved_videos:
            pid = item.get("PostVideoId")
            if pid and ObjectId.is_valid(pid) and ObjectId(pid) not in excluded_object_ids:
                filtered_video_ids.append((ObjectId(pid), item["UploadAt"]))
            if len(filtered_video_ids) >= limit:
                break

        if not filtered_video_ids:
            return {"videos": []}

        # Get each PostVideoId
        video_id_list = [pid for pid, _ in filtered_video_ids]

        # Get images
        videos = list(videos_collection.find({"_id": {"$in": video_id_list}}))

        # Sort by UploadAt order
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

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching saved videos: {str(e)}")
