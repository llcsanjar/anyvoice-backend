# backend/menu/menu.py

from cryptography.fernet import Fernet
from fastapi import APIRouter, HTTPException
from pymongo import MongoClient
from gridfs import GridFS
from bson import ObjectId
import os
from dotenv import load_dotenv
from fastapi import Body
import uuid
from datetime import datetime, timedelta

# Load environment variables
load_dotenv()
ENCRYPTION_KEY = os.getenv("ENCRYPTION_KEY")
MONGO_URI = os.getenv("MONGO_URI")

router = APIRouter()
# 🔗 Connecting to MongoDB
client = MongoClient(MONGO_URI,
                    connectTimeoutMS=0,
                    serverSelectionTimeoutMS=0,
                    socketTimeoutMS=0
                    )

# AuthDB
users_db = client["AuthDB"]
users_fs = GridFS(users_db)
users_collection = users_db["Users"]
followers_collection = users_db["Followers"]
temp_codes_db = users_db["TempCodes"]
sessions = users_db["Sessions"]
user_status_collection = users_db["UserStatus"]
recovery_codes_collection = users_db["RecoveryCodes"]

# Images
images_db = client["Images"]
images_fs = GridFS(images_db)
images_collection = images_db["ImagesData"]
images_support_collection = images_db["Support"]
images_comment_collection = images_db["Comments"]
images_views_collection = images_db['ImageViews']
images_comment_likes = images_db["CommentLikes"]
images_save_collection = images_db['SaveImages']

# Videos
videos_db = client["Videos"]
videos_fs = GridFS(videos_db)
videos_collection = videos_db["VideosData"]
videos_support_collection = videos_db["Support"]
videos_comment_collection = videos_db["Comments"]
videos_views_collection = videos_db['VideoViews']
videos_save_collection = videos_db['SaveVideos']
videos_comment_likes = videos_db["CommentLikes"]

# Messages
messages_db = client["Messages"]
messages_collection = messages_db["Messages"]

# Notifications
notifications_db = client["Notifications"]
notifications_collection = notifications_db["NotificationsData"]

# Shopings
shopings_db = client["Shopings"]
shopings_fs = GridFS(shopings_db)
shopings_collection = shopings_db["ShopingsData"]
shopings_views_collection = shopings_db["ShopingsViews"]
shopings_like_collection = shopings_db["Likes"]

# Products
products_db = client["Products"]
products_fs = GridFS(products_db)
products_collection = products_db["ProductsData"]
products_buy_collection = products_db["Buy"]
products_comment_collection = products_db["Comments"]
products_views_collection = products_db['ProductViews']
files_products_collection = products_db['FilesMetadata']
product_comment_likes = products_db["CommentLikes"]
products_save_collection = products_db["SaveProducts"]
physical_product_purchases_collection = products_db["PhysicalProductPurchases"]

# Money
withdrawal_requests_db = client["Money"]
withdrawal_requests_collection = withdrawal_requests_db["withdrawal_requests"]
withdrawal_requests_password = withdrawal_requests_db['Password']

# Theory
theory_db = client["Theory"]
theory_collection = theory_db["TheoryData"]
theory_readings_collection = theory_db["TheoryReadings"]
theories_comment_collection = theory_db["Comments"]
theories_comment_likes = theory_db["CommentLikes"]
theories_save_collection = theory_db["SaveTheories"]
theory_confirmations_collection = theory_db["Confirmations"]
theory_rejections_collection = theory_db["Rejections"]

# Ads
ads_db = client["Ads"]
viewed_ads_collection = ads_db["viewed_advertisements"]

# Articles
articles_db = client["Articles"]
articles_collection = articles_db["ArticlesData"]
article_likes_collection = articles_db["ArticleLikes"]
article_saves_collection = articles_db["ArticleSaves"]
article_views_collection = articles_db['ArticleViews']
article_reports_collection = articles_db["ArticleReports"]
article_comment_collection = articles_db["Comments"]
article_comment_likes = articles_db["CommentLikes"]

# Report
reports_db = client["Reports"]
reports_of_theory = reports_db["TheoryReports"]
reports_of_product = reports_db["ProductReports"]
reports_of_video = reports_db["VideoReports"]
reports_of_image = reports_db["ImageReports"]
reports_of_article = reports_db["ArticleReports"]
reports_of_account = reports_db["AccountReports"]

def decrypt_data(encrypted_data: str, key: str) -> str:
    fernet = Fernet(key.encode())
    return fernet.decrypt(encrypted_data.encode()).decode()

def encrypt_data(data: str, key: str) -> str:
    fernet = Fernet(key.encode())
    return fernet.encrypt(data.encode()).decode()

@router.post("/verify-token")
async def verify_token(token_data: dict = Body(...)):
    token = token_data.get("token")

    try:
        ENCRYPTION_KEY = os.getenv("ENCRYPTION_KEY")
        decrypted_token = decrypt_data(token, ENCRYPTION_KEY)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid token format")

    session = sessions.find_one({"token": decrypted_token})
    new_token = str(uuid.uuid4())

    if not session:
        return {
            "token_refreshed": True,
            "new_token": encrypt_data(new_token, ENCRYPTION_KEY)
        }

    user = users_collection.find_one({"_id": ObjectId(session["user_id"])})
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    now = datetime.utcnow()
    if session["expires"] < now:
        new_expiry = now + timedelta(minutes=15)

        sessions.update_one(
            {"_id": session["_id"]},
            {"$set": {"token": new_token, "expires": new_expiry}}
        )

        return {
            "user_id": str(user["_id"]),
            "token_refreshed": True,
            "new_token": encrypt_data(new_token, ENCRYPTION_KEY)
        }

    return {"user_id": str(user["_id"]), "token_refreshed": False}

@router.post("/check-link-article")
async def check_link_article(link_data: dict):
    client.admin.command('ping')

    link = link_data.get("link")

    if not link:
        raise HTTPException(status_code=400, detail="link is required")

    article = articles_collection.find_one({"link": link})
    if not article:
        raise HTTPException(status_code=406, detail="link is wrong")

    article_id = str(article["_id"])
    article_user_id = str(article["user_id"])

    user_info = users_collection.find_one({'_id': ObjectId(article_user_id)})
    if not user_info:
        raise HTTPException(status_code=405, detail="User not found")

    username = user_info['Username']
    display = user_info.get('Display', '')
    decrypted_display = decrypt_data(display, ENCRYPTION_KEY) if display else ''

    return {
        "exists": True,
        "article_id": article_id,
        "user_id": article_user_id,
        "username": username,
        "display": decrypted_display,
        "article_user_id": article_user_id,
    }
