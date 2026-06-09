# backend/home/chat.py

from fastapi import APIRouter, HTTPException, Query
from cryptography.fernet import Fernet
import os
from bson import ObjectId
from fastapi import Query
import base64
from cryptography.fernet import Fernet
from menu.menu import users_collection, users_fs
from datetime import datetime, timezone
from typing import List
from menu.menu import images_collection, users_collection, videos_collection, products_collection, shopings_collection, \
theory_collection, articles_collection, client, shopings_fs, products_fs
from menu.menu import decrypt_data

ENCRYPTION_KEY = os.getenv("ENCRYPTION_KEY")
fernet = Fernet(ENCRYPTION_KEY)

router = APIRouter()

@router.get("/accounts")
async def get_accounts(
    user_id: str,
    search: str = "",
    selected_block_users: List[str] = Query(default=[])
):
    client.admin.command('ping')

    blocked_ids = [ObjectId(uid) for uid in selected_block_users if ObjectId.is_valid(uid)]
    current_user_id = ObjectId(user_id)

    # Basic conditions
    query = {
        "_id": {
            "$ne": current_user_id,
            "$nin": blocked_ids
        },
        "Banned": {"$ne": True}
    }

    # 🔍 Search only in Username
    if search:
        query["Username"] = {"$regex": search, "$options": "i"}

    users = users_collection.find(query, {
        "Username": 1,
        "Display": 1,
        "ProfileImageId": 1
    }).limit(10)

    accounts = []
    for user in users:
        avatar_base64 = None
        profile_image_id = user.get("ProfileImageId")

        if profile_image_id and ObjectId.is_valid(str(profile_image_id)):
            try:
                file = users_fs.get(ObjectId(profile_image_id))
                image_bytes = file.read()
                avatar_base64 = f"data:image/jpeg;base64,{base64.b64encode(image_bytes).decode('utf-8')}"
            except:
                avatar_base64 = None

        encrypted_display = user.get("Display", "")
        try:
            decrypted_display = fernet.decrypt(encrypted_display.encode()).decode()
        except:
            decrypted_display = encrypted_display

        accounts.append({
            "id": str(user["_id"]),
            "username": user.get("Username", ""),
            "display_name": decrypted_display,
            "avatar": avatar_base64
        })

    if not accounts:
        return {"message": "No accounts found for your search."}

    return accounts

@router.get("/search-images")
async def search_images(
    limit: int = Query(20, description="Number of images to return"),
    offset: int = Query(0, description="How many images to skip"),
    user_id: str = Query(None, description="ID of the requesting user"),
    search_term: str = Query("", description="Search term for title or description"),
):
    # Build match criteria
    match_criteria = {
        "Visibility": "public",
        "$or": [
            {"Title": {"$regex": search_term, "$options": "i"}},
            {"Description": {"$regex": search_term, "$options": "i"}}
        ]
    }

    # If user_id is provided, exclude images where user is blocked
    if user_id and ObjectId.is_valid(user_id):
        match_criteria["BlockUsersList"] = {"$ne": ObjectId(user_id)}

    pipeline = [
        {"$match": match_criteria},
        {"$sort": {"UploadAt": -1}},
        {"$skip": offset},
        {"$limit": limit},
    ]

    results = list(images_collection.aggregate(pipeline))
    return {
        "images": [
            {
                "id": str(item["_id"]),
                "user_id": str(item["UserId"]),
                "visibility": item.get("Visibility", "public").lower(),
                "upload_at": item["UploadAt"].isoformat() + "Z",
                "collaboration_accounts": [str(acc) for acc in item.get("CollaborationAccounts", [])]
            } for item in results
        ]
    }

