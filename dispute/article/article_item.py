# backend/dispute/article/article_item.py

from fastapi import APIRouter, HTTPException, Query, WebSocket, WebSocketDisconnect
import os
import base64
from bson import ObjectId
from datetime import datetime, timezone
from pydantic import BaseModel
from menu.menu import users_collection, users_fs, notifications_collection, article_comment_likes, articles_collection, \
article_comment_collection, article_likes_collection, article_saves_collection, article_views_collection, messages_collection, \
reports_of_article
from home.chat import manager_chat
from menu.menu import decrypt_data, encrypt_data
from home.home import send_email

ENCRYPTION_KEY = os.getenv("ENCRYPTION_KEY")
my_email = os.getenv("MY_EMAIL")

router = APIRouter()

# Connection Manager for WebSocket
class ConnectionManager:
    def __init__(self):
        self.active_connections: dict[str, list[WebSocket]] = {}

    async def connect(self, websocket: WebSocket, article_id: str):
        try:
            await websocket.accept()
            if article_id not in self.active_connections:
                self.active_connections[article_id] = []
            self.active_connections[article_id].append(websocket)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Error in WebSocket connect: {e}")

    def disconnect(self, websocket: WebSocket, article_id: str):
        try:
            if article_id in self.active_connections:
                if websocket in self.active_connections[article_id]:
                    self.active_connections[article_id].remove(websocket)
                if not self.active_connections[article_id]:
                    del self.active_connections[article_id]
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Error in WebSocket disconnect: {e}")

    async def broadcast(self, article_id: str, message: dict):
        if article_id in self.active_connections:
            connections_to_remove = []
            for connection in self.active_connections[article_id]:
                try:
                    await connection.send_json(message)
                except Exception:
                    connections_to_remove.append(connection)
            for connection in connections_to_remove:
                self.disconnect(connection, article_id)

manager_article = ConnectionManager()

@router.websocket("/ws/updates-article/{article_id}")
async def websocket_updates(websocket: WebSocket, article_id: str):
    await manager_article.connect(websocket, article_id)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager_article.disconnect(websocket, article_id)
    except Exception:
        manager_article.disconnect(websocket, article_id)

def to_object_id(id_str: str) -> ObjectId:
    """Convert string to ObjectId safely"""
    try:
        return ObjectId(id_str)
    except:
        raise HTTPException(status_code=400, detail=f"Invalid ID format: {id_str}")

async def get_article_with_user(article, current_user_id=None):
    """Get article with user information and interaction status"""

    if article.get('Banned', False):
        return {
            'is_banned': article.get('Banned', False),
        }

    # Convert current_user_id to ObjectId if it's a string
    user_obj_id = None
    if current_user_id:
        try:
            user_obj_id = to_object_id(current_user_id) if isinstance(current_user_id, str) else current_user_id
        except:
            pass

    user = users_collection.find_one({"_id": article["user_id"]})

    if user.get("Banned", False):
        return {
            "is_banned": True
        }

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
        "is_banned": article.get("Banned", False),
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

@router.get("/articles/{article_id}")
async def get_article(
    article_id: str,
    user_id: str
):
    """Get a single article by ID"""
    article_object_id = to_object_id(article_id)

    article = articles_collection.find_one({"_id": article_object_id})
    if not article:
        raise HTTPException(status_code=404, detail="Article not found")

    updated_article = articles_collection.find_one({"_id": article_object_id})
    return await get_article_with_user(updated_article, user_id)

