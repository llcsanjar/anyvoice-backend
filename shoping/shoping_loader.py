# backend/shoping/shoping_loader.py

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from dotenv import load_dotenv
from fastapi import Query
from bson import ObjectId
import os
from menu.menu import products_collection, users_collection, users_fs, shopings_collection, shopings_fs, shopings_like_collection, \
shopings_views_collection
import datetime
from pydantic import BaseModel
from cryptography.fernet import Fernet
import base64
from menu.menu import decrypt_data

# Load environment variables
load_dotenv()

router = APIRouter()

ENCRYPTION_KEY = os.getenv("ENCRYPTION_KEY")

# Connection Manager for WebSocket
class ConnectionManager:
    def __init__(self):
        self.active_connections: dict[str, list[WebSocket]] = {}

    async def connect(self, websocket: WebSocket, shoping_id: str):
        try:
            await websocket.accept()
            if shoping_id not in self.active_connections:
                self.active_connections[shoping_id] = []
            self.active_connections[shoping_id].append(websocket)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Error in WebSocket connect: {e}")

    def disconnect(self, websocket: WebSocket, shoping_id: str):
        try:
            if shoping_id in self.active_connections:
                if websocket in self.active_connections[shoping_id]:
                    self.active_connections[shoping_id].remove(websocket)
                if not self.active_connections[shoping_id]:
                    del self.active_connections[shoping_id]
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Error in WebSocket disconnect: {e}")

    async def broadcast(self, shoping_id: str, message: dict):
        if shoping_id in self.active_connections:
            connections_to_remove = []
            for connection in self.active_connections[shoping_id]:
                try:
                    await connection.send_json(message)
                except Exception as e:
                    connections_to_remove.append(connection)
            # Remove invalid connections
            for connection in connections_to_remove:
                self.disconnect(connection, shoping_id)

manager_shoping = ConnectionManager()

@router.websocket("/ws/updates-shoping/{shoping_id}")
async def websocket_updates(websocket: WebSocket, shoping_id: str):
    await manager_shoping.connect(websocket, shoping_id)
    try:
        while True:
            # Wait for messages to keep connection alive
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager_shoping.disconnect(websocket, shoping_id)
    except Exception as e:
        manager_shoping.disconnect(websocket, shoping_id)

@router.get("/get-shoping-preview/{shoping_id}")
async def get_shoping_preview(shoping_id: str):
    # Validate ObjectId
    if not ObjectId.is_valid(shoping_id):
        raise HTTPException(status_code=400, detail="Invalid shoping ID format")

    post_info = shopings_collection.find_one({"_id": ObjectId(shoping_id)})
    if not post_info:
        raise HTTPException(status_code=404, detail="Post not found")

    thumbnail_id = post_info.get("ThumbnailId", [])
    if not thumbnail_id:
        raise HTTPException(status_code=404, detail="No shopings found for this post")

    thumbnail_id = post_info.get("ThumbnailId")
    if thumbnail_id:
        file_thumbnail = shopings_fs.get(ObjectId(thumbnail_id))
        thumbnail_base64 = base64.b64encode(file_thumbnail.read()).decode('utf-8')
    else:
        thumbnail_base64 = ''

    user_info = users_collection.find_one({'_id': post_info['UserId']})
    if not user_info:
        raise HTTPException(status_code=404, detail="User not found")

    username = user_info['Username']
    display = user_info.get('Display', '')
    decrypted_display = decrypt_data(display, ENCRYPTION_KEY) if display else ''

    profile_image_id = user_info.get("ProfileImageId")
    if profile_image_id:
        file_avatar = users_fs.get(ObjectId(profile_image_id))
        avatar_base64 = base64.b64encode(file_avatar.read()).decode('utf-8')
    else:
        avatar_base64 = ''

    shoping_display = post_info.get('Display', '')
    decrypted_shoping_display = decrypt_data(shoping_display, ENCRYPTION_KEY) if shoping_display else ''

    data_of_shoping = post_info.get('DataOfShoping', '')
    decrypted_data_of_shoping = decrypt_data(data_of_shoping, ENCRYPTION_KEY) if data_of_shoping else ''

    return {
        "id": str(post_info['_id']),
        "shoping_name": post_info['ShopingName'],
        "shoping_thumbnail": thumbnail_base64,
        "shoping_display": decrypted_shoping_display,
        "data_of_shoping": decrypted_data_of_shoping,
        "upload_at": post_info['UploadAt'].isoformat() + "Z",
        "update_at": post_info.get('UpdateAt').isoformat() + "Z" if post_info.get('UpdateAt') else post_info.get('UpdateAt'),
        "username": str(username),
        "display": str(decrypted_display),
        "avatar": avatar_base64,
        "count_views": post_info.get('CountViews', 0),
        "count_products": post_info.get('CountProducts', 0),
        "count_likes": post_info.get('CountLike', 0),
    }