@router.get("/search-videos")
async def search_videos(
    limit: int = Query(20, description="Number of videos to return"),
    offset: int = Query(0, description="How many videos to skip"),
    user_id: str = Query(None, description="ID of the requesting user"),
    search_term: str = Query("", description="Search term for title or description"),
):
    # Build match criteria
    match_criteria = {
        "Visibility": "public",
        "$or": [
            {"Title": {"$regex": search_term, "$options": "i"}},
            {"Description": {"$regex": search_term, "$options": "i"}}
        ]
    }

    # If user_id is provided, exclude videos where user is blocked
    if user_id and ObjectId.is_valid(user_id):
        match_criteria["BlockUsersList"] = {"$ne": ObjectId(user_id)}

    pipeline = [
        {"$match": match_criteria},
        {"$sort": {"UploadAt": -1}},
        {"$skip": offset},
        {"$limit": limit},
    ]

    results = list(videos_collection.aggregate(pipeline))
    return {
        "videos": [
            {
                "id": str(item["_id"]),
                "user_id": str(item["UserId"]),
                "visibility": item.get("Visibility", "public").lower(),
                "upload_at": item["UploadAt"].isoformat() + "Z",
                "collaboration_accounts": [str(acc) for acc in item.get("CollaborationAccounts", [])]
            } for item in results
        ]
    }

@router.get("/search-shopings")
def search_shopings(
    search_term: str = Query(..., description="Search text"),
    limit: int = Query(10, description="Number of shops"),
    offset: int = Query(0, description="Number of shops to skip"),
    user_id: str = Query(..., description="ID of the requesting user")
):
    if not ObjectId.is_valid(user_id):
        raise HTTPException(status_code=400, detail="Invalid user ID format")

    # Create search pattern for shop name
    search_regex = {"$regex": f".*{search_term}.*", "$options": "i"}

    # Search in shops
    cursor = shopings_collection.find({
        "$or": [
            {"ShopingName": search_regex},
        ]
    }).sort("UploadAt", -1).skip(offset).limit(limit)

    shopings_list = []
    for shoping in cursor:
        # Get thumbnail
        thumbnail_id = shoping.get("ThumbnailId")
        thumbnail_base64 = ''
        if thumbnail_id:
            try:
                file_thumbnail = shopings_fs.get(ObjectId(thumbnail_id))
                thumbnail_base64 = base64.b64encode(file_thumbnail.read()).decode('utf-8')
            except Exception:
                thumbnail_base64 = ''

        # Decrypt display
        display = shoping.get('Display', '')
        decrypted_display = decrypt_data(display, ENCRYPTION_KEY) if display else ''

        shopings_list.append({
            "id": str(shoping["_id"]),
            "user_id": str(shoping["UserId"]),
            "shoping_name": shoping["ShopingName"],
            "display": decrypted_display,
            "thumbnail": thumbnail_base64,
            "count_views": shoping.get("CountViews", 0),
            "count_products": shoping.get("CountProducts", 0),
            "count_likes": shoping.get("CountLike", 0),
            "upload_at": shoping.get("UploadAt")
        })

    return {
        "shopings": shopings_list,
        "total": len(shopings_list),
        "has_more": len(shopings_list) == limit
    }