@router.delete("/articles/{article_id}")
async def delete_article(
    article_id: str,
    user_id: str,
):
    """Delete an article"""
    article_object_id = to_object_id(article_id)
    user_object_id = to_object_id(user_id)
    
    article = articles_collection.find_one({"_id": article_object_id})
    if not article:
        raise HTTPException(status_code=404, detail="Article not found")
    
    if article["user_id"] != user_object_id:
        raise HTTPException(status_code=403, detail="Not authorized to delete this article")
    
    # Collect all comment IDs for this article
    all_comment_ids = []
    
    top_comments = article_comment_collection.find({
        "article_id": article_object_id,
        "parent_comment_id": None
    })
    
    def collect_nested_replays(parent_id):
        nested_replays = article_comment_collection.find({
            "parent_comment_id": parent_id
        })
        for nested in nested_replays:
            all_comment_ids.append(nested["_id"])
            collect_nested_replays(nested["_id"])
    
    for comment in top_comments:
        all_comment_ids.append(comment["_id"])
        for replay_id in comment.get("replays", []):
            replay = article_comment_collection.find_one({"_id": replay_id})
            if replay:
                all_comment_ids.append(replay["_id"])
                collect_nested_replays(replay["_id"])
    
    # Delete comments
    if all_comment_ids:
        article_comment_collection.delete_many({"_id": {"$in": all_comment_ids}})
        article_comment_likes.delete_many({"comment_id": {"$in": all_comment_ids}})
    
    # Delete article and related data
    articles_collection.delete_one({"_id": article_object_id})
    article_likes_collection.delete_many({"article_id": article_object_id})
    article_saves_collection.delete_many({"article_id": article_object_id})
    article_views_collection.delete_many({"article_id": article_object_id})
    article_comment_likes.delete_many({"article_id": article_object_id})
    article_comment_collection.delete_many({"article_id": article_object_id})
    notifications_collection.delete_many({"PostId": article_object_id})

    users_collection.update_one({"_id": user_object_id}, {"$inc": {"CountPosts": -1}})
    users_collection.update_one({"_id": user_object_id}, {"$inc": {"CountArticles": -1}})

    await manager_article.broadcast(article_id, {
        "type": "article_deleted",
        "article_id": article_id
    })
    
    return {"success": True, "message": "Article deleted successfully"}

@router.post("/articles/{article_id}/view")
async def register_article_view(
    article_id: str,
    user_id: str = Query(..., description="ID of the user viewing the article")
):
    """Register a view for an article"""

    article_object_id = to_object_id(article_id)
    user_object_id = to_object_id(user_id)
    
    article = articles_collection.find_one({"_id": article_object_id})
    if not article:
        raise HTTPException(status_code=404, detail="Article not found")
    
    # Санҷед, ки оё ин корбар аллакай ин мақоларо тамошо кардааст
    existing_view = article_views_collection.find_one({
        "article_id": article_object_id,
        "user_id": user_object_id
    })
    
    if not existing_view:
        # Сабти тамошои нав
        article_views_collection.insert_one({
            "article_id": article_object_id,
            "user_id": user_object_id,
            "viewed_at": datetime.now(timezone.utc)
        })
        
        # Зиёд кардани миқдори тамошо дар мақола
        articles_collection.update_one(
            {"_id": article_object_id},
            {"$inc": {"CountView": 1}}
        )
        
        # Гирифтани миқдори нави тамошо
        updated_article = articles_collection.find_one({"_id": article_object_id})
        new_view_count = updated_article.get("CountView", 0)
        
        # Обнавитсозӣ тавассути WebSocket
        await manager_article.broadcast(article_id, {
            "type": "view_update",
            "count": new_view_count,
            "user_id": user_id
        })
        
        return {
            "success": True,
            "views": new_view_count,
            "message": "View registered successfully"
        }
    else:
        # Ин корбар аллакай ин мақоларо тамошо кардааст
        return {
            "success": True,
            "views": article.get("CountView", 0),
            "message": "View already registered"
        }

class ArticleLike(BaseModel):
    user_id: str

@router.post("/articles/{article_id}/like")
async def like_article(
    article_id: str,
    like_data: ArticleLike,
):
    """Like or unlike an article"""
    article_object_id = to_object_id(article_id)
    user_object_id = to_object_id(like_data.user_id)
    
    article = articles_collection.find_one({"_id": article_object_id})
    if not article:
        raise HTTPException(status_code=404, detail="Article not found")
    
    existing_like = article_likes_collection.find_one({
        "article_id": article_object_id,
        "user_id": user_object_id
    })
    
    if existing_like:
        article_likes_collection.delete_one({"_id": existing_like["_id"]})
        liked = False
        articles_collection.update_one(
            {"_id": article_object_id},
            {"$inc": {"CountLike": -1}}
        )
    else:
        article_likes_collection.insert_one({
            "article_id": article_object_id,
            "user_id": user_object_id,
            "liked_at": datetime.now(timezone.utc)
        })
        liked = True
        articles_collection.update_one(
            {"_id": article_object_id},
            {"$inc": {"CountLike": 1}}
        )
    
    updated_article = articles_collection.find_one({"_id": article_object_id})
    count = updated_article.get("CountLike", 0)
    
    await manager_article.broadcast(article_id, {
        "type": "like_update",
        "count": count,
        "liked": liked,
        "user_id": like_data.user_id
    })
    
    return {"success": True, "liked": liked, "count": count}

