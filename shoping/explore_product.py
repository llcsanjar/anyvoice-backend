# backend/product/product.py

from fastapi import APIRouter
from fastapi import Query
from bson import ObjectId
from typing import List
from menu.menu import products_collection

router = APIRouter()

@router.get("/get-random-products")
def get_random_products(
    limit: int = 20,
    exclude_ids: List[str] = Query(default=[]),
    user_id: str = Query(None, description="ID of the requesting user")
):
    try:
        excluded_object_ids = [ObjectId(i) for i in exclude_ids]
    except Exception as e:
        excluded_object_ids = []

    # Build the match criteria
    match_criteria = {
        "_id": {"$nin": excluded_object_ids},
        "CollaborationShopings": {"$exists": True, "$ne": []}  # Only products that have CollaborationShopings and are not empty
    }

    # If user_id is provided, add condition to exclude products where user is blocked
    if user_id and ObjectId.is_valid(user_id):
        match_criteria["BlockUsersList"] = {"$ne": ObjectId(user_id)}

    pipeline = [
        {
            "$match": match_criteria
        },
        {"$sample": {"size": limit}}
    ]

    results = list(products_collection.aggregate(pipeline))
    return {
        "products": [{"id": str(item["_id"]), "user_id": str(item["UserId"])} for item in results],
    }