@router.get("/search-products")
async def search_products(
    user_id: str = Query(...),
    search_term: str = Query(""),
    limit: int = Query(10),
    offset: int = Query(0),
    min_price: float = Query(None),
    max_price: float = Query(None),
    product_type: str = Query(None),
    sort_by: str = Query("newest")
):
    # Create search conditions
    query_conditions = {}

    # Search in Title and DataOfProduct
    if search_term:
        query_conditions["$or"] = [
            {"Title": {"$regex": search_term, "$options": "i"}},
            {"DataOfProduct": {"$regex": search_term, "$options": "i"}}
        ]

    # Price filter
    price_filter = {}
    if min_price is not None:
        price_filter["$gte"] = min_price
    if max_price is not None:
        price_filter["$lte"] = max_price
    if price_filter:
        query_conditions["PriceProduct"] = price_filter

    # Product type filter
    if product_type == 'personal-sales':
        query_conditions["PersonalProductSales"] = True

    elif product_type:
        query_conditions["ProductType"] = product_type

    # Create sort order
    sort_field = "UploadAt"
    sort_direction = -1  # descending

    if sort_by == "price_low":
        sort_field = "PriceProduct"
        sort_direction = 1  # ascending
    elif sort_by == "price_high":
        sort_field = "PriceProduct"
        sort_direction = -1  # descending
    elif sort_by == "most_bought":
        sort_field = "CountBuy"
        sort_direction = -1  # descending
    elif sort_by == "newest":
        sort_field = "UploadAt"
        sort_direction = -1  # descending

    # Execute search in database
    products_cursor = products_collection.find(
        query_conditions
    ).sort(sort_field, sort_direction).skip(offset).limit(limit)

    products = []
    for product in products_cursor:
        if user_id and ObjectId.is_valid(user_id):
            block_list = product.get("BlockUsersList", [])
            block_object_ids = [
                ObjectId(uid) for uid in block_list if ObjectId.is_valid(str(uid))
            ]
            if ObjectId(user_id) in block_object_ids:
                continue

        # Get user information
        user_data = users_collection.find_one({"_id": product["UserId"]})
        avatar_base64 = None

        if user_data and "Avatar" in user_data:
            avatar_file = users_collection.files.get(user_data["Avatar"])
            if avatar_file:
                avatar_bytes = avatar_file.read()
                avatar_base64 = f"data:image/jpeg;base64,{base64.b64encode(avatar_bytes).decode('utf-8')}"

        # Get product image
        product_image = None
        if product.get("ProductImageIds"):
            try:
                image_file = products_fs.get(ObjectId(product["ProductImageIds"][0]))
                image_bytes = image_file.read()
                product_image = f"data:image/jpeg;base64,{base64.b64encode(image_bytes).decode('utf-8')}"
            except:
                pass

        products.append({
            "id": str(product["_id"]),
            "user_id": str(product["UserId"]),
            "title": product["Title"],
            "data_of_product": product["DataOfProduct"],
            "price": product.get("PriceProduct", 0),
            "product_type": product.get("ProductType", ""),
            "count_buy": product.get("CountBuy", 0),
            "upload_at": product["UploadAt"].isoformat() + "Z",
            "user_avatar": avatar_base64,
            "product_image": product_image,
            "username": user_data.get("Username", "") if user_data else ""
        })

    return {"products": products}

@router.get("/search-theories")
async def search_theories(
    limit: int = Query(20, description="Number of theories to return"),
    offset: int = Query(0, description="How many theories to skip"),
    user_id: str = Query(None, description="ID of the requesting user"),
    search_term: str = Query("", description="Search term for title or description"),
):
    match_criteria = {
        "$or": [
            {"name": {"$regex": search_term, "$options": "i"}},
            {"definition": {"$regex": search_term, "$options": "i"}},
            {"additional_info": {"$regex": search_term, "$options": "i"}},
        ]
    }

    pipeline = [
        {"$match": match_criteria},
        {"$sort": {"created_at": -1}},
        {"$skip": offset},
        {"$limit": limit},
    ]

    results = list(theory_collection.aggregate(pipeline))

    theories_list = []

    for the in results:
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

        # EXACT FORMAT FOR FRONTEND
        theories_list.append({
            "id": str(the["_id"]),
            "user_id": str(the["user_id"]),
            "theory_data": theory_data
        })

    return {
        "theories": theories_list
    }

@router.get("/search-articles")
async def search_articles(
    limit: int = Query(20, description="Number of articles to return"),
    offset: int = Query(0, description="How many articles to skip"),
    user_id: str = Query(None, description="ID of the requesting user"),
    search_term: str = Query("", description="Search term for author_full_name, title, summary or content"),
):
    match_criteria = {
        "$or": [
            {"author_full_name": {"$regex": search_term, "$options": "i"}},
            {"title": {"$regex": search_term, "$options": "i"}},
            {"summary": {"$regex": search_term, "$options": "i"}},
            {"content": {"$regex": search_term, "$options": "i"}},
        ]
    }

    pipeline = [
        {"$match": match_criteria},
        {"$sort": {"created_at": -1}},
        {"$skip": offset},
        {"$limit": limit},
    ]

    results = list(articles_collection.aggregate(pipeline))
    
    articles_list = []
    
    for article in results:
        try:
            articles_list.append({"id": str(article["_id"])})
        except Exception as e:
            print(f"Error processing article {article.get('_id')}: {e}")
            continue
    
    return {
        "articles": articles_list
    }