class ArticleSave(BaseModel):
    user_id: str

@router.post("/articles/{article_id}/save")
async def save_article(
    article_id: str,
    save_data: ArticleSave,
):
    """Save or unsave an article"""
    article_object_id = to_object_id(article_id)
    user_object_id = to_object_id(save_data.user_id)
    
    article = articles_collection.find_one({"_id": article_object_id})
    if not article:
        raise HTTPException(status_code=404, detail="Article not found")
    
    existing_save = article_saves_collection.find_one({
        "article_id": article_object_id,
        "user_id": user_object_id
    })
    
    if existing_save:
        article_saves_collection.delete_one({"_id": existing_save["_id"]})
        saved = False
        articles_collection.update_one(
            {"_id": article_object_id},
            {"$inc": {"CountSave": -1}}
        )
    else:
        article_saves_collection.insert_one({
            "article_id": article_object_id,
            "user_id": user_object_id,
            "saved_at": datetime.now(timezone.utc)
        })
        saved = True
        articles_collection.update_one(
            {"_id": article_object_id},
            {"$inc": {"CountSave": 1}}
        )
    
    updated_article = articles_collection.find_one({"_id": article_object_id})
    count = updated_article.get("CountSave", 0)
    
    await manager_article.broadcast(article_id, {
        "type": "save_update",
        "count": count,
        "saved": saved,
        "user_id": save_data.user_id
    })
    
    return {"success": True, "saved": saved, "count": count}

class ArticleShareMessage(BaseModel):
    from_user_id: str
    to_user_id: str
    article_id: str

@router.post("/share-article")
async def share_article(share: ArticleShareMessage):
    """Share an article to another user"""
    created_at = datetime.now(timezone.utc)
    
    article = articles_collection.find_one({"_id": to_object_id(share.article_id)})
    if not article:
        raise HTTPException(status_code=404, detail="Article not found")
    
    article_link = f"https://www.anyvoice.world/article/{article.get('link', str(share.article_id))}"
    
    result = messages_collection.insert_one({
        "from_user_id": to_object_id(share.from_user_id),
        "to_user_id": to_object_id(share.to_user_id),
        "message": article_link,
        "article_id": to_object_id(share.article_id),
        "created_at": created_at,
        "is_deleted": False,
        "is_edited": False,
        "is_read": False,
        "type": "article"
    })
    message_id = str(result.inserted_id)

    articles_collection.update_one(
        {"_id": to_object_id(share.article_id)},
        {"$inc": {"CountShare": 1}}
    )

    updated_article = articles_collection.find_one({"_id": to_object_id(share.article_id)})

    await manager_article.broadcast(share.article_id, {
        "type": "share_count",
        "value": updated_article.get("CountShare", 0)
    })

    user_data = users_collection.find_one({"_id": to_object_id(share.from_user_id)})
    if not user_data:
        raise HTTPException(status_code=404, detail="User not found")
    
    decrypted_display = decrypt_data(user_data.get('Display', ''), ENCRYPTION_KEY) if user_data.get('Display') else ''
    
    message_payload = {
        "type": "new_messanger",
        "value": {
            'from_user_id': str(share.from_user_id),
            'to_user_id': str(share.to_user_id),
            'username': user_data['Username'],
            'display': decrypted_display,
            'message': article_link,
            'article_id': share.article_id,
            'article_title': article.get('title', ''),
            'created_at': created_at.isoformat() + "Z",
            'message_id': message_id,
            "is_edited": False,
            "type": "article"
        },
    }
    
    await manager_chat.broadcast(str(share.from_user_id), message_payload)
    await manager_chat.broadcast(str(share.to_user_id), message_payload)

    await manager_article.broadcast(share.article_id, {
        "type": "share_update",
        "count": updated_article.get("CountShare", 0),
    })

    return {"success": True, "message_id": message_id}

