# backend/explore/video_loader.py

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect, Query, Request
from fastapi.responses import StreamingResponse, FileResponse
import os
from cryptography.fernet import Fernet
import base64
from bson import ObjectId
import datetime
from pydantic import BaseModel
import json
import re
from account.account import manager_account
from menu.menu import videos_collection, videos_fs, users_collection, users_fs, videos_views_collection,\
videos_support_collection, videos_comment_collection, messages_db, reports_of_video, \
notifications_collection, videos_save_collection, videos_comment_collection, videos_comment_likes, messages_collection
from home.chat import manager_chat
from dotenv import load_dotenv
from menu.menu import encrypt_data, decrypt_data
from home.home import send_email

load_dotenv()

ENCRYPTION_KEY = os.getenv("ENCRYPTION_KEY")
my_email = os.getenv("MY_EMAIL")

fernet = Fernet(ENCRYPTION_KEY)

# Конфигуратсия барои HLS
HLS_STORAGE_PATH = os.getenv("HLS_STORAGE_PATH", "hls_videos")

router = APIRouter()

CHUNK_SIZE = 256 * 1024

class ConnectionManager:
    def __init__(self):
        self.active_connections: dict[str, list[WebSocket]] = {}

    async def connect(self, websocket: WebSocket, video_id: str):
        try:
            await websocket.accept()
            if video_id not in self.active_connections:
                self.active_connections[video_id] = []
            self.active_connections[video_id].append(websocket)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Error in WebSocket connect: {e}")

    def disconnect(self, websocket: WebSocket, video_id: str):
        try:
            if video_id in self.active_connections:
                if websocket in self.active_connections[video_id]:
                    self.active_connections[video_id].remove(websocket)
                if not self.active_connections[video_id]:
                    del self.active_connections[video_id]
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Error in WebSocket disconnect: {e}")

    async def broadcast(self, video_id: str, message: dict):
        if video_id in self.active_connections:
            connections_to_remove = []
            for connection in self.active_connections[video_id]:
                try:
                    await connection.send_json(message)
                except Exception as e:
                    connections_to_remove.append(connection)
            # Remove invalid connections
            for connection in connections_to_remove:
                self.disconnect(connection, video_id)

manager_video = ConnectionManager()

@router.websocket("/ws/updates-video/{video_id}")
async def websocket_updates(websocket: WebSocket, video_id: str):
    await manager_video.connect(websocket, video_id)
    try:
        while True:
            # Wait for messages to keep connection alive
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager_video.disconnect(websocket, video_id)
    except Exception as e:
        manager_video.disconnect(websocket, video_id)

