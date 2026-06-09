# backend/dispute/article/create_article.py

from fastapi import APIRouter, HTTPException
import os
from bson import ObjectId
from menu.menu import articles_collection, users_collection, users_fs, followers_collection, notifications_collection, article_likes_collection, \
article_saves_collection
from typing import List
from pydantic import BaseModel
from cryptography.fernet import Fernet
import base64
from datetime import datetime, timezone
import string
import random
from typing import Optional
from home.home import broadcast_notification, serialize_notification
from dispute.article.article_item import manager_article
from menu.menu import encrypt_data

ENCRYPTION_KEY = os.getenv("ENCRYPTION_KEY")

router = APIRouter()

def to_object_id(id_str: str) -> ObjectId:
    """Convert string to ObjectId safely"""
    try:
        return ObjectId(id_str)
    except:
        raise HTTPException(status_code=400, detail=f"Invalid ID format: {id_str}")

async def get_article_with_user(article, current_user_id=None):
    """Get article with user information and interaction status"""
    # Convert current_user_id to ObjectId if it's a string
    user_obj_id = None
    if current_user_id:
        try:
            user_obj_id = to_object_id(current_user_id) if isinstance(current_user_id, str) else current_user_id
        except:
            pass

    user = users_collection.find_one({"_id": article["user_id"]})

    # Get counts from article fields
    like_count = article.get("CountLike", 0)
    save_count = article.get("CountSave", 0)
    view_count = article.get("CountView", 0)
    comment_count = article.get("CountComment", 0)

    # Get author full name
    author_full_name = article.get("author_full_name")

    # Get avatar
    avatar_base64 = ''
    if user and user.get("ProfileImageId"):
        try:
            file_avatar = users_fs.get(ObjectId(user["ProfileImageId"]))
            avatar_base64 = base64.b64encode(file_avatar.read()).decode('utf-8')
        except:
            pass

    result = {
        "id": str(article["_id"]),
        "title": article.get("title", ""),
        "summary": article.get("summary", ""),
        "content": article.get("content", ""),
        "images": article.get("images", []),
        "user_id": str(article["user_id"]),
        "username": user.get("username", "") if user else "",
        "display_name": user.get("display_name", "") if user else "",
        "full_name": user.get("full_name", "") if user else "",
        "author_full_name": author_full_name,
        "avatar": avatar_base64,
        "likes": like_count,
        "saves": save_count,
        "views": view_count,
        "comments": comment_count,
        "link": article.get("link", ''),
        "created_at": article.get("created_at", None).isoformat() + 'Z' if article.get("created_at", None) else None,
        "updated_at": article.get("updated_at", None).isoformat() + 'Z' if article.get("updated_at", None) else None,
        "advertisement_checkbox": article.get("AdvertisementCheckbox", False),
        "advertisement_count": article.get("AdvertisementCount", 0),
    }

    if user_obj_id:
        # Check if user liked the article
        liked = article_likes_collection.find_one({
            "article_id": article["_id"],
            "user_id": user_obj_id
        })
        result["liked"] = liked is not None

        # Check if user saved the article
        saved = article_saves_collection.find_one({
            "article_id": article["_id"],
            "user_id": user_obj_id
        })
        result["saved"] = saved is not None

    return result

class ArticleCreate(BaseModel):
    title: str
    summary: str
    content: str
    images: List[str] = []
    user_id: str
    author_full_name: Optional[str] = None
    advertisement_checkbox: bool = False
    advertisement_count: int = 0