@router.post("/cancel-share-article")
async def cancel_share_article(share: ArticleShareMessage):
    from_id = to_object_id(share.from_user_id)
    to_id = to_object_id(share.to_user_id)
    article_id = to_object_id(share.article_id)

    article = articles_collection.find_one({"_id": article_id})
    if not article:
        raise HTTPException(status_code=404, detail="Article not found")

    article_link = f"https://www.anyvoice.world/article/{article.get('link', str(share.article_id))}"

    message = messages_collection.find_one({
        "from_user_id": from_id,
        "to_user_id": to_id,
        "message": article_link,
        "type": "article",
        "is_deleted": False,
    }, sort=[("created_at", -1)])

    if not message:
        raise HTTPException(status_code=404, detail="Message not found")

    if message.get("is_deleted", False):
        raise HTTPException(status_code=400, detail="Already deleted")

    deleted_at = datetime.now(timezone.utc)

    messages_collection.update_one(
        {"_id": message["_id"]},
        {
            "$set": {
                "is_deleted": True,
                "deleted_by": from_id,
                "deleted_at": deleted_at
            }
        }
    )

    replied_messages = list(messages_collection.find({
        "reply_to_message_id": message["_id"],
        "is_deleted": {"$ne": True}
    }))

    user_data = users_collection.find_one({"_id": from_id})
    if not user_data:
        raise HTTPException(status_code=404, detail="User not found")

    decrypted_display = decrypt_data(user_data.get('Display', ''), ENCRYPTION_KEY) if user_data.get('Display') else ''

    message_payload = {
        "type": "delete_messanger",
        "value": {
            'from_user_id': str(message["from_user_id"]),
            'to_user_id': str(message["to_user_id"]),
            'username': user_data['Username'],
            'display': decrypted_display,
            'message_id': str(message["_id"]),
            'created_at': message["created_at"].isoformat(),
            "is_deleted": True,
            "deleted_by": str(from_id),
            "deleted_at": deleted_at.isoformat(),
            "type": "article"
        },
    }

    await manager_chat.broadcast(str(message["from_user_id"]), message_payload)
    await manager_chat.broadcast(str(message["to_user_id"]), message_payload)

    for reply_msg in replied_messages:
        updated_reply_info = {
            "message_id": str(message["_id"]),
            "text": "[Deleted article]",
            "from_username": user_data['Username'],
            "from_user_id": str(message["from_user_id"]),
            "message_type": "article",
            "is_deleted": True
        }

        update_payload = {
            "type": "update_reply_info",
            "value": {
                "message_id": str(reply_msg["_id"]),
                "reply_to": updated_reply_info
            }
        }

        await manager_chat.broadcast(str(reply_msg["from_user_id"]), update_payload)
        await manager_chat.broadcast(str(reply_msg["to_user_id"]), update_payload)

    articles_collection.update_one(
        {"_id": article_id},
        {"$inc": {"CountShare": -1}}
    )

    updated_article = articles_collection.find_one({"_id": article_id})

    await manager_article.broadcast(share.article_id, {
        "type": "share_count",
        "value": updated_article.get("CountShare", 0)
    })

    await manager_article.broadcast(share.article_id, {
        "type": "share_update",
        "count": updated_article.get("CountShare", 0),
    })

    return {"success": True}

class ArticleReportRequest(BaseModel):
    user_id: str
    article_id: str
    reason: str

@router.post("/report-article")
async def report_article(request: ArticleReportRequest):
    # Validate ObjectId
    if not ObjectId.is_valid(request.user_id) or not ObjectId.is_valid(request.article_id):
        raise HTTPException(status_code=400, detail="Invalid user_id or article_id format")

    # Check if comment exists
    article = articles_collection.find_one({"_id": ObjectId(request.article_id)})
    if not article:
        raise HTTPException(status_code=404, detail="article not found")

    # Check if user exists
    user = users_collection.find_one({"_id": ObjectId(request.user_id)})
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # Check for duplicate report
    existing_report = reports_of_article.find_one({
        "user_id": ObjectId(request.user_id),
        "article_id": ObjectId(request.article_id)
    })
    if existing_report:
        raise HTTPException(status_code=401, detail="You have already reported this article")

    # Encrypt reason
    encrypted_reason = encrypt_data(request.reason, ENCRYPTION_KEY)

    # Save report in ArticleReports table
    report_data = {
        "user_id": ObjectId(request.user_id),
        "article_id": ObjectId(request.article_id),
        "reason": encrypted_reason,
        "created_at": datetime.now(timezone.utc)
    }
    reports_of_article.insert_one(report_data)

    send_email(
        recipient=my_email,
        message=f"""Шикоят аз мақолаи https://www.anyvoice.world/article/{article["link"]}.\n
        Шикоят кунанда: @{user['Username']}\n
        Сабаб: {request.reason}\n""",
        subject='Шикоят⚠️'
    )

    return {"success": True}