@router.get("/get-video-preview/{video_id}")
async def get_video_preview(
    video_id: str,
    user_id: str = Query(None, description="ID of the requesting user")
):
    if not ObjectId.is_valid(video_id):
        raise HTTPException(status_code=400, detail="Invalid video ID format")

    post_info = videos_collection.find_one({"_id": ObjectId(video_id)})
    if not post_info:
        raise HTTPException(status_code=404, detail="Post not found")

    # 🚫 Check if video post is banned
    if post_info.get("Banned", False):
        return {
            "is_banned": True
        }

    # 🚫 Check if owner account is banned
    user_info = users_collection.find_one({"_id": post_info["UserId"]})
    if not user_info:
        raise HTTPException(status_code=404, detail="User not found")

    if user_info.get("Banned", False):
        return {
            "is_banned": True
        }

    user_is_blocked = False

    if user_id and ObjectId.is_valid(user_id):
        block_list = post_info.get("BlockUsersList", [])
        block_object_ids = [
            ObjectId(uid)
            for uid in block_list
            if ObjectId.is_valid(str(uid))
        ]

        if ObjectId(user_id) in block_object_ids:
            user_is_blocked = True

    if user_is_blocked:
        return {
            "visibility": post_info.get("Visibility", "public"),
            "user_is_blocked": True,
        }

    video_ids = post_info.get("VideoIds", [])
    if not video_ids:
        raise HTTPException(status_code=404, detail="No videos found for this post")

    first_video_duration = post_info.get("VideoDuration", "")

    # Thumbnail
    first_video_base64 = ""
    thumbnail_id = post_info.get("ThumbnailId")

    if thumbnail_id:
        try:
            first_video_data = videos_fs.get(thumbnail_id).read()
            first_video_base64 = base64.b64encode(
                first_video_data
            ).decode()
        except Exception:
            first_video_base64 = ""

    username = user_info["Username"]

    display = user_info.get("Display", "")
    decrypted_display = (
        decrypt_data(display, ENCRYPTION_KEY)
        if display else ""
    )

    title = post_info.get("Title", "")
    description = post_info.get("Description", "")
    decrypted_link = post_info["Link"]

    upload_at = post_info.get("UploadAt").isoformat() + "Z"
    update_at = post_info.get("UpdateAt")

    profile_image_id = user_info.get("ProfileImageId")

    if profile_image_id:
        try:
            file_avatar = users_fs.get(ObjectId(profile_image_id))
            avatar_base64 = base64.b64encode(
                file_avatar.read()
            ).decode("utf-8")
        except Exception:
            avatar_base64 = ""
    else:
        avatar_base64 = ""

    # HLS metadata
    hls_videos = post_info.get("HLSVideos", [])

    video_qualities = []
    if hls_videos:
        first_hls = hls_videos[0]
        video_qualities = first_hls.get(
            "qualities",
            ["360p", "480p", "720p"]
        )

    return {
        "id": str(post_info["_id"]),
        "first_video_base64": first_video_base64,
        "video_count": len(video_ids),
        "duration": first_video_duration,
        "title": title,
        "description": description,
        "username": str(username),
        "display": str(decrypted_display),
        "avatar": avatar_base64,
        "support_count": post_info.get("CountSupport", 0),
        "comment_count": post_info.get("CountComment", 0),
        "collaborator_ids": str(post_info["CollaborationAccounts"]),
        "share_count": post_info["CountShare"],
        "save_count": post_info["CountSave"],
        "count_view": post_info.get("CountView", 0),
        "Link": decrypted_link,
        "BlockUsersList": [
            str(uid)
            for uid in post_info.get("BlockUsersList", [])
        ],
        "UploadAt": upload_at,
        "UpdateAt": update_at,
        "allow_comments": post_info["AllowComments"],
        "visibility": post_info.get("Visibility", "public"),
        "hls_videos": hls_videos,
        "qualities": video_qualities,
        "is_banned": False,
    }

class BlockMessage(BaseModel):
    user_id: str
    block_user: str
    video_id: str