@router.get("/check-like-shoping")
def get_like_info(
    user_id: str = Query(..., description="User ID"),
    shoping_id: str = Query(..., description="Image ID")
):
    try:
        # Validate ObjectId for user_id and shoping_id
        if not ObjectId.is_valid(user_id) or not ObjectId.is_valid(shoping_id):
            return False  # Return False instead of error

        # Check if image exists in shopingsData
        shoping_exists = shopings_collection.find_one({'_id': ObjectId(shoping_id)})
        if not shoping_exists:
            return False  # Return False instead of error

        # Check like
        like = shopings_like_collection.find_one({
            'UserId': ObjectId(user_id),
            'PostShopingId': ObjectId(shoping_id),
        })

        return bool(like)  # Return True if like exists, False otherwise
    except Exception as e:
        return False  # Return False instead of error

@router.get("/get-shoping-products")
def get_shoping_products(
    shoping_id: str = Query(..., description="ID of the shoping whose products are requested"),
    limit: int = Query(20, description="Number of products to return"),
    offset: int = Query(0, description="Number of products to skip"),
    user_id: str = Query(..., description="ID of the user whose products are requested"),
):
    if not ObjectId.is_valid(shoping_id):
        raise HTTPException(status_code=400, detail="Invalid shoping_id")

    # Create ObjectId for user_id for comparison
    user_object_id = ObjectId(user_id)

    # Use filter to separate products where user is not in BlockUsersList
    cursor = products_collection.find({
        "CollaborationShopings": ObjectId(shoping_id),
        "BlockUsersList": {"$ne": user_object_id}  # Products where user is not in BlockUsersList
    }).sort("_id", -1).skip(offset).limit(limit)

    return {
        "products": [
            {
                "id": str(item["_id"]),
                "user_id": str(item["UserId"]),
            }
            for item in cursor
        ]
    }

@router.get("/like-shoping-save")
async def like_shoping_save(
    user_id: str = Query(..., description="User ID"),
    shoping_id: str = Query(..., description="Image ID")
):
    # Check if the user has already liked this image
    existing_like = shopings_like_collection.find_one({
        'UserId': ObjectId(user_id),
        'PostShopingId': ObjectId(shoping_id)
    })

    if existing_like:
        raise HTTPException(
            status_code=400,
            detail="This user has already liked this image"
        )

    shopings_like_collection.insert_one({
        'UserId': ObjectId(user_id),
        'PostShopingId': ObjectId(shoping_id),
        "UploadAt": datetime.datetime.now(datetime.timezone.utc),
    })

    shopings_collection.update_one(
        {'_id': ObjectId(shoping_id)},
        {'$inc': {'CountLike': 1}},
    )

    # Broadcast updated like count
    shoping_data = shopings_collection.find_one({'_id': ObjectId(shoping_id)})
    await manager_shoping.broadcast(shoping_id, {
        "type": "like_count",
        "value": shoping_data.get('CountLike', 0),
        "user_id": user_id,
        "like": True,
    })

    return {"success": True}

@router.get("/like-shoping-delete")
async def like_shoping_delete(
    user_id: str = Query(..., description="User ID"),
    shoping_id: str = Query(..., description="Image ID")
):
    # Check if the user has already liked this image
    existing_like = shopings_like_collection.find_one({
        'UserId': ObjectId(user_id),
        'PostShopingId': ObjectId(shoping_id)
    })

    if not existing_like:
        raise HTTPException(
            status_code=400,
            detail="This user has not liked this image or has already unliked it"
        )

    shopings_like_collection.delete_one({
        'UserId': ObjectId(user_id),
        'PostShopingId': ObjectId(shoping_id),
    })

    shopings_collection.update_one(
        {'_id': ObjectId(shoping_id)},
        {'$inc': {'CountLike': -1}},
    )

    # Broadcast updated like count
    shoping_data = shopings_collection.find_one({'_id': ObjectId(shoping_id)})
    await manager_shoping.broadcast(shoping_id, {
        "type": "like_count",
        "value": shoping_data.get('CountLike', 0),
        "user_id": user_id,
        "like": False,
    })

    return {"success": True}

class ViewEndRequest(BaseModel):
    user_id: str
    shoping_id: str

@router.post("/track-view-shoping")
async def track_view_end(request: ViewEndRequest):
    if not ObjectId.is_valid(request.user_id) or not ObjectId.is_valid(request.shoping_id):
        raise HTTPException(status_code=400, detail="Invalid user_id or shoping_id format")

    user_id = ObjectId(request.user_id)
    shoping_id = ObjectId(request.shoping_id)

    shoping = shopings_collection.find_one({"_id": shoping_id})
    if not shoping:
        raise HTTPException(status_code=404, detail="shoping not found")

    # Check: does view record already exist
    existing_view = shopings_views_collection.find_one({
        "user_id": user_id,
        "shoping_id": shoping_id
    })

    # ✅ If record does not exist, create it and increment CountViews once
    if not existing_view:
        shopings_views_collection.insert_one({
            "user_id": user_id,
            "shoping_id": shoping_id,
            "viewed_at": datetime.datetime.now(datetime.timezone.utc)
        })

        shopings_collection.update_one(
            {"_id": shoping_id},
            {"$inc": {"CountViews": 1}}
        )

        shoping_data = shopings_collection.find_one({"_id": shoping_id})

        await manager_shoping.broadcast(str(shoping_id), {
            "type": "view_count",
            "value": shoping_data.get("CountViews", 0)
        })

    # If record already exists, do nothing
    return {"success": True}
