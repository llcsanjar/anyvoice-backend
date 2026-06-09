# backend/explore/explore_image.py

from fastapi import APIRouter
from bson import ObjectId
from fastapi import Query
from typing import List
from menu.menu import images_collection

router = APIRouter()

@router.get("/get-random-images")
def get_random_images(
    limit: int = 20,
    exclude_ids: List[str] = Query(default=[]),
    user_id: str = Query(None, description="ID of the requesting user")
):
    try:
        excluded_object_ids = [ObjectId(i) for i in exclude_ids]
    except Exception:
        excluded_object_ids = []

    # Build the match criteria
    match_criteria = {
        "_id": {"$nin": excluded_object_ids},
        "Visibility": "public",
        "Banned": {"$ne": True}
    }

    # If user_id is provided, exclude images where requesting user is blocked
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

    results = list(images_collection.aggregate(pipeline))

    return {
        "images": [
            {
                "id": str(item["_id"]),
                "user_id": str(item["UserId"])
            }
            for item in results
        ],
    }