@router.post("/block-video")
async def block_video(block: BlockMessage):
    try:
        # Validate ObjectId
        if not ObjectId.is_valid(block.user_id) or not ObjectId.is_valid(block.block_user) or not ObjectId.is_valid(block.video_id):
            raise HTTPException(status_code=400, detail="Invalid user_id, block_user, or video_id format")

        # Get image information
        video = videos_collection.find_one({"_id": ObjectId(block.video_id)})
        if not video:
            raise HTTPException(status_code=404, detail="video not found")

        # Check permission: user_id must be owner or collaborator
        is_owner = str(video.get("UserId")) == block.user_id
        collaborator_ids = []
        collaboration_accounts = video.get("CollaborationAccounts", "")
        if collaboration_accounts:
            try:
                if isinstance(collaboration_accounts, str):
                    if collaboration_accounts.startswith("[") and collaboration_accounts.endswith("]"):
                        collaborator_ids = json.loads(collaboration_accounts)
                        collaborator_ids = [str(cid) for cid in collaborator_ids if ObjectId.is_valid(str(cid))]
                    else:
                        collaborator_ids = re.findall(r"[0-9a-fA-F]{24}", collaboration_accounts)
                elif isinstance(collaboration_accounts, list):
                    collaborator_ids = [str(cid) for cid in collaboration_accounts if ObjectId.is_valid(str(cid))]
            except Exception as e:
                collaborator_ids = []

        is_collaborator = block.user_id in collaborator_ids
        if not (is_owner or is_collaborator):
            raise HTTPException(status_code=403, detail="Not authorized to block users for this video")

        # Check if user to block exists
        block_user_info = users_collection.find_one({"_id": ObjectId(block.block_user)})
        if not block_user_info:
            raise HTTPException(status_code=404, detail="User to block not found")

        # Add block_user as ObjectId to BlockUsersList
        block_users_list = video.get("BlockUsersList", [])
        block_user_object_id = ObjectId(block.block_user)
        if block_user_object_id not in block_users_list:
            block_users_list.append(block_user_object_id)
            videos_collection.update_one(
                {"_id": ObjectId(block.video_id)},
                {"$set": {"BlockUsersList": block_users_list}}
            )

        # Broadcast update (with string ID for frontend)
        await manager_video.broadcast(block.video_id, {
            "type": "block_user",
            "block_user_id": block.block_user,  # string for frontend
            "video_id": block.video_id
        })

        return {"success": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/cancel-block-video")
async def cancel_block(block: BlockMessage):
    try:
        # Validate ObjectId
        if not ObjectId.is_valid(block.user_id) or not ObjectId.is_valid(block.block_user) or not ObjectId.is_valid(block.video_id):
            raise HTTPException(status_code=400, detail="Invalid user_id, block_user, or video_id format")

        # Get image information
        video = videos_collection.find_one({"_id": ObjectId(block.video_id)})
        if not video:
            raise HTTPException(status_code=404, detail="video not found")

        # Check permission: user_id must be owner or collaborator
        is_owner = str(video.get("UserId")) == block.user_id
        collaborator_ids = []
        collaboration_accounts = video.get("CollaborationAccounts", "")
        if collaboration_accounts:
            try:
                if isinstance(collaboration_accounts, str):
                    if collaboration_accounts.startswith("[") and collaboration_accounts.endswith("]"):
                        collaborator_ids = json.loads(collaboration_accounts)
                        collaborator_ids = [str(cid) for cid in collaborator_ids if ObjectId.is_valid(str(cid))]
                    else:
                        collaborator_ids = re.findall(r"[0-9a-fA-F]{24}", collaboration_accounts)
                elif isinstance(collaboration_accounts, list):
                    collaborator_ids = [str(cid) for cid in collaboration_accounts if ObjectId.is_valid(str(cid))]
            except Exception as e:
                collaborator_ids = []

        is_collaborator = block.user_id in collaborator_ids
        if not (is_owner or is_collaborator):
            raise HTTPException(status_code=403, detail="Not authorized to cancel block for this video")

        # Check if user to unblock exists
        block_user_info = users_collection.find_one({"_id": ObjectId(block.block_user)})
        if not block_user_info:
            raise HTTPException(status_code=404, detail="User to unblock not found")

        # Remove block_user as ObjectId from BlockUsersList
        block_users_list = video.get("BlockUsersList", [])
        block_user_object_id = ObjectId(block.block_user)
        if block_user_object_id in block_users_list:
            block_users_list.remove(block_user_object_id)
            videos_collection.update_one(
                {"_id": ObjectId(block.video_id)},
                {"$set": {"BlockUsersList": block_users_list}}
            )

        # Broadcast update (with string ID for frontend)
        await manager_video.broadcast(block.video_id, {
            "type": "cancel_block_user",
            "block_user_id": block.block_user,  # string for frontend
            "video_id": block.video_id
        })

        return {"success": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/get-video-by-id/{video_id}")
def get_video_by_id(video_id: str, user_id: str = Query(None, description="ID of the requesting user")):
    if not ObjectId.is_valid(video_id):
        raise HTTPException(status_code=400, detail="Invalid video ID format")

    post_info = videos_collection.find_one({"_id": ObjectId(video_id)})
    if not post_info:
        raise HTTPException(status_code=404, detail="Post not found")

    if user_id and ObjectId.is_valid(user_id):
        block_list = post_info.get("BlockUsersList", [])
        block_object_ids = [ObjectId(uid) for uid in block_list if ObjectId.is_valid(str(uid))]
        if ObjectId(user_id) in block_object_ids:
            raise HTTPException(status_code=403, detail="Access denied: You are blocked from viewing this post")

    # Get HLS videos data
    hls_videos = post_info.get("HLSVideos", [])
    videos_data = []
    for hls_video in hls_videos:
        videos_data.append({
            'video_id': hls_video.get('video_id'),
            'master_url': hls_video.get('master_url'),
            'duration': hls_video.get('duration'),
            'orientation': hls_video.get('orientation'),
            'qualities': hls_video.get('qualities', ['360p', '480p', '720p'])
        })

    user_info = users_collection.find_one({'_id': post_info['UserId']})
    if not user_info:
        raise HTTPException(status_code=404, detail="User not found")

    username = user_info['Username']
    display = user_info.get('Display', '')
    decrypted_display = decrypt_data(display, ENCRYPTION_KEY) if display else ''
    title = post_info.get('Title', '')
    description = post_info.get('Description', '')
    decrypted_link = post_info['Link']
    upload_at = post_info.get('UploadAt').isoformat() + "Z"
    update_at = post_info.get('UpdateAt')

    profile_video_id = user_info.get("ProfileImageId")
    avatar_base64 = ''
    if profile_video_id:
        try:
            file_avatar = users_fs.get(ObjectId(profile_video_id))
            avatar_base64 = base64.b64encode(file_avatar.read()).decode('utf-8')
        except Exception as e:
            pass

    video_names = post_info.get("VideoNames", [])  # <-- get names

    return {
        "id": str(post_info['_id']),
        "videos_data": videos_data,  # Now contains full HLS metadata
        "video_count": len(videos_data),
        "title": title,
        "description": description,
        "username": str(username),
        "display": str(decrypted_display),
        "avatar": avatar_base64,
        "support_count": post_info.get('CountSupport', 0),
        "comment_count": post_info.get('CountComment', 0),
        'collaborator_ids': str(post_info.get('CollaborationAccounts', '')),
        'share_count': post_info.get('CountShare', 0),
        'save_count': post_info.get('CountSave', 0),
        'count_view': post_info.get('CountView', 0),
        'Link': decrypted_link,
        'BlockUsersList': [str(uid) for uid in post_info.get('BlockUsersList', [])],
        'UploadAt': upload_at,
        'UpdateAt': update_at,
        'allow_comments': post_info.get('AllowComments', True),
        "videos_name": video_names,
    }

@router.get("/check-support-video")
def get_support_info(
    user_id: str = Query(..., description="User ID"),
    video_id: str = Query(..., description="Image ID")
):
    try:
        # Validate ObjectId for user_id and video_id
        if not ObjectId.is_valid(user_id) or not ObjectId.is_valid(video_id):
            return False  # Return False instead of error

        # Check if image exists in VideosData
        video_exists = videos_collection.find_one({'_id': ObjectId(video_id)})
        if not video_exists:
            return False  # Return False instead of error

        # Check support
        support = videos_support_collection.find_one({
            'UserId': ObjectId(user_id),
            'PostVideoId': ObjectId(video_id),
        })

        return bool(support)  # Return True if support exists, False otherwise
    except Exception as e:
        return False  # Return False instead of error

@router.get("/check-save-video-status")
def check_save_video_status(video_id: str, user_id: str):
    try:
        if not ObjectId.is_valid(video_id) or not ObjectId.is_valid(user_id):
            raise HTTPException(status_code=400, detail="Invalid ID format")

        saved = videos_save_collection.find_one({
            "PostVideoId": ObjectId(video_id),
            "UserId": ObjectId(user_id)
        })

        return {"saved": bool(saved)}  # True or False

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

class ViewEndRequest(BaseModel):
    user_id: str
    video_id: str

@router.post("/track-view-video")
async def track_view_end(request: ViewEndRequest):
    try:
        if not ObjectId.is_valid(request.user_id) or not ObjectId.is_valid(request.video_id):
            raise HTTPException(status_code=400, detail="Invalid user_id or video_id format")

        user_id = ObjectId(request.user_id)
        video_id = ObjectId(request.video_id)

        video = videos_collection.find_one({"_id": video_id})
        if not video:
            raise HTTPException(status_code=404, detail="video not found")

        # Check: does view record already exist
        existing_view = videos_views_collection.find_one({
            "user_id": user_id,
            "video_id": video_id
        })

        # ✅ If record does not exist, create it and increment CountView once
        if not existing_view:
            videos_views_collection.insert_one({
                "user_id": user_id,
                "video_id": video_id,
                "viewed_at": datetime.datetime.now(datetime.timezone.utc)
            })

            videos_collection.update_one(
                {"_id": video_id},
                {"$inc": {"CountView": 1}}
            )

            video_data = videos_collection.find_one({"_id": video_id})
            await manager_video.broadcast(str(video_id), {
                "type": "view_count",
                "value": video_data.get("CountView", 0)
            })

        # If record already exists, do nothing
        return {"success": True}
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/get-video-by-index/{video_id}/{index}")
async def get_video_by_index(video_id: str, index: int, user_id: str = Query(None, description="ID of the requesting user")):
    if not ObjectId.is_valid(video_id):
        raise HTTPException(status_code=400, detail="Invalid video ID format")

    post_info = videos_collection.find_one({"_id": ObjectId(video_id)})
    if not post_info:
        raise HTTPException(status_code=404, detail="Post not found")

    if user_id and ObjectId.is_valid(user_id):
        block_list = post_info.get("BlockUsersList", [])
        block_object_ids = [ObjectId(uid) for uid in block_list if ObjectId.is_valid(str(uid))]
        if ObjectId(user_id) in block_object_ids:
            raise HTTPException(status_code=403, detail="Access denied: You are blocked from viewing this post")

    hls_videos = post_info.get("HLSVideos", [])
    if not hls_videos:
        raise HTTPException(status_code=404, detail="No videos found for this post")

    if index < 0 or index >= len(hls_videos):
        raise HTTPException(status_code=400, detail="Invalid video index")

    selected_video = hls_videos[index]
    return {
        "video_id": selected_video.get('video_id'),
        "master_url": selected_video.get('master_url'),
        "duration": selected_video.get('duration'),
        "orientation": selected_video.get('orientation'),
        "qualities": selected_video.get('qualities', ['360p', '480p', '720p'])
    }

@router.get("/support-video-delete")
async def support_video_delete(
    user_id: str = Query(..., description="User ID"),
    video_id: str = Query(..., description="Image ID")
):
    # Check if the user has already supported this image
    existing_support = videos_support_collection.find_one({
        'UserId': ObjectId(user_id),
        'PostVideoId': ObjectId(video_id)
    })

    if not existing_support:
        raise HTTPException(
            status_code=400,
            detail="This user has not supported this image or has already removed support"
        )

    videos_support_collection.delete_one({
        'UserId': ObjectId(user_id),
        'PostVideoId': ObjectId(video_id),
    })

    videos_collection.update_one(
        {'_id': ObjectId(video_id)},
        {'$inc': {'CountSupport': -1}},
    )

    # Broadcast updated support count
    video_data = videos_collection.find_one({'_id': ObjectId(video_id)})
    await manager_video.broadcast(video_id, {
        "type": "support_count",
        "value": video_data.get('CountSupport', 0),
        "user_id": user_id,
        "support": False,
    })

    return {"success": True}

@router.get("/support-video-save")
async def support_video_save(
    user_id: str = Query(..., description="User ID"),
    video_id: str = Query(..., description="Image ID")
):
    # Check if the user has already supported this image
    existing_support = videos_support_collection.find_one({
        'UserId': ObjectId(user_id),
        'PostVideoId': ObjectId(video_id)
    })

    if existing_support:
        raise HTTPException(
            status_code=400,
            detail="This user has already supported this image"
        )

    videos_support_collection.insert_one({
        'UserId': ObjectId(user_id),
        'PostVideoId': ObjectId(video_id),
        "UploadAt": datetime.datetime.now(datetime.timezone.utc),
    })

    videos_collection.update_one(
        {'_id': ObjectId(video_id)},
        {'$inc': {'CountSupport': 1}},
    )

    # Broadcast updated support count
    video_data = videos_collection.find_one({'_id': ObjectId(video_id)})
    await manager_video.broadcast(video_id, {
        "type": "support_count",
        "value": video_data.get('CountSupport', 0),
        "user_id": user_id,
        "support": True,
    })

    return {"success": True}

@router.get("/save-video")
async def save_video(user_id: str, video_id: str):
    saved = videos_save_collection.find_one({
        "UserId": ObjectId(user_id),
        "PostVideoId": ObjectId(video_id)
    })
    if saved:
        videos_save_collection.delete_one({
            "UserId": ObjectId(user_id),
            "PostVideoId": ObjectId(video_id)
        })
        videos_collection.update_one(
            {"_id": ObjectId(video_id)},
            {"$inc": {"CountSave": -1}}
        )
        await manager_video.broadcast(video_id, {
            "type": "save_count",
            "value": videos_collection.find_one({"_id": ObjectId(video_id)}).get("CountSave", 0),
            "user_id": user_id,
            "saved": not bool(saved)
        })
        return {"saved": False}
    else:
        videos_save_collection.insert_one({
            "UserId": ObjectId(user_id),
            "PostVideoId": ObjectId(video_id),
            "SavedAt": datetime.datetime.now(datetime.timezone.utc)
        })
        videos_collection.update_one(
            {"_id": ObjectId(video_id)},
            {"$inc": {"CountSave": 1}}
        )
        await manager_video.broadcast(video_id, {
            "type": "save_count",
            "value": videos_collection.find_one({"_id": ObjectId(video_id)}).get("CountSave", 0),
            "user_id": user_id,
            "saved": not bool(saved)
        })
        return {"saved": True}

class ShareVideoMessage(BaseModel):
    from_user_id: str
    to_user_id: str
    video_id: str

@router.post("/share-video")
async def share_video(share: ShareVideoMessage):
    if not ObjectId.is_valid(share.video_id) or not ObjectId.is_valid(share.from_user_id) or not ObjectId.is_valid(share.to_user_id):
        raise HTTPException(status_code=400, detail="Invalid ObjectId provided")

    created_at = datetime.datetime.now(datetime.timezone.utc)

    video_data = videos_collection.find_one({"_id": ObjectId(share.video_id)})
    if not video_data:
        raise HTTPException(status_code=404, detail="Video not found")

    video_link = f"https://www.anyvoice.world/video/{video_data.get('Link', str(share.video_id))}"

    # ✅ INSERT MESSAGE (UNIFIED)
    result = messages_collection.insert_one({
        "from_user_id": ObjectId(share.from_user_id),
        "to_user_id": ObjectId(share.to_user_id),
        "message": video_link,
        "video_id": ObjectId(share.video_id),
        "created_at": created_at,
        "is_deleted": False,
        "is_edited": False,
        "is_read": False,
        "type": "video"
    })

    message_id = str(result.inserted_id)

    # ✅ UPDATE SHARE COUNT
    videos_collection.update_one(
        {"_id": ObjectId(share.video_id)},
        {"$inc": {"CountShare": 1}}
    )

    updated_video = videos_collection.find_one({"_id": ObjectId(share.video_id)})

    await manager_video.broadcast(str(share.video_id), {
        "type": "share_count",
        "value": updated_video.get("CountShare", 0)
    })

    # ✅ USER
    user_data = users_collection.find_one({"_id": ObjectId(share.from_user_id)})
    if not user_data:
        raise HTTPException(status_code=404, detail="User not found")

    decrypted_display = decrypt_data(user_data.get('Display', ''), ENCRYPTION_KEY) if user_data.get('Display') else ''

    # ✅ PAYLOAD
    message_payload = {
        "type": "new_messanger",
        "value": {
            "from_user_id": str(share.from_user_id),
            "to_user_id": str(share.to_user_id),
            "username": user_data["Username"],
            "display": decrypted_display,
            "message": video_link,
            "video_id": share.video_id,
            "created_at": created_at.isoformat() + "Z",
            "message_id": message_id,
            "is_edited": False,
            "is_deleted": False,
            "type": "video"
        },
    }

    # ✅ USE ONE WS MANAGER
    await manager_chat.broadcast(str(share.from_user_id), message_payload)
    await manager_chat.broadcast(str(share.to_user_id), message_payload)

    return {"success": True, "message_id": message_id}

@router.post("/cancel-share-video")
async def cancel_share_video(share: ShareVideoMessage):
    from_id = ObjectId(share.from_user_id)
    to_id = ObjectId(share.to_user_id)
    video_id = ObjectId(share.video_id)

    video_data = videos_collection.find_one({"_id": video_id})
    if not video_data:
        raise HTTPException(status_code=404, detail="Video not found")

    video_link = video_data.get("Link")

    # ✅ GET NEWEST MESSAGE
    message = messages_collection.find_one(
        {
            "from_user_id": from_id,
            "to_user_id": to_id,
            "message": video_link,
            "type": "video",
            "is_deleted": False,
        },
        sort=[("created_at", -1)]
    )

    if not message:
        raise HTTPException(status_code=404, detail="Message not found")

    if message.get("is_deleted", False):
        raise HTTPException(status_code=400, detail="Already deleted")

    deleted_at = datetime.datetime.now(datetime.timezone.utc)

    # ✅ SOFT DELETE
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

    # ✅ FIND REPLIES
    replied_messages = list(messages_collection.find({
        "reply_to_message_id": message["_id"],
        "is_deleted": {"$ne": True}
    }))

    user_data = users_collection.find_one({"_id": from_id})
    if not user_data:
        raise HTTPException(status_code=404, detail="User not found")

    decrypted_display = decrypt_data(user_data.get('Display', ''), ENCRYPTION_KEY) if user_data.get('Display') else ''

    # ✅ DELETE EVENT
    message_payload = {
        "type": "delete_messanger",
        "value": {
            "from_user_id": str(message["from_user_id"]),
            "to_user_id": str(message["to_user_id"]),
            "username": user_data["Username"],
            "display": decrypted_display,
            "message_id": str(message["_id"]),
            "created_at": message["created_at"].isoformat(),
            "is_deleted": True,
            "deleted_by": str(from_id),
            "deleted_at": deleted_at.isoformat(),
            "type": "video"
        },
    }

    await manager_chat.broadcast(str(message["from_user_id"]), message_payload)
    await manager_chat.broadcast(str(message["to_user_id"]), message_payload)

    # ✅ UPDATE REPLIES
    for reply_msg in replied_messages:
        updated_reply_info = {
            "message_id": str(message["_id"]),
            "text": "[Deleted video]",
            "from_username": user_data["Username"],
            "from_user_id": str(message["from_user_id"]),
            "message_type": "video",
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

    # ✅ UPDATE SHARE COUNT
    videos_collection.update_one(
        {"_id": video_id},
        {"$inc": {"CountShare": -1}}
    )

    updated_video = videos_collection.find_one({"_id": video_id})

    await manager_video.broadcast(str(share.video_id), {
        "type": "share_count",
        "value": max(0, updated_video.get("CountShare", 0))
    })

    return {"success": True}

class VideoReportRequest(BaseModel):
    user_id: str
    video_id: str
    reason: str

@router.post("/report-video")
async def report_video(request: VideoReportRequest):
    # Validate ObjectId
    if not ObjectId.is_valid(request.user_id) or not ObjectId.is_valid(request.video_id):
        raise HTTPException(status_code=400, detail="Invalid user_id or video_id format")

    # Check if comment exists
    video = videos_collection.find_one({"_id": ObjectId(request.video_id)})
    if not video:
        raise HTTPException(status_code=404, detail="video not found")

    # Check if user exists
    user = users_collection.find_one({"_id": ObjectId(request.user_id)})
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # Check for duplicate report
    existing_report = reports_of_video.find_one({
        "user_id": ObjectId(request.user_id),
        "video_id": ObjectId(request.video_id)
    })
    if existing_report:
        raise HTTPException(status_code=401, detail="You have already reported this video")

    # Encrypt reason
    encrypted_reason = encrypt_data(request.reason, ENCRYPTION_KEY)

    # Save report in VideoReports table
    report_data = {
        "user_id": ObjectId(request.user_id),
        "video_id": ObjectId(request.video_id),
        "reason": encrypted_reason,
        "created_at": datetime.datetime.now(datetime.timezone.utc)
    }
    reports_of_video.insert_one(report_data)

    send_email(
        recipient=my_email,
        message=f"""Шикоят аз видеои https://www.anyvoice.world/video/{video["Link"]}.\n
        Шикоят кунанда: @{user['Username']}\n
        Сабаб: {request.reason}\n""",
        subject='Шикоят⚠️'
    )

    return {"success": True}

class DeletePostRequest(BaseModel):
    video_id: str
    user_id: str

@router.post("/delete-post-video")
async def delete_post_api(data: DeletePostRequest):
    video_id = ObjectId(data.video_id)
    user_id = ObjectId(data.user_id)

    # Fetch the video/post
    video = videos_collection.find_one({"_id": video_id})
    if not video:
        raise HTTPException(status_code=404, detail="Post not found")

    is_owner = video.get("UserId") == user_id
    collaborators_raw = video.get("CollaborationAccounts", "[]")

    # Parse collaborators
    if isinstance(collaborators_raw, str):
        try:
            collaborators = json.loads(collaborators_raw)
        except:
            collaborators = []
    elif isinstance(collaborators_raw, list):
        collaborators = collaborators_raw
    else:
        collaborators = []

    collaborators = [ObjectId(cid) for cid in collaborators if ObjectId.is_valid(str(cid))]
    is_collaborator = user_id in collaborators

    # Initialize CountPosts for the user if it doesn't exist
    user_info = users_collection.find_one({"_id": user_id})
    if not user_info:
        raise HTTPException(status_code=404, detail="User not found")
    if "CountPosts" not in user_info:
        users_collection.update_one(
            {"_id": user_id},
            {"$set": {"CountPosts": 0}}
        )

    if is_collaborator and not is_owner:
        # Collaborator case: Remove user from CollaborationAccounts and decrement their CountPosts
        if user_id in collaborators:
            collaborators.remove(user_id)
            videos_collection.update_one(
                {"_id": video_id},
                {"$set": {"CollaborationAccounts": collaborators}}
            )
            # Decrement collaborator's CountPosts by 1
            users_collection.update_one(
                {"_id": user_id},
                {"$inc": {"CountPosts": -1}}
            )

            users_collection.update_one(
                {"_id": user_id},
                {"$inc": {"CountVideos": -1}}
            )

            # Broadcast delete_post message
            await manager_account.broadcast(str(user_id), {
                "type": "delete_post",
                "post_id": str(data.video_id),
            })

        return {"status": "removed_from_collaborators"}

    elif is_owner:
        # Owner case: Delete the post and decrement owner's CountPosts
        videos_collection.delete_one({"_id": video_id})
        videos_comment_collection.delete_many({"video_id": video_id})
        videos_comment_likes.delete_many({"video_id": video_id})
        reports_of_video.delete_many({"video_id": video_id})
        videos_support_collection.delete_many({"PostVideoId": video_id})
        videos_save_collection.delete_many({"PostVideoId": video_id})
        notifications_collection.delete_many({"PostId": video_id})
        messages_db["Messages"].delete_many({"video_id": video_id})

        # Delete HLS files
        hls_path = video.get("HLSStoragePath")
        if hls_path and os.path.exists(hls_path):
            import shutil
            shutil.rmtree(hls_path)

        # Delete thumbnail from GridFS
        thumbnail_id = video.get("ThumbnailId")
        if thumbnail_id:
            try:
                videos_fs.delete(ObjectId(thumbnail_id))
            except Exception as e:
                pass

        # Decrement owner's CountPosts by 1
        users_collection.update_one(
            {"_id": user_id},
            {"$inc": {"CountPosts": -1}}
        )

        users_collection.update_one(
            {"_id": user_id},
            {"$inc": {"CountVideos": -1}}
        )

        # Decrement CountPosts for all collaborators by 1 each
        for collaborator_id in collaborators:
            collaborator_info = users_collection.find_one({"_id": collaborator_id})
            if collaborator_info:
                if "CountPosts" not in collaborator_info:
                    users_collection.update_one(
                        {"_id": collaborator_id},
                        {"$set": {"CountPosts": 0}}
                    )

                users_collection.update_one(
                    {"_id": collaborator_id},
                    {"$inc": {"CountPosts": -1}}
                )

                users_collection.update_one(
                    {"_id": collaborator_id},
                    {"$inc": {"CountVideos": -1}}
                )

        # Broadcast delete_post message
        await manager_account.broadcast(str(user_id), {
            "type": "delete_post",
            "post_id": str(data.video_id),
        })

        # Broadcast delete_post message
        await manager_video.broadcast(str(data.video_id), {
            "type": "delete_post",
            "post_id": str(data.video_id),
        })

        return {"status": "deleted"}

# =====================================================
# 🔥 NEW HLS STREAMING ENDPOINT
# =====================================================
@router.get("/hls/{post_id}/{video_id}/{filename:path}")
async def serve_hls_file(post_id: str, video_id: str, filename: str):
    """Сервер кардани файлҳои HLS (playlist.m3u8 ва segment_*.ts)"""
    file_path = os.path.join(HLS_STORAGE_PATH, post_id, video_id, filename)
    
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="File not found")
    
    # Determine content type based on file extension
    if filename.endswith('.m3u8'):
        media_type = 'application/vnd.apple.mpegurl'
    elif filename.endswith('.ts'):
        media_type = 'video/MP2T'
    else:
        media_type = 'application/octet-stream'
    
    return FileResponse(
        file_path,
        media_type=media_type,
        headers={
            'Cache-Control': 'no-cache',
            'Access-Control-Allow-Origin': '*'
        }
    )

@router.get("/hls-master/{post_id}/{video_id}")
async def serve_hls_master(post_id: str, video_id: str):
    """Сервер кардани master.m3u8 барои видео"""
    # Find the video in database to get correct master URL
    post_info = videos_collection.find_one({"_id": ObjectId(post_id)})
    if not post_info:
        raise HTTPException(status_code=404, detail="Post not found")
    
    hls_videos = post_info.get("HLSVideos", [])
    video_found = None
    for v in hls_videos:
        if v.get('video_id') == video_id:
            video_found = v
            break
    
    if not video_found:
        raise HTTPException(status_code=404, detail="Video not found")
    
    master_path = os.path.join(HLS_STORAGE_PATH, post_id, video_id, 'master.m3u8')
    
    if not os.path.exists(master_path):
        raise HTTPException(status_code=404, detail="Master playlist not found")
    
    return FileResponse(
        master_path,
        media_type='application/vnd.apple.mpegurl',
        headers={
            'Cache-Control': 'no-cache',
            'Access-Control-Allow-Origin': '*'
        }
    )

@router.get("/hls-qualities/{post_id}/{video_id}")
async def get_hls_qualities(post_id: str, video_id: str):
    """Гирифтани рӯйхати сифатҳои дастрас барои видео"""
    post_info = videos_collection.find_one({"_id": ObjectId(post_id)})
    if not post_info:
        raise HTTPException(status_code=404, detail="Post not found")
    
    hls_videos = post_info.get("HLSVideos", [])
    for v in hls_videos:
        if v.get('video_id') == video_id:
            return {
                'qualities': v.get('qualities', ['360p', '480p', '720p']),
                'master_url': f"/hls-master/{post_id}/{video_id}"
            }
    
    raise HTTPException(status_code=404, detail="Video not found")
