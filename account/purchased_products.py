# backend/account/purchased_products.py

from fastapi import APIRouter, HTTPException, Query
from bson import ObjectId
from menu.menu import products_buy_collection, products_collection
from pymongo import DESCENDING
from typing import List

router = APIRouter()

@router.get("/get-user-buyed-products")
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

    try:
        # Saved images with BuyIn (save time)
        saved_products = list(
            products_buy_collection.find({"UserId": ObjectId(user_id)})
            .sort("BuyIn", DESCENDING)
            .skip(len(excluded_object_ids))
            .limit(limit)
        )

        # Separate IDs in order
        filtered_product_ids = []
        for item in saved_products:
            pid = item.get("PostProductId")
            if pid and ObjectId.is_valid(pid) and ObjectId(pid) not in excluded_object_ids:
                filtered_product_ids.append((ObjectId(pid), item["BuyIn"]))
            if len(filtered_product_ids) >= limit:
                break

        if not filtered_product_ids:
            return {"products": []}

        # Get each PostProductId
        product_id_list = [pid for pid, _ in filtered_product_ids]

        # Get images
        products = list(products_collection.find({"_id": {"$in": product_id_list}}))

        # Sort by UploadAt order
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
                })

        return {"products": sorted_results}

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching saved images: {str(e)}")
