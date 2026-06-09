# backend/explore/explore_video.py

from fastapi import APIRouter, Query
from bson import ObjectId
from typing import List
from menu.menu import videos_collection

router = APIRouter()

@router.get("/get-random-videos")
def get_random_videos(
    limit: int = 20,
    exclude_ids: List[str] = Query(default=[]),
    user_id: str = Query(None, description="ID of the requesting user")
):
    try:
        excluded_object_ids = [ObjectId(i) for i in exclude_ids]
    except Exception:
        excluded_object_ids = []

    match_criteria = {
        "_id": {"$nin": excluded_object_ids},
        "Visibility": "public",
        "Banned": {"$ne": True}
    }

    if user_id and ObjectId.is_valid(user_id):
        match_criteria["BlockUsersList"] = {"$ne": ObjectId(user_id)}

    pipeline = [
        {
            "$match": match_criteria
        },
        {
            "$sample": {"size": limit}
        }
    ]

    results = list(videos_collection.aggregate(pipeline))

    return {
        "videos": [
            {
                "id": str(item["_id"]),
                "user_id": str(item["UserId"])
            }
            for item in results
        ],
    }