@router.post("/articles")
async def create_article(
    article_data: ArticleCreate,
):
    """Create a new article"""
    user_object_id = to_object_id(article_data.user_id)
    
    user = users_collection.find_one({"_id": user_object_id})
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # Handle advertisement payment
    advertisement_count = float(article_data.advertisement_count)
    advertisement_checkbox = article_data.advertisement_checkbox

    if advertisement_checkbox and advertisement_count > 0:
        amount = advertisement_count / 100

        # Check source user balance
        from_user_balance = user.get("Balance", 0)
        if from_user_balance < amount:
            raise HTTPException(status_code=408, detail="Insufficient balance")

        users_collection.update_one(
            {"_id": user_object_id},
            {"$inc": {"Balance": -amount}}
        )

        # Add amount to target account
        users_collection.update_one(
            {"Username": "sanjar"},
            {"$inc": {"Balance": amount}}
        )

    characters = string.ascii_letters + string.digits
    while True:
        unique_link = ''.join(random.choice(characters) for _ in range(11))
        if not articles_collection.find_one({"link": unique_link}):
            break

    article = {
        "title": article_data.title,
        "summary": article_data.summary,
        "content": article_data.content,
        "images": article_data.images,
        "user_id": user_object_id,
        "author_full_name": article_data.author_full_name or user.get("full_name", ""),
        "created_at": datetime.now(timezone.utc),
        "link": unique_link,
        "CountLike": 0,
        "CountSave": 0,
        "CountView": 0,
        "CountShare": 0,
        "CountComment": 0,
        "AdvertisementCheckbox": advertisement_checkbox,
        "AdvertisementCount": int(advertisement_count),
    }
    
    result = articles_collection.insert_one(article)

    users_collection.update_one({"_id": user_object_id}, {"$inc": {"CountPosts": 1}})
    users_collection.update_one({"_id": user_object_id}, {"$inc": {"CountArticles": 1}})

    post_id = result.inserted_id
    article_link = f"https://www.anyvoice.world/article/{unique_link}"
    
    # Send notifications to followers
    followers = followers_collection.find({"target_user_id": user_object_id})
    
    encrypted_follower_message = encrypt_data(
        f"@{user.get('Username')} added a new article. View article: {article_link}",
        ENCRYPTION_KEY
    )
    
    encrypted_follower_type = encrypt_data("new_article", ENCRYPTION_KEY)
    
    for follower in followers:
        follower_id = follower["follower_id"]
        
        if follower_id != user_object_id:
            notification_doc = {
                "NotificationFrom": user_object_id,
                "NotificationTo": follower_id,
                "Message": encrypted_follower_message,
                "PostId": post_id,
                "IsRead": False,
                "UploadAt": datetime.now(timezone.utc).isoformat().replace('Z', '+00:00'),
                "Type": encrypted_follower_type,
                "status": "pending"
            }
            
            notifications_collection.insert_one(notification_doc)
            serialized_notification = serialize_notification(notification_doc)
            await broadcast_notification(str(follower_id), "add", serialized_notification)

    article_with_user = await get_article_with_user(article, article_data.user_id)
    
    return {
        "success": True,
        "article": article_with_user
    }

class ArticleUpdate(BaseModel):
    user_id: str
    title: Optional[str] = None
    summary: Optional[str] = None
    content: Optional[str] = None
    images: Optional[List[str]] = None
    author_full_name: Optional[str] = None
    advertisement_checkbox: Optional[bool] = None
    advertisement_count: Optional[int] = None

@router.put("/articles/{article_id}")
async def update_article(
    article_id: str,
    article_data: ArticleUpdate,
):
    """Update an existing article"""
    article_object_id = to_object_id(article_id)
    user_object_id = to_object_id(article_data.user_id)
    
    article = articles_collection.find_one({"_id": article_object_id})
    if not article:
        raise HTTPException(status_code=404, detail="Article not found")
    
    if article["user_id"] != user_object_id:
        raise HTTPException(status_code=403, detail="Not authorized to edit this article")
    
    user = users_collection.find_one({"_id": user_object_id})
    
    update_data = {}
    if article_data.title is not None:
        update_data["title"] = article_data.title
    if article_data.summary is not None:
        update_data["summary"] = article_data.summary
    if article_data.content is not None:
        update_data["content"] = article_data.content
    if article_data.images is not None:
        update_data["images"] = article_data.images
    if article_data.author_full_name is not None:
        update_data["author_full_name"] = article_data.author_full_name
    
    # Handle advertisement update and payment
    advertisement_checkbox = article_data.advertisement_checkbox
    advertisement_count = article_data.advertisement_count
    
    if advertisement_checkbox is not None:
        # Get previous advertisement data
        previous_ad_count = article.get("AdvertisementCount", 0)
        previous_ad_checkbox = article.get("AdvertisementCheckbox", False)
        
        # Compare previous and new advertisement count
        if advertisement_checkbox and advertisement_count > previous_ad_count:
            additional_amount = (advertisement_count - previous_ad_count) / 100
            
            from_user_balance = user.get("Balance", 0)
            if from_user_balance < additional_amount:
                raise HTTPException(status_code=408, detail="Insufficient balance")
            
            users_collection.update_one(
                {"_id": user_object_id},
                {"$inc": {"Balance": -additional_amount}}
            )
            
            users_collection.update_one(
                {"Username": "sanjar"},
                {"$inc": {"Balance": additional_amount}}
            )
        
        update_data["AdvertisementCheckbox"] = advertisement_checkbox
        update_data["AdvertisementCount"] = int(advertisement_count)
    
    if update_data:
        update_data["updated_at"] = datetime.now(timezone.utc)
        articles_collection.update_one(
            {"_id": article_object_id},
            {"$set": update_data}
        )
    
    updated_article = articles_collection.find_one({"_id": article_object_id})
    updated_article_with_user = await get_article_with_user(updated_article, article_data.user_id)
    
    await manager_article.broadcast(article_id, {
        "type": "article_updated",
        "article": updated_article_with_user
    })
    
    return {
        "success": True,
        "article": updated_article_with_user
    }
