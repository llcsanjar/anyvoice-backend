# backend/account/account.py

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect, Query
from typing import List
from bson import ObjectId
from pymongo import DESCENDING
import os
import base64
from cryptography.fernet import Fernet
from pydantic import BaseModel
from menu.menu import client, users_fs, users_collection, followers_collection, videos_collection, images_collection, products_collection, \
withdrawal_requests_collection, notifications_collection, shopings_collection, articles_collection, theory_collection, reports_of_account
from fastapi import HTTPException, status
from home.home import serialize_notification, broadcast_notification, send_email
from datetime import datetime, timezone
from menu.menu import encrypt_data, decrypt_data

ENCRYPTION_KEY = os.getenv("ENCRYPTION_KEY")
my_email = os.getenv("MY_EMAIL")

fernet = Fernet(ENCRYPTION_KEY)

router = APIRouter()

# Connection Manager for WebSocket
class ConnectionManagerAccount:
    def __init__(self):
        self.active_connections: dict[str, list[WebSocket]] = {}

    async def connect(self, websocket: WebSocket, user_id: str):
        try:
            await websocket.accept()
            if user_id not in self.active_connections:
                self.active_connections[user_id] = []
            self.active_connections[user_id].append(websocket)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Error in WebSocket connect: {e}")

    def disconnect(self, websocket: WebSocket, user_id: str):
        try:
            if user_id in self.active_connections:
                if websocket in self.active_connections[user_id]:
                    self.active_connections[user_id].remove(websocket)
                if not self.active_connections[user_id]:
                    del self.active_connections[user_id]
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Error in WebSocket disconnect: {e}")

    async def broadcast(self, user_id: str, message: dict):
        if user_id in self.active_connections:
            connections_to_remove = []
            for connection in self.active_connections[user_id]:
                try:
                    await connection.send_json(message)
                except Exception as e:
                    connections_to_remove.append(connection)
            # Remove invalid connections
            for connection in connections_to_remove:
                self.disconnect(connection, user_id)

manager_account = ConnectionManagerAccount()

@router.websocket("/ws/account_updates/{user_id}")
async def websocket_updates(websocket: WebSocket, user_id: str):
    await manager_account.connect(websocket, user_id)
    try:
        while True:
            # Wait for messages to keep connection alive
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager_account.disconnect(websocket, user_id)
    except Exception as e:
        manager_account.disconnect(websocket, user_id)

class UsernameRequest(BaseModel):
    username: str

@router.post("/check-username")
async def check_username(data: UsernameRequest):
    username = data.username

    client.admin.command('ping')

    if not username:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Username is required"
        )

    user = users_collection.find_one({"Username": username})
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Username not found"
        )

    # Process avatar
    profile_image_id = user.get("ProfileImageId")
    avatar_base64 = ''
    if profile_image_id:
        file_avatar = users_fs.get(ObjectId(profile_image_id))
        avatar_base64 = base64.b64encode(file_avatar.read()).decode('utf-8')

    # Decrypt display
    encrypted_display = user.get("Display", "")
    decrypted_display = ""
    if encrypted_display:
        decrypted_display = decrypt_data(encrypted_data=encrypted_display, key=ENCRYPTION_KEY)

    return {
        "user_id": str(user["_id"]),
        "username": user.get("Username", ""),
        "display": decrypted_display,
        "avatar": avatar_base64
    }

@router.get("/get-user-by-username")
def get_user_by_username(username: str = Query(..., description="Username of the user")):
    user = users_collection.find_one({'Username': username})
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )
    return {"user_id": str(user['_id'])}

@router.get("/get-user-info/{user_id}")
def get_user_info(user_id: str):
    # Validate ObjectId
    if not ObjectId.is_valid(user_id):
        raise HTTPException(status_code=400, detail="Invalid user ID format")

    # Get user information
    user_info = users_collection.find_one({'_id': ObjectId(user_id)})
    if not user_info:
        raise HTTPException(status_code=404, detail="User not found")

    is_banned = user_info.get('Banned', False)

    if is_banned:
        return {
            "is_banned": is_banned
        }

    # Get avatar
    profile_image_id = user_info.get("ProfileImageId")
    avatar_base64 = ''
    if profile_image_id:
        try:
            file_avatar = users_fs.get(ObjectId(profile_image_id))
            avatar_base64 = base64.b64encode(file_avatar.read()).decode('utf-8')
        except Exception as e:
            avatar_base64 = ''

    # Decrypt display
    display = user_info.get('Display', '')
    decrypted_display = decrypt_data(display, ENCRYPTION_KEY) if display else ''

    return {
        "user_id": str(user_info['_id']),
        "username": user_info['Username'],
        "display": decrypted_display,
        "avatar": avatar_base64
    }

@router.get("/get-user-images")
def get_user_images(
    user_id: str = Query(..., description="ID of the user whose images are requested"),
    requester_id: str = Query(None, description="ID of the authenticated user making the request"),
    limit: int = Query(20, description="Number of images to return"),
    exclude_ids: List[str] = Query(default=[], description="List of image IDs to exclude")
):
    try:
        excluded_object_ids = [ObjectId(i) for i in exclude_ids if ObjectId.is_valid(i)]
    except Exception:
        excluded_object_ids = []

    if not ObjectId.is_valid(user_id):
        raise HTTPException(status_code=400, detail="Invalid user_id")

    if requester_id and not ObjectId.is_valid(requester_id):
        raise HTTPException(status_code=400, detail="Invalid requester_id")

    match_criteria = {
        "_id": {"$nin": excluded_object_ids},
        "$or": [
            {"UserId": ObjectId(user_id)},
            {"CollaborationAccounts": ObjectId(user_id)}
        ]
    }

    if requester_id and requester_id == user_id:
        pass
    elif requester_id:
        match_criteria["$or"].append({"Visibility": "public"})
        match_criteria["$or"].append({"Visibility": "private", "CollaborationAccounts": ObjectId(requester_id)})
    else:
        match_criteria["Visibility"] = "public"

    pipeline = [
        {"$match": match_criteria},
        {"$sort": {"UploadAt": DESCENDING}},
        {"$limit": limit}
    ]

    try:
        results = list(images_collection.aggregate(pipeline))
        return {
            "images": [
                {
                    "id": str(item["_id"]),
                    "user_id": str(item["UserId"]),
                    "upload_at": item["UploadAt"].isoformat(),
                    "collaboration_accounts": [str(acc) for acc in item.get("CollaborationAccounts", [])],
                    "visibility": item.get("Visibility", "public"),
                }
                for item in results
            ]
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching images: {str(e)}")

class CustomData(BaseModel):
    field: str
    value: str

@router.get("/get-account-info/{user_id}")
async def get_account_info(user_id: str, requester_id: str = Query(None, description="ID of the requesting user")):
    user = users_collection.find_one({"_id": ObjectId(user_id)})
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    decrypted_email = decrypt_data(user.get("Email", ""), ENCRYPTION_KEY) if user.get("Email") else ""
    decrypted_birth_date = decrypt_data(user.get("BirthDate", ""), ENCRYPTION_KEY) if user.get("BirthDate") else ""
    decrypted_city = decrypt_data(user.get("City", ""), ENCRYPTION_KEY) if user.get("City") else ""
    decrypted_country = decrypt_data(user.get("Country", ""), ENCRYPTION_KEY) if user.get("Country") else ""
    decrypted_public_ip = decrypt_data(user.get("PublicIp", ""), ENCRYPTION_KEY) if user.get("PublicIp") else ""
    decrypted_latitude = decrypt_data(user.get("Latitude", ""), ENCRYPTION_KEY) if user.get("Latitude") else ""
    decrypted_longitude = decrypt_data(user.get("Longitude", ""), ENCRYPTION_KEY) if user.get("Longitude") else ""
    decrypted_password = decrypt_data(user.get("Password", ""), ENCRYPTION_KEY) if user.get("Password") else ""

    # Number of followers
    count_followers = followers_collection.count_documents({"target_user_id": ObjectId(user_id)})

    # Number of following
    count_following = followers_collection.count_documents({"follower_id": ObjectId(user_id)})

    # Check follow status
    is_following = False
    if requester_id and ObjectId.is_valid(requester_id):
        is_following = followers_collection.find_one({
            "follower_id": ObjectId(requester_id),
            "target_user_id": ObjectId(user_id)
        }) is not None

    response = {
        "user_id": str(user["_id"]),
        "email": decrypted_email,
        "password": decrypted_password,
        "birth_date": decrypted_birth_date,
        "city": decrypted_city,
        "country": decrypted_country,
        "public_ip": decrypted_public_ip,
        "count_posts": user.get("CountPosts", 0),
        "count_videos": user.get("CountVideos", 0),
        "count_images": user.get("CountImages", 0),
        "count_articles": user.get("CountArticles", 0),
        "count_products": user.get("CountProducts", 0),
        "count_shopings": user.get("CountShopings", 0),
        "count_theories": user.get("CountTheories", 0),
        "count_followers": count_followers,
        "count_following": count_following,
        "balance": user.get("Balance", 0),
        "latitude": decrypted_latitude,
        "longitude": decrypted_longitude,
        "is_following": is_following
    }

    return response

@router.get("/get-user-videos")
def get_user_videos(
    user_id: str = Query(..., description="ID of the user whose videos are requested"),
    requester_id: str = Query(None, description="ID of the authenticated user making the request"),
    limit: int = Query(20, description="Number of videos to return"),
    exclude_ids: List[str] = Query(default=[], description="List of video IDs to exclude")
):
    try:
        excluded_object_ids = [ObjectId(i) for i in exclude_ids if ObjectId.is_valid(i)]
    except Exception:
        excluded_object_ids = []

    if not ObjectId.is_valid(user_id):
        raise HTTPException(status_code=400, detail="Invalid user_id")

    if requester_id and not ObjectId.is_valid(requester_id):
        raise HTTPException(status_code=400, detail="Invalid requester_id")

    match_criteria = {
        "_id": {"$nin": excluded_object_ids},
        "$or": [
            {"UserId": ObjectId(user_id)},
            {"CollaborationAccounts": ObjectId(user_id)}
        ]
    }

    if requester_id and requester_id == user_id:
        pass
    elif requester_id:
        match_criteria["$or"].append({"Visibility": "public"})
        match_criteria["$or"].append({"Visibility": "private", "CollaborationAccounts": ObjectId(requester_id)})
    else:
        match_criteria["Visibility"] = "public"

    pipeline = [
        {"$match": match_criteria},
        {"$sort": {"UploadAt": DESCENDING}},
        {"$limit": limit}
    ]

    try:
        results = list(videos_collection.aggregate(pipeline))
        return {
            "videos": [
                {
                    "id": str(item["_id"]),
                    "user_id": str(item["UserId"]),
                    "upload_at": item["UploadAt"].isoformat(),
                    "collaboration_accounts": [str(acc) for acc in item.get("CollaborationAccounts", [])],
                    "visibility": item.get("Visibility", "public"),
                }
                for item in results
            ]
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching videos: {str(e)}")

class FollowRequest(BaseModel):
    follower_id: str
    target_user_id: str

@router.post("/follow")
async def follow_user(follow_request: FollowRequest):
    follower_id = follow_request.follower_id
    target_user_id = follow_request.target_user_id

    if not ObjectId.is_valid(follower_id) or not ObjectId.is_valid(target_user_id):
        raise HTTPException(status_code=400, detail="Invalid follower_id or target_user_id")

    if follower_id == target_user_id:
        raise HTTPException(status_code=400, detail="Cannot follow yourself")

    target_user = users_collection.find_one({"_id": ObjectId(target_user_id)})
    if not target_user:
        raise HTTPException(status_code=404, detail="Target user not found")

    existing_follow = followers_collection.find_one({
        "follower_id": ObjectId(follower_id),
        "target_user_id": ObjectId(target_user_id)
    })
    if existing_follow:
        raise HTTPException(status_code=400, detail="Already following this user")

    # Add follow
    followed_at = datetime.now(timezone.utc)
    new_follow = {
        "follower_id": ObjectId(follower_id),
        "target_user_id": ObjectId(target_user_id),
        "followed_at": followed_at
    }
    followers_collection.insert_one(new_follow)

    # Update CountFollowers and CountFollowing
    count_followers = followers_collection.count_documents({"target_user_id": ObjectId(target_user_id)})
    count_following = followers_collection.count_documents({"follower_id": ObjectId(follower_id)})
    users_collection.update_one(
        {"_id": ObjectId(target_user_id)},
        {"$set": {"CountFollowers": count_followers}}
    )
    users_collection.update_one(
        {"_id": ObjectId(follower_id)},
        {"$set": {"CountFollowing": count_following}}
    )

    # Get follower information for WebSocket message
    follower_info = users_collection.find_one({"_id": ObjectId(follower_id)})
    if not follower_info:
        raise HTTPException(status_code=404, detail="Follower user not found")

    decrypted_display = decrypt_data(follower_info.get('Display', ''), ENCRYPTION_KEY) if follower_info.get('Display') else ''
    avatar_base64 = ''
    profile_image_id = follower_info.get("ProfileImageId")
    if profile_image_id:
        try:
            file_avatar = users_fs.get(ObjectId(profile_image_id))
            avatar_base64 = base64.b64encode(file_avatar.read()).decode('utf-8')
        except Exception:
            avatar_base64 = ''

    follower_data = {
        "user_id": str(follower_info["_id"]),
        "username": follower_info["Username"],
        "display": decrypted_display,
        "avatar": avatar_base64,
        "followed_at": followed_at.isoformat()
    }

    # Create notification for target user (who got a follower)
    notification_message = f"@{follower_info['Username']} followed you ✅"
    encrypted_message = encrypt_data(notification_message, ENCRYPTION_KEY)
    
    notification = {
        "NotificationFrom": ObjectId(follower_id),
        "NotificationTo": ObjectId(target_user_id),
        "Message": encrypted_message,
        "IsRead": False,
        "UploadAt": datetime.now(timezone.utc).isoformat().replace('Z', '+00:00'),
        "Type": encrypt_data("follow", ENCRYPTION_KEY),
        "status": "pending"
    }

    # Create notification in notifications collection
    result = notifications_collection.insert_one(notification)
    
    # Serialize and send WebSocket message for notification
    serialized_notification = serialize_notification(notification)
    await broadcast_notification(str(target_user_id), "add", serialized_notification)

    # Broadcast to follower_id
    await manager_account.broadcast(str(follower_id), {
        "type": "follow",
        "follower_id": str(follower_id),
        "target_user_id": str(target_user_id),
        "count_following": count_following,
        "target_user": {
            "user_id": str(target_user_id),
            "username": target_user["Username"],
            "display": decrypt_data(target_user.get('Display', ''), ENCRYPTION_KEY) if target_user.get('Display') else '',
            "avatar": ''  # You can add avatar here if needed
        }
    })

    # Broadcast to target_user_id with follower information
    await manager_account.broadcast(str(target_user_id), {
        "type": "follow",
        "follower_id": str(follower_id),
        "target_user_id": str(target_user_id),
        "count_followers": count_followers,
        "follower": follower_data,
        "notification": {
            "message": notification_message,
            "type": "follow"
        }
    })

    return {"status": "success", "message": "Followed successfully"}

@router.post("/unfollow")
async def unfollow_user(follow_request: FollowRequest):
    follower_id = follow_request.follower_id
    target_user_id = follow_request.target_user_id

    if not ObjectId.is_valid(follower_id) or not ObjectId.is_valid(target_user_id):
        raise HTTPException(status_code=400, detail="Invalid follower_id or target_user_id")

    if follower_id == target_user_id:
        raise HTTPException(status_code=400, detail="Cannot unfollow yourself")

    target_user = users_collection.find_one({"_id": ObjectId(target_user_id)})
    if not target_user:
        raise HTTPException(status_code=404, detail="Target user not found")

    existing_follow = followers_collection.find_one({
        "follower_id": ObjectId(follower_id),
        "target_user_id": ObjectId(target_user_id)
    })
    if not existing_follow:
        raise HTTPException(status_code=400, detail="Not following this user")

    # Remove follow
    followers_collection.delete_one({
        "follower_id": ObjectId(follower_id),
        "target_user_id": ObjectId(target_user_id)
    })

    # Update CountFollowers and CountFollowing
    count_followers = followers_collection.count_documents({"target_user_id": ObjectId(target_user_id)})
    count_following = followers_collection.count_documents({"follower_id": ObjectId(follower_id)})
    users_collection.update_one(
        {"_id": ObjectId(target_user_id)},
        {"$set": {"CountFollowers": count_followers}}
    )
    users_collection.update_one(
        {"_id": ObjectId(follower_id)},
        {"$set": {"CountFollowing": count_following}}
    )

    # Get follower information for WebSocket message
    follower_info = users_collection.find_one({"_id": ObjectId(follower_id)})
    if not follower_info:
        raise HTTPException(status_code=404, detail="Follower user not found")

    decrypted_display = decrypt_data(follower_info.get('Display', ''), ENCRYPTION_KEY) if follower_info.get('Display') else ''
    avatar_base64 = ''
    profile_image_id = follower_info.get("ProfileImageId")
    if profile_image_id:
        try:
            file_avatar = users_fs.get(ObjectId(profile_image_id))
            avatar_base64 = base64.b64encode(file_avatar.read()).decode('utf-8')
        except Exception:
            avatar_base64 = ''

    follower_data = {
        "user_id": str(follower_info["_id"]),
        "username": follower_info["Username"],
        "display": decrypted_display,
        "avatar": avatar_base64
    }

    # Broadcast to follower_id
    await manager_account.broadcast(str(follower_id), {
        "type": "unfollow",
        "follower_id": str(follower_id),
        "target_user_id": str(target_user_id),
        "count_following": count_following,
        "target_user": {
            "user_id": str(target_user_id),
            "username": target_user["Username"],
            "display": decrypt_data(target_user.get('Display', ''), ENCRYPTION_KEY) if target_user.get('Display') else '',
            "avatar": ''  # You can add avatar here if needed
        }
    })

    # Broadcast to target_user_id with follower information
    await manager_account.broadcast(str(target_user_id), {
        "type": "unfollow",
        "follower_id": str(follower_id),
        "target_user_id": str(target_user_id),
        "count_followers": count_followers,
        "follower": follower_data
    })

    return {"status": "success", "message": "Unfollowed successfully"}

@router.get("/get-followers/{user_id}")
async def get_followers(
    user_id: str,
    offset: int = Query(0, ge=0, description="Number of followers to skip"),
    limit: int = Query(20, ge=1, description="Number of followers per request"),
    requester_id: str = Query(None, description="ID of the requesting user")
):
    if not ObjectId.is_valid(user_id):
        raise HTTPException(status_code=400, detail="Invalid user ID format")

    user = users_collection.find_one({"_id": ObjectId(user_id)})
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    total_count = followers_collection.count_documents({
        "target_user_id": ObjectId(user_id)
    })

    followers = list(
        followers_collection.find({
            "target_user_id": ObjectId(user_id)
        })
        .sort("followed_at", -1)
        .skip(offset)
        .limit(limit)
    )

    followers_data = []

    requester_obj_id = (
        ObjectId(requester_id)
        if requester_id and ObjectId.is_valid(requester_id)
        else None
    )

    for follow in followers:
        follower_info = users_collection.find_one({
            "_id": follow["follower_id"]
        })

        if not follower_info:
            continue

        # АГАР АККАУНТ БАНШУДА БОШАД 👇
        is_banned = follower_info.get("Banned", False)

        if is_banned:
            followers_data.append({
                "user_id": str(follower_info["_id"]),
                "username": "Banned Account",
                "display": "",
                "avatar": "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Wn8K6sAAAAASUVORK5CYII=",
                "followed_at": follow["followed_at"].isoformat(),
                "is_following": False,
                "is_banned": True
            })
            continue

        # Аккаунти оддӣ
        decrypted_display = (
            decrypt_data(
                follower_info.get('Display', ''),
                ENCRYPTION_KEY
            )
            if follower_info.get('Display')
            else ''
        )

        avatar_base64 = ''
        profile_image_id = follower_info.get("ProfileImageId")

        if profile_image_id:
            try:
                file_avatar = users_fs.get(ObjectId(profile_image_id))
                avatar_base64 = base64.b64encode(
                    file_avatar.read()
                ).decode('utf-8')
            except Exception:
                avatar_base64 = ''

        # Check if requester follows this user
        is_following = False

        if requester_obj_id and str(requester_obj_id) != str(follower_info["_id"]):
            existing_follow = followers_collection.find_one({
                "follower_id": requester_obj_id,
                "target_user_id": follower_info["_id"]
            })
            is_following = existing_follow is not None

        elif requester_obj_id and str(requester_obj_id) == str(follower_info["_id"]):
            is_following = True

        followers_data.append({
            "user_id": str(follower_info["_id"]),
            "username": follower_info["Username"],
            "display": decrypted_display,
            "avatar": avatar_base64,
            "followed_at": follow["followed_at"].isoformat(),
            "is_following": is_following,
            "is_banned": False
        })

    has_more = offset + len(followers) < total_count
    next_offset = offset + len(followers) if has_more else None

    return {
        "followers": followers_data,
        "total_count": total_count,
        "has_more": has_more,
        "next_offset": next_offset,
        "offset": offset,
        "limit": limit
    }

@router.get("/get-following/{user_id}")
async def get_following(
    user_id: str,
    offset: int = Query(0, ge=0, description="Number of following to skip"),
    limit: int = Query(20, ge=1, description="Number of following per request"),
    requester_id: str = Query(None, description="ID of the requesting user")
):
    if not ObjectId.is_valid(user_id):
        raise HTTPException(status_code=400, detail="Invalid user ID format")

    user = users_collection.find_one({"_id": ObjectId(user_id)})
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    total_count = followers_collection.count_documents({
        "follower_id": ObjectId(user_id)
    })

    following = list(
        followers_collection.find({
            "follower_id": ObjectId(user_id)
        })
        .sort("followed_at", -1)
        .skip(offset)
        .limit(limit)
    )

    following_data = []

    requester_obj_id = (
        ObjectId(requester_id)
        if requester_id and ObjectId.is_valid(requester_id)
        else None
    )

    for follow in following:
        following_info = users_collection.find_one({
            "_id": follow["target_user_id"]
        })

        if not following_info:
            continue

        # Агар аккаунт banned бошад
        is_banned = following_info.get("Banned", False)

        if is_banned:
            following_data.append({
                "user_id": str(following_info["_id"]),
                "username": "Banned Account",
                "display": "",
                "avatar": "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Wn8K6sAAAAASUVORK5CYII=",
                "followed_at": follow["followed_at"].isoformat(),
                "is_following": False,
                "is_banned": True
            })
            continue

        # Аккаунти оддӣ
        decrypted_display = (
            decrypt_data(
                following_info.get("Display", ""),
                ENCRYPTION_KEY
            )
            if following_info.get("Display")
            else ""
        )

        avatar_base64 = ""
        profile_image_id = following_info.get("ProfileImageId")

        if profile_image_id:
            try:
                file_avatar = users_fs.get(ObjectId(profile_image_id))
                avatar_base64 = base64.b64encode(
                    file_avatar.read()
                ).decode("utf-8")
            except Exception:
                avatar_base64 = ""

        # Санҷиши follow status
        is_following = False

        if requester_obj_id and str(requester_obj_id) != str(following_info["_id"]):
            existing_follow = followers_collection.find_one({
                "follower_id": requester_obj_id,
                "target_user_id": following_info["_id"]
            })
            is_following = existing_follow is not None

        elif requester_obj_id and str(requester_obj_id) == str(following_info["_id"]):
            is_following = True

        following_data.append({
            "user_id": str(following_info["_id"]),
            "username": following_info["Username"],
            "display": decrypted_display,
            "avatar": avatar_base64,
            "followed_at": follow["followed_at"].isoformat(),
            "is_following": is_following,
            "is_banned": False
        })

    has_more = offset + len(following) < total_count
    next_offset = offset + len(following) if has_more else None

    return {
        "following": following_data,
        "total_count": total_count,
        "has_more": has_more,
        "next_offset": next_offset,
        "offset": offset,
        "limit": limit
    }

@router.get("/search-followers")
async def search_followers(
    user_id: str,
    search: str = "",
    skip: int = 0,
    limit: int = 20,
    requester_id: str = '',
):
    if not ObjectId.is_valid(user_id):
        raise HTTPException(status_code=400, detail="Invalid ID")

    current_user_id = ObjectId(user_id)

    requester_oid = (
        ObjectId(requester_id)
        if requester_id and ObjectId.is_valid(requester_id)
        else current_user_id
    )

    user_query = {
        "Username": {"$regex": search, "$options": "i"},
        "_id": {"$ne": current_user_id}
    }

    matched_users = list(users_collection.find(user_query, {
        "_id": 1,
        "Username": 1,
        "Display": 1,
        "ProfileImageId": 1,
        "Banned": 1
    }))

    if not matched_users:
        return []

    matched_user_ids = [u["_id"] for u in matched_users]

    follower_relations = followers_collection.find(
        {
            "target_user_id": current_user_id,
            "follower_id": {"$in": matched_user_ids}
        },
        {"follower_id": 1}
    )

    valid_ids = {fr["follower_id"] for fr in follower_relations}

    following_relations = followers_collection.find(
        {
            "follower_id": requester_oid,
            "target_user_id": {"$in": list(valid_ids)}
        },
        {"target_user_id": 1}
    )

    following_set = {fr["target_user_id"] for fr in following_relations}

    results = []

    for user in matched_users:
        if user["_id"] not in valid_ids:
            continue

        is_banned = user.get("Banned", False)

        if is_banned:
            results.append({
                "user_id": str(user["_id"]),
                "username": "Banned Account",
                "display_name": "",
                "avatar": "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Wn8K6sAAAAASUVORK5CYII=",
                "is_following": False,
                "is_banned": True
            })
            continue

        avatar_base64 = ""
        profile_image_id = user.get("ProfileImageId")

        if profile_image_id:
            try:
                file = users_fs.get(ObjectId(profile_image_id))
                image_bytes = file.read()
                avatar_base64 = (
                    f"data:image/jpeg;base64,"
                    f"{base64.b64encode(image_bytes).decode('utf-8')}"
                )
            except Exception:
                pass

        encrypted_display = user.get("Display", "")
        try:
            decrypted_display = fernet.decrypt(
                encrypted_display.encode()
            ).decode()
        except Exception:
            decrypted_display = encrypted_display

        results.append({
            "user_id": str(user["_id"]),
            "username": user.get("Username", ""),
            "display_name": decrypted_display,
            "avatar": avatar_base64,
            "is_following": user["_id"] in following_set,
            "is_banned": False
        })

    return results[skip: skip + limit]

@router.get("/search-following")
async def search_following(
    user_id: str,
    search: str = "",
    skip: int = 0,
    limit: int = 20,
    requester_id: str = '',
):
    if not ObjectId.is_valid(user_id):
        raise HTTPException(status_code=400, detail="Invalid ID")

    current_user_id = ObjectId(user_id)

    requester_oid = (
        ObjectId(requester_id)
        if requester_id and ObjectId.is_valid(requester_id)
        else current_user_id
    )

    user_query = {
        "Username": {"$regex": search, "$options": "i"},
        "_id": {"$ne": current_user_id}
    }

    matched_users = list(users_collection.find(user_query, {
        "_id": 1,
        "Username": 1,
        "Display": 1,
        "ProfileImageId": 1,
        "Banned": 1
    }))

    if not matched_users:
        return []

    matched_user_ids = [u["_id"] for u in matched_users]

    following_relations = followers_collection.find(
        {
            "follower_id": current_user_id,
            "target_user_id": {"$in": matched_user_ids}
        },
        {"target_user_id": 1}
    )

    valid_ids = {fr["target_user_id"] for fr in following_relations}

    requester_following_relations = followers_collection.find(
        {
            "follower_id": requester_oid,
            "target_user_id": {"$in": list(valid_ids)}
        },
        {"target_user_id": 1}
    )

    requester_following_set = {
        fr["target_user_id"]
        for fr in requester_following_relations
    }

    results = []

    for user in matched_users:
        if user["_id"] not in valid_ids:
            continue

        is_banned = user.get("Banned", False)

        if is_banned:
            results.append({
                "user_id": str(user["_id"]),
                "username": "Banned Account",
                "display_name": "",
                "avatar": "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Wn8K6sAAAAASUVORK5CYII=",
                "is_following": False,
                "is_banned": True
            })
            continue

        avatar_base64 = ""
        profile_image_id = user.get("ProfileImageId")

        if profile_image_id:
            try:
                file = users_fs.get(ObjectId(profile_image_id))
                image_bytes = file.read()
                avatar_base64 = (
                    f"data:image/jpeg;base64,"
                    f"{base64.b64encode(image_bytes).decode('utf-8')}"
                )
            except Exception:
                pass

        encrypted_display = user.get("Display", "")
        try:
            decrypted_display = fernet.decrypt(
                encrypted_display.encode()
            ).decode()
        except Exception:
            decrypted_display = encrypted_display

        results.append({
            "user_id": str(user["_id"]),
            "username": user.get("Username", ""),
            "display_name": decrypted_display,
            "avatar": avatar_base64,
            "is_following": user["_id"] in requester_following_set,
            "is_banned": False
        })

    return results[skip: skip + limit]

@router.get("/get-user-products")
def get_user_products(
    user_id: str = Query(..., description="ID of the user whose products are requested"),
    requester_id: str = Query(None, description="ID of the authenticated user making the request"),
    limit: int = Query(20, description="Number of products to return"),
    exclude_ids: List[str] = Query(default=[], description="List of product IDs to exclude")
):
    try:
        excluded_object_ids = [ObjectId(i) for i in exclude_ids if ObjectId.is_valid(i)]
    except Exception:
        excluded_object_ids = []

    if not ObjectId.is_valid(user_id):
        raise HTTPException(status_code=400, detail="Invalid user_id")

    if requester_id and not ObjectId.is_valid(requester_id):
        raise HTTPException(status_code=400, detail="Invalid requester_id")

    match_criteria = {
        "_id": {"$nin": excluded_object_ids},
        "$or": [
            {"UserId": ObjectId(user_id)},
        ]
    }

    if requester_id and requester_id == user_id:
        pass
    elif requester_id:
        match_criteria["$or"].append({"Visibility": "public"})
        match_criteria["$or"].append({"Visibility": "private"})
    else:
        match_criteria["Visibility"] = "public"

    pipeline = [
        {"$match": match_criteria},
        {"$sort": {"UploadAt": DESCENDING}},
        {"$limit": limit}
    ]

    try:
        results = list(products_collection.aggregate(pipeline))
        return {
            "products": [
                {
                    "id": str(item["_id"]),
                    "user_id": str(item["UserId"]),
                    "upload_at": item["UploadAt"].isoformat(),
                    "visibility": item.get("Visibility", "public"),
                }
                for item in results
            ]
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching products: {str(e)}")

class TransferRequest(BaseModel):
    from_user_id: str
    to_user_id: str
    amount: float

@router.post("/transfer-money")
async def transfer_money(transfer_request: TransferRequest):
    from_user_id = transfer_request.from_user_id
    to_user_id = transfer_request.to_user_id
    amount = transfer_request.amount

    if amount <= 0:
        raise HTTPException(status_code=400, detail="Amount must be greater than 0")

    if not ObjectId.is_valid(from_user_id) or not ObjectId.is_valid(to_user_id):
        raise HTTPException(status_code=400, detail="Invalid user IDs")

    from_user = users_collection.find_one({"_id": ObjectId(from_user_id)})
    to_user = users_collection.find_one({"_id": ObjectId(to_user_id)})
    sanjar_user = users_collection.find_one({"Username": "sanjar"})

    if not from_user or not to_user or not sanjar_user:
        raise HTTPException(status_code=404, detail="User not found")

    # 1% комиссия
    commission = round(amount * 0.01, 2)
    total_deduct = amount + commission

    if from_user.get("Balance", 0) < total_deduct:
        raise HTTPException(status_code=403, detail="Insufficient balance (including commission)")

    # Балансҳоро нав мекунем
    users_collection.update_one({"_id": ObjectId(from_user_id)}, {"$inc": {"Balance": -total_deduct}})
    users_collection.update_one({"_id": ObjectId(to_user_id)}, {"$inc": {"Balance": amount}})
    users_collection.update_one({"_id": sanjar_user["_id"]}, {"$inc": {"Balance": commission}})

    updated_from_user = users_collection.find_one({"_id": ObjectId(from_user_id)})
    updated_to_user = users_collection.find_one({"_id": ObjectId(to_user_id)})

    now_utc = datetime.now(timezone.utc)

    # Омодасозии матн барои фиристанда
    message_for_sender = (
        f"💸 You sent money\n"
        f"From: @{from_user['Username']}\n"
        f"To: @{to_user['Username']}\n"
        f"Amount: {amount} somoni\n"
        f"Commission: {commission} somoni (1%)\n"
        f"Time: {now_utc.isoformat().replace('Z', '+00:00')}\n"
        f"✅ Successfully sent"
    )

    # Омодасозии матн барои қабулкунанда
    message_for_receiver = (
        f"💸 You received money\n"
        f"From: @{from_user['Username']}\n"
        f"To: @{to_user['Username']}\n"
        f"Amount: {amount} somoni\n"
        f"Commission: {commission} somoni (1%)\n"
        f"Time: {now_utc.isoformat().replace('Z', '+00:00')}\n"
        f"✅ Successfully received"
    )

    # Функсияи ёрдамчӣ барои сабт ва фиристодани огоҳинома
    async def send_notification(to_id, message):
        notification = {
            "NotificationFrom": ObjectId(from_user_id),
            "NotificationTo": ObjectId(to_id),
            "Message": encrypt_data(message, ENCRYPTION_KEY),
            "PostId": ObjectId(from_user_id),
            "IsRead": False,
            "UploadAt": now_utc.isoformat().replace('Z', '+00:00'),
            "Type": "system",
            "status": "completed"
        }
        notifications_collection.insert_one(notification)
        serialized = serialize_notification(notification)
        await broadcast_notification(str(to_id), "add", serialized)

    # Ба ҳарду огоҳинома мефиристем
    await send_notification(from_user_id, message_for_sender)
    await send_notification(to_user_id, message_for_receiver)

    return {
        "status": "success",
        "message": f"{amount} somoni transferred with {commission} commission",
        "from_user_new_balance": updated_from_user.get("Balance", 0),
        "to_user_new_balance": updated_to_user.get("Balance", 0),
        "commission": commission,
        "from_username": from_user["Username"],
        "to_username": to_user["Username"]
    }

class WithdrawalRequest(BaseModel):
    user_id: str
    phone_or_card: str
    amount: float

@router.post("/create-withdrawal-request")
async def create_withdrawal_request(withdrawal_request: WithdrawalRequest):
    user_id = withdrawal_request.user_id
    phone_or_card = withdrawal_request.phone_or_card
    amount = withdrawal_request.amount

    if not ObjectId.is_valid(user_id):
        raise HTTPException(status_code=400, detail="Invalid user ID")

    # Check if user already has an active request
    existing_request = withdrawal_requests_collection.find_one({
        "user_id": ObjectId(user_id),
        "status": {"$in": ["pending", "processing"]}
    })

    if existing_request:
        raise HTTPException(
            status_code=400, 
            detail="You cannot make two withdrawal requests at the same time"
        )

    # Check user balance
    user = users_collection.find_one({"_id": ObjectId(user_id)})
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    user_balance = user.get("Balance", 0)
    if user_balance < amount:
        raise HTTPException(status_code=403, detail="Your balance is insufficient")

    # Create new request
    new_request = {
        "user_id": ObjectId(user_id),
        "phone_or_card": phone_or_card,
        "amount": amount,
        "status": "pending",  # pending, processing, completed, rejected
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc)
    }

    result = withdrawal_requests_collection.insert_one(new_request)

    # Temporarily deduct amount from user balance (until admin approval)
    users_collection.update_one(
        {"_id": ObjectId(user_id)},
        {"$inc": {"Balance": -amount}}
    )

    # Load updated data
    updated_user = users_collection.find_one({"_id": ObjectId(user_id)})

    return {
        "status": "success",
        "message": "Withdrawal request created successfully",
        "request_id": str(result.inserted_id),
        "new_balance": updated_user.get("Balance", 0)
    }

@router.get("/get-withdrawal-requests/{user_id}")
async def get_withdrawal_requests(user_id: str):
    if not ObjectId.is_valid(user_id):
        raise HTTPException(status_code=400, detail="Invalid user ID")

    requests = list(withdrawal_requests_collection.find(
        {"user_id": ObjectId(user_id)}
    ).sort("created_at", -1))

    return {
        "requests": [
            {
                "id": str(req["_id"]),
                "phone_or_card": req["phone_or_card"],
                "amount": req["amount"],
                "status": req["status"],
                "created_at": req["created_at"].isoformat(),
                "updated_at": req["updated_at"].isoformat()
            }
            for req in requests
        ]
    }

@router.post("/account/by_ids")
async def get_accounts_by_ids(payload: dict):
    try:
        ids = payload.get("ids", [])
        object_ids = [ObjectId(i) for i in ids if ObjectId.is_valid(i)]
        
        users = users_collection.find({"_id": {"$in": object_ids}}, {
            "Username": 1,
            "Display": 1,
            "ProfileImageId": 1
        })

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
            except Exception:
                decrypted_display = encrypted_display

            accounts.append({
                "id": str(user["_id"]),
                "username": user.get("Username", ""),
                "display_name": decrypted_display,
                "avatar": avatar_base64
            })

        return accounts

    except Exception as e:
        return {"message": f"Error while fetching accounts: {str(e)}"}

@router.get("/accounts-block")
async def get_accounts(user_id: str, search: str = "", exclude_ids: str = ""):
    client.admin.command('ping')

    # Parse exclude_ids (24-character ObjectIds separated by ",")
    exclude_list = []
    if exclude_ids:
        exclude_list = [ObjectId(i) for i in exclude_ids.split(",") if ObjectId.is_valid(i)]

    query = {
        "_id": {
            "$ne": ObjectId(user_id),
            "$nin": exclude_list  # ❗️IDs that should be excluded
        },
        "Banned": {"$ne": True}
    }

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
        except Exception:
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

@router.get("/get-user-avatar/{user_id}")
def get_user_avatar(user_id: str):
    try:
        user_info = users_collection.find_one({'_id': ObjectId(user_id)})
        if not user_info:
            raise HTTPException(status_code=404, detail="User not found")

        profile_image_id = user_info.get("ProfileImageId")
        if profile_image_id:
            file_avatar = users_fs.get(ObjectId(profile_image_id))
            avatar_base64 = base64.b64encode(file_avatar.read()).decode('utf-8')
        else:
            avatar_base64 = ''

        return {"avatar": avatar_base64}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.get("/get-user-articles")
async def get_user_articles(
    user_id: str = Query(..., description="ID of the user whose articles are requested"),
    requester_id: str = Query(None, description="ID of the authenticated user making the request"),
    limit: int = Query(20, description="Number of articles to return"),
    exclude_ids: List[str] = Query(default=[], description="List of articles IDs to exclude")
):
    try:
        excluded_object_ids = [ObjectId(i) for i in exclude_ids if ObjectId.is_valid(i)]
    except Exception:
        excluded_object_ids = []

    if not ObjectId.is_valid(user_id):
        raise HTTPException(status_code=400, detail="Invalid user_id")

    if requester_id and not ObjectId.is_valid(requester_id):
        raise HTTPException(status_code=400, detail="Invalid requester_id")

    match_criteria = {
        "_id": {"$nin": excluded_object_ids},
        "$or": [
            {"user_id": ObjectId(user_id)},
        ]
    }

    pipeline = [
        {"$match": match_criteria},
        {"$sort": {"created_at": DESCENDING}},
        {"$limit": limit}
    ]

    results = list(articles_collection.aggregate(pipeline))

    articles_list = []

    for artl in results:
        user_info = users_collection.find_one({'_id': ObjectId(artl["user_id"])})
        if not user_info:
            continue

        # Normalize created_at
        created_at = artl.get("created_at")

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

        # EXACT FORMAT FOR FRONTEND
        articles_list.append({
            "id": str(artl["_id"]),
            "user_id": str(artl["user_id"]),
        })

    return {
        "articles": articles_list
    }

@router.get("/get-user-theories")
def get_user_theories(
    user_id: str = Query(..., description="ID of the user whose theories are requested"),
    requester_id: str = Query(None, description="ID of the authenticated user making the request"),
    limit: int = Query(20, description="Number of theories to return"),
    exclude_ids: List[str] = Query(default=[], description="List of theory IDs to exclude")
):
    try:
        excluded_object_ids = [ObjectId(i) for i in exclude_ids if ObjectId.is_valid(i)]
    except Exception:
        excluded_object_ids = []

    if not ObjectId.is_valid(user_id):
        raise HTTPException(status_code=400, detail="Invalid user_id")

    if requester_id and not ObjectId.is_valid(requester_id):
        raise HTTPException(status_code=400, detail="Invalid requester_id")

    match_criteria = {
        "_id": {"$nin": excluded_object_ids},
        "$or": [
            {"user_id": ObjectId(user_id)},
        ]
    }

    pipeline = [
        {"$match": match_criteria},
        {"$sort": {"created_at": DESCENDING}},
        {"$limit": limit}
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

@router.get("/get-user-shopings")
def get_user_shopings(
    user_id: str = Query(..., description="ID of the user whose shopings are requested"),
    requester_id: str = Query(None, description="ID of the authenticated user making the request"),
    limit: int = Query(20, description="Number of shopings to return"),
    exclude_ids: List[str] = Query(default=[], description="List of shoping IDs to exclude")
):
    try:
        excluded_object_ids = [ObjectId(i) for i in exclude_ids if ObjectId.is_valid(i)]
    except Exception:
        excluded_object_ids = []

    if not ObjectId.is_valid(user_id):
        raise HTTPException(status_code=400, detail="Invalid user_id")

    if requester_id and not ObjectId.is_valid(requester_id):
        raise HTTPException(status_code=400, detail="Invalid requester_id")

    match_criteria = {
        "_id": {"$nin": excluded_object_ids},
        "$or": [
            {"UserId": ObjectId(user_id)},
        ]
    }

    pipeline = [
        {"$match": match_criteria},
        {"$sort": {"UploadAt": DESCENDING}},
        {"$limit": limit}
    ]

    try:
        results = list(shopings_collection.aggregate(pipeline))
        return {
            "shopings": [
                {
                    "id": str(item["_id"]),
                    "user_id": str(item["UserId"]),
                    "upload_at": item["UploadAt"],
                }
                for item in results
            ]
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching shopings: {str(e)}")

class AccountReportRequest(BaseModel):
    user_id: str
    account_id: str
    reason: str

@router.post("/report-account")
async def report_account(request: AccountReportRequest):
    # Validate ObjectId
    if not ObjectId.is_valid(request.user_id) or not ObjectId.is_valid(request.account_id):
        raise HTTPException(status_code=400, detail="Invalid user_id or account_id format")

    # Check if comment exists
    account = users_collection.find_one({"_id": ObjectId(request.account_id)})
    if not account:
        raise HTTPException(status_code=404, detail="account not found")

    # Check if user exists
    user = users_collection.find_one({"_id": ObjectId(request.user_id)})
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # Check for duplicate report
    existing_report = reports_of_account.find_one({
        "user_id": ObjectId(request.user_id),
        "account_id": ObjectId(request.account_id)
    })
    if existing_report:
        raise HTTPException(status_code=401, detail="You have already reported this account")

    # Encrypt reason
    encrypted_reason = encrypt_data(request.reason, ENCRYPTION_KEY)

    # Save report in AccountReports table
    report_data = {
        "user_id": ObjectId(request.user_id),
        "account_id": ObjectId(request.account_id),
        "reason": encrypted_reason,
        "created_at": datetime.now(timezone.utc)
    }
    reports_of_account.insert_one(report_data)

    send_email(
        recipient=my_email,
        message=f"""Шикоят аз аккаунти https://www.anyvoice.world/@{account["Username"]}.\n
        Шикоят кунанда: @{user['Username']}\n
        Сабаб: {request.reason}\n""",
        subject='Шикоят⚠️'
    )

    return {"success": True}
