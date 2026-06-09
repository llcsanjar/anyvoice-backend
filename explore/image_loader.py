# backend/explore/image_loader.py

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
import base64
from bson import ObjectId
import os
from pydantic import BaseModel
from fastapi import Query
import datetime
import re
import json
from cryptography.fernet import Fernet
from menu.menu import images_collection, images_support_collection, users_collection,\
images_comment_collection, images_fs, users_fs, reports_of_image, messages_db, \
images_views_collection, notifications_collection, \
images_comment_likes, images_save_collection, messages_collection
from account.account import manager_account
from home.chat import manager_chat
from menu.menu import encrypt_data, decrypt_data
from home.home import send_email

ENCRYPTION_KEY = os.getenv("ENCRYPTION_KEY")
my_email = os.getenv("MY_EMAIL")

fernet = Fernet(ENCRYPTION_KEY)

router = APIRouter()

# Connection Manager for WebSocket
class ConnectionManager:
    def __init__(self):
        self.active_connections: dict[str, list[WebSocket]] = {}

    async def connect(self, websocket: WebSocket, image_id: str):
        try:
            await websocket.accept()
            if image_id not in self.active_connections:
                self.active_connections[image_id] = []
            self.active_connections[image_id].append(websocket)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Error in WebSocket connect: {e}")

    def disconnect(self, websocket: WebSocket, image_id: str):
        try:
            if image_id in self.active_connections:
                if websocket in self.active_connections[image_id]:
                    self.active_connections[image_id].remove(websocket)
                if not self.active_connections[image_id]:
                    del self.active_connections[image_id]
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Error in WebSocket disconnect: {e}")

    async def broadcast(self, image_id: str, message: dict):
        if image_id in self.active_connections:
            connections_to_remove = []
            for connection in self.active_connections[image_id]:
                try:
                    await connection.send_json(message)
                except Exception as e:
                    connections_to_remove.append(connection)
            # Remove invalid connections
            for connection in connections_to_remove:
                self.disconnect(connection, image_id)

manager_image = ConnectionManager()

@router.websocket("/ws/updates-image/{image_id}")
async def websocket_updates(websocket: WebSocket, image_id: str):
    await manager_image.connect(websocket, image_id)
    try:
        while True:
            # Wait for messages to keep connection alive
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager_image.disconnect(websocket, image_id)
    except Exception as e:
        manager_image.disconnect(websocket, image_id)

@router.get("/get-image-preview/{image_id}")
async def get_image_preview(
    image_id: str,
    user_id: str = Query(None, description="ID of the requesting user")
):
    # Validate ObjectId
    if not ObjectId.is_valid(image_id):
        raise HTTPException(status_code=400, detail="Invalid image ID format")

    post_info = images_collection.find_one({"_id": ObjectId(image_id)})
    if not post_info:
        raise HTTPException(status_code=404, detail="Post not found")

    # 🚫 Check if post is banned
    if post_info.get("Banned", False):
        return {
            "is_banned": True
        }

    # 🚫 Check if post owner account is banned
    user_info = users_collection.find_one({"_id": post_info["UserId"]})
    if not user_info:
        raise HTTPException(status_code=404, detail="User not found")

    if user_info.get("Banned", False):
        return {
            "is_banned": True
        }

    user_is_blocked = False

    # If user_id is provided, check block list
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

    image_ids = post_info.get("ImageIds", [])
    if not image_ids:
        raise HTTPException(status_code=404, detail="No images found for this post")

    # Get only first image
    first_image_data = images_fs.get(image_ids[0]).read()
    first_image_base64 = base64.b64encode(first_image_data).decode()

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
        file_avatar = users_fs.get(ObjectId(profile_image_id))
        avatar_base64 = base64.b64encode(
            file_avatar.read()
        ).decode("utf-8")
    else:
        avatar_base64 = ""

    return {
        "id": str(post_info["_id"]),
        "images_data": [first_image_base64],
        "image_count": len(image_ids),
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
        "is_banned": False,
    }

class BlockMessage(BaseModel):
    user_id: str
    block_user: str
    image_id: str

@router.post("/block-image")
async def block_image(block: BlockMessage):
    try:
        # Validate ObjectId
        if not ObjectId.is_valid(block.user_id) or not ObjectId.is_valid(block.block_user) or not ObjectId.is_valid(block.image_id):
            raise HTTPException(status_code=400, detail="Invalid user_id, block_user, or image_id format")

        # Get image information
        image = images_collection.find_one({"_id": ObjectId(block.image_id)})
        if not image:
            raise HTTPException(status_code=404, detail="Image not found")

        # Check permission: user_id must be owner or collaborator
        is_owner = str(image.get("UserId")) == block.user_id
        collaborator_ids = []
        collaboration_accounts = image.get("CollaborationAccounts", "")
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
            raise HTTPException(status_code=403, detail="Not authorized to block users for this image")

        # Check if user to block exists
        block_user_info = users_collection.find_one({"_id": ObjectId(block.block_user)})
        if not block_user_info:
            raise HTTPException(status_code=404, detail="User to block not found")

        # Add block_user as ObjectId to BlockUsersList
        block_users_list = image.get("BlockUsersList", [])
        block_user_object_id = ObjectId(block.block_user)
        if block_user_object_id not in block_users_list:
            block_users_list.append(block_user_object_id)
            images_collection.update_one(
                {"_id": ObjectId(block.image_id)},
                {"$set": {"BlockUsersList": block_users_list}}
            )

        # Broadcast update (with string ID for frontend)
        await manager_image.broadcast(block.image_id, {
            "type": "block_user",
            "block_user_id": block.block_user,  # string for frontend
            "image_id": block.image_id
        })

        return {"success": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/cancel-block-image")
async def cancel_block(block: BlockMessage):
    try:
        # Validate ObjectId
        if not ObjectId.is_valid(block.user_id) or not ObjectId.is_valid(block.block_user) or not ObjectId.is_valid(block.image_id):
            raise HTTPException(status_code=400, detail="Invalid user_id, block_user, or image_id format")

        # Get image information
        image = images_collection.find_one({"_id": ObjectId(block.image_id)})
        if not image:
            raise HTTPException(status_code=404, detail="Image not found")

        # Check permission: user_id must be owner or collaborator
        is_owner = str(image.get("UserId")) == block.user_id
        collaborator_ids = []
        collaboration_accounts = image.get("CollaborationAccounts", "")
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
            raise HTTPException(status_code=403, detail="Not authorized to cancel block for this image")

        # Check if user to unblock exists
        block_user_info = users_collection.find_one({"_id": ObjectId(block.block_user)})
        if not block_user_info:
            raise HTTPException(status_code=404, detail="User to unblock not found")

        # Remove block_user as ObjectId from BlockUsersList
        block_users_list = image.get("BlockUsersList", [])
        block_user_object_id = ObjectId(block.block_user)
        if block_user_object_id in block_users_list:
            block_users_list.remove(block_user_object_id)
            images_collection.update_one(
                {"_id": ObjectId(block.image_id)},
                {"$set": {"BlockUsersList": block_users_list}}
            )

        # Broadcast update (with string ID for frontend)
        await manager_image.broadcast(block.image_id, {
            "type": "cancel_block_user",
            "block_user_id": block.block_user,  # string for frontend
            "image_id": block.image_id
        })

        return {"success": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/get-image-by-id/{image_id}")
def get_image_by_id_v2(image_id: str, user_id: str = Query(None)):
    """
    Version 2: Return all images, but more efficiently.
    """
    if not ObjectId.is_valid(image_id):
        raise HTTPException(status_code=400, detail="Invalid image ID format")

    post_info = images_collection.find_one({"_id": ObjectId(image_id)})
    if not post_info:
        raise HTTPException(status_code=404, detail="Post not found")

    # Check blocking
    if user_id and ObjectId.is_valid(user_id):
        block_list = post_info.get("BlockUsersList", [])
        block_object_ids = [
            ObjectId(uid) for uid in block_list if ObjectId.is_valid(str(uid))
        ]
        if ObjectId(user_id) in block_object_ids:
            raise HTTPException(status_code=403, detail="Access denied")

    image_ids = post_info.get("ImageIds", [])
    if not image_ids:
        raise HTTPException(status_code=404, detail="No images found")

    # Load only the first image for efficiency
    # Frontend can load remaining images with /get-image-by-index
    max_images_to_load = min(1, len(image_ids))
    images_data = []
    
    for i in range(max_images_to_load):
        try:
            file = images_fs.find_one({"_id": ObjectId(image_ids[i])})
            if file:
                image_binary = file.read()
                encoded = base64.b64encode(image_binary).decode('utf-8')
                images_data.append(encoded)
        except Exception:
            # If error occurs, leave placeholder empty for this index
            images_data.append("")

    user_info = users_collection.find_one({'_id': post_info['UserId']})
    if not user_info:
        raise HTTPException(status_code=404, detail="User not found")

    username = user_info['Username']
    display = user_info.get('Display', '')
    decrypted_display = decrypt_data(display, ENCRYPTION_KEY) if display else ''
    title = post_info.get('Title', '')
    description = post_info.get('Description', '')
    decrypted_link = post_info['Link']
    UploadAt = post_info.get('UploadAt').isoformat() + "Z"
    UpdateAt = post_info.get('UpdateAt')

    profile_image_id = user_info.get("ProfileImageId")
    if profile_image_id:
        file_avatar = users_fs.get(ObjectId(profile_image_id))
        avatar_base64 = base64.b64encode(file_avatar.read()).decode('utf-8')
    else:
        avatar_base64 = ''

    return {
        "id": str(post_info['_id']),
        "images_data": images_data,  # Only first image
        "total_images": len(image_ids),  # Total number of images
        "title": title,
        "description": description,
        "username": str(username),
        "display": str(decrypted_display),
        "avatar": avatar_base64,
        "support_count": post_info.get('CountSupport', 0),
        "comment_count": post_info.get('CountComment', 0),
        'collaborator_ids': str(post_info['CollaborationAccounts']),
        'share_count': post_info['CountShare'],
        'save_count': post_info['CountSave'],
        'count_view': post_info.get('CountView', 0),
        'Link': decrypted_link,
        'BlockUsersList': [str(uid) for uid in post_info.get('BlockUsersList', [])],
        'UploadAt': UploadAt,
        'UpdateAt': UpdateAt,
        'allow_comments': post_info['AllowComments'],
    }

@router.get("/get-image-by-index/{image_id}/{index}")
def get_image_by_index(image_id: str, index: int, user_id: str = Query(None)):
    """
    Get a specific image from the image collection by index.
    """
    if not ObjectId.is_valid(image_id):
        raise HTTPException(status_code=400, detail="Invalid image ID format")

    # Get post information
    post_info = images_collection.find_one({"_id": ObjectId(image_id)})
    if not post_info:
        raise HTTPException(status_code=404, detail="Post not found")

    # Check blocking
    if user_id and ObjectId.is_valid(user_id):
        block_list = post_info.get("BlockUsersList", [])
        block_object_ids = [
            ObjectId(uid) for uid in block_list if ObjectId.is_valid(str(uid))
        ]
        if ObjectId(user_id) in block_object_ids:
            raise HTTPException(status_code=403, detail="Access denied")

    # Get image IDs
    image_ids = post_info.get("ImageIds", [])
    if not image_ids:
        raise HTTPException(status_code=404, detail="No images found")

    # Check index validity
    if index < 0 or index >= len(image_ids):
        raise HTTPException(status_code=400, detail="Invalid image index")

    # Get specific image
    try:
        image_id_obj = ObjectId(image_ids[index])
        file = images_fs.find_one({"_id": image_id_obj})
        if not file:
            raise HTTPException(status_code=404, detail="Image file not found")
        
        image_binary = file.read()
        encoded = base64.b64encode(image_binary).decode('utf-8')
        
        # Return only one image
        return {
            "image_id": encoded,
            "index": index,
            "total_images": len(image_ids)
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error loading image: {str(e)}")

@router.get("/check-support-image")
def get_support_info(
    user_id: str = Query(..., description="User ID"),
    image_id: str = Query(..., description="Image ID")
):
    try:
        # Validate ObjectId for user_id and image_id
        if not ObjectId.is_valid(user_id) or not ObjectId.is_valid(image_id):
            return False  # Return False instead of error

        # Check if image exists in ImagesData
        image_exists = images_collection.find_one({'_id': ObjectId(image_id)})
        if not image_exists:
            return False  # Return False instead of error

        # Check support
        support = images_support_collection.find_one({
            'UserId': ObjectId(user_id),
            'PostImageId': ObjectId(image_id),
        })

        return bool(support)  # Return True if support exists, False otherwise
    except Exception as e:
        return False  # Return False instead of error

@router.get("/check-save-image-status")
def check_save_status(image_id: str, user_id: str):
    if not ObjectId.is_valid(image_id) or not ObjectId.is_valid(user_id):
        raise HTTPException(status_code=400, detail="Invalid ID format")

    saved = images_save_collection.find_one({
        "PostImageId": ObjectId(image_id),
        "UserId": ObjectId(user_id)
    })

    return {"saved": bool(saved)}  # True or False

class ViewEndRequest(BaseModel):
    user_id: str
    image_id: str

@router.post("/track-view-image")
async def track_view_end(request: ViewEndRequest):
    if not ObjectId.is_valid(request.user_id) or not ObjectId.is_valid(request.image_id):
        raise HTTPException(status_code=400, detail="Invalid user_id or image_id format")

    user_id = ObjectId(request.user_id)
    image_id = ObjectId(request.image_id)

    image = images_collection.find_one({"_id": image_id})
    if not image:
        raise HTTPException(status_code=404, detail="Image not found")

    # Check: does view record already exist
    existing_view = images_views_collection.find_one({
        "user_id": user_id,
        "image_id": image_id
    })

    # ✅ If record does not exist, create it and increment CountView once
    if not existing_view:
        images_views_collection.insert_one({
            "user_id": user_id,
            "image_id": image_id,
            "viewed_at": datetime.datetime.now(datetime.timezone.utc)
        })

        images_collection.update_one(
            {"_id": image_id},
            {"$inc": {"CountView": 1}}
        )

        image_data = images_collection.find_one({"_id": image_id})
        await manager_image.broadcast(str(image_id), {
            "type": "view_count",
            "value": image_data.get("CountView", 0)
        })

    # If record already exists, do nothing
    return {"success": True}

@router.get("/support-image-delete")
async def support_image_delete(
    user_id: str = Query(..., description="User ID"),
    image_id: str = Query(..., description="Image ID")
):
    # Check if the user has already supported this image
    existing_support = images_support_collection.find_one({
        'UserId': ObjectId(user_id),
        'PostImageId': ObjectId(image_id)
    })

    if not existing_support:
        raise HTTPException(
            status_code=400,
            detail="This user has not supported this image or has already removed support"
        )

    images_support_collection.delete_one({
        'UserId': ObjectId(user_id),
        'PostImageId': ObjectId(image_id),
    })

    images_collection.update_one(
        {'_id': ObjectId(image_id)},
        {'$inc': {'CountSupport': -1}},
    )

    # Broadcast updated support count
    image_data = images_collection.find_one({'_id': ObjectId(image_id)})
    await manager_image.broadcast(image_id, {
        "type": "support_count",
        "value": image_data.get('CountSupport', 0),
        "user_id": user_id,
        "support": False,
    })

    return {"success": True}

@router.get("/support-image-save")
async def support_image_save(
    user_id: str = Query(..., description="User ID"),
    image_id: str = Query(..., description="Image ID")
):
    # Check if the user has already supported this image
    existing_support = images_support_collection.find_one({
        'UserId': ObjectId(user_id),
        'PostImageId': ObjectId(image_id)
    })

    if existing_support:
        raise HTTPException(
            status_code=400,
            detail="This user has already supported this image"
        )

    images_support_collection.insert_one({
        'UserId': ObjectId(user_id),
        'PostImageId': ObjectId(image_id),
        "UploadAt": datetime.datetime.now(datetime.timezone.utc),
    })

    images_collection.update_one(
        {'_id': ObjectId(image_id)},
        {'$inc': {'CountSupport': 1}},
    )

    # Broadcast updated support count
    image_data = images_collection.find_one({'_id': ObjectId(image_id)})
    await manager_image.broadcast(image_id, {
        "type": "support_count",
        "value": image_data.get('CountSupport', 0),
        "user_id": user_id,
        "support": True,
    })

    return {"success": True}

@router.get("/save-image")
async def save_image(user_id: str, image_id: str):
    saved = images_save_collection.find_one({
        "UserId": ObjectId(user_id),
        "PostImageId": ObjectId(image_id)
    })
    if saved:
        images_save_collection.delete_one({
            "UserId": ObjectId(user_id),
            "PostImageId": ObjectId(image_id)
        })
        images_collection.update_one(
            {"_id": ObjectId(image_id)},
            {"$inc": {"CountSave": -1}}
        )
        await manager_image.broadcast(image_id, {
            "type": "save_count",
            "value": images_collection.find_one({"_id": ObjectId(image_id)}).get("CountSave", 0),
            "user_id": user_id,
            "saved": not bool(saved)
        })
        return {"saved": False}
    else:
        images_save_collection.insert_one({
            "UserId": ObjectId(user_id),
            "PostImageId": ObjectId(image_id),
            "SavedAt": datetime.datetime.now(datetime.timezone.utc)
        })
        images_collection.update_one(
            {"_id": ObjectId(image_id)},
            {"$inc": {"CountSave": 1}}
        )
        await manager_image.broadcast(image_id, {
            "type": "save_count",
            "value": images_collection.find_one({"_id": ObjectId(image_id)}).get("CountSave", 0),
            "user_id": user_id,
            "saved": not bool(saved)
        })
        return {"saved": True}

class ShareMessage(BaseModel):
    from_user_id: str
    to_user_id: str
    image_id: str

@router.post("/share-image")
async def share_image(share: ShareMessage):
    created_at = datetime.datetime.now(datetime.timezone.utc)

    image_data = images_collection.find_one({"_id": ObjectId(share.image_id)})
    if not image_data:
        raise HTTPException(status_code=404, detail="Image not found")

    image_link = f"https://www.anyvoice.world/image/{image_data.get('Link', str(share.image_id))}"

    # ✅ INSERT MESSAGE (UNIFIED FORMAT)
    result = messages_collection.insert_one({
        "from_user_id": ObjectId(share.from_user_id),
        "to_user_id": ObjectId(share.to_user_id),
        "message": image_link,
        "image_id": ObjectId(share.image_id),
        "created_at": created_at,
        "is_deleted": False,
        "is_edited": False,
        "is_read": False,
        "type": "image"
    })

    message_id = str(result.inserted_id)

    # ✅ UPDATE SHARE COUNT
    images_collection.update_one(
        {"_id": ObjectId(share.image_id)},
        {"$inc": {"CountShare": 1}}
    )

    updated_image = images_collection.find_one({"_id": ObjectId(share.image_id)})

    await manager_image.broadcast(str(share.image_id), {
        "type": "share_count",
        "value": updated_image.get("CountShare", 0)
    })

    # ✅ USER DATA
    user_data = users_collection.find_one({"_id": ObjectId(share.from_user_id)})
    if not user_data:
        raise HTTPException(status_code=404, detail="User not found")

    decrypted_display = decrypt_data(user_data.get('Display', ''), ENCRYPTION_KEY) if user_data.get('Display') else ''

    # ✅ PAYLOAD (UNIFIED)
    message_payload = {
        "type": "new_messanger",
        "value": {
            "from_user_id": str(share.from_user_id),
            "to_user_id": str(share.to_user_id),
            "username": user_data["Username"],
            "display": decrypted_display,
            "message": image_link,
            "image_id": share.image_id,
            "created_at": created_at.isoformat() + "Z",
            "message_id": message_id,
            "is_edited": False,
            "is_deleted": False,
            "type": "image"
        },
    }

    # ✅ USE ONE MANAGER
    await manager_chat.broadcast(str(share.from_user_id), message_payload)
    await manager_chat.broadcast(str(share.to_user_id), message_payload)

    return {"success": True, "message_id": message_id}

@router.post("/cancel-share-image")
async def cancel_share_image(share: ShareMessage):
    from_id = ObjectId(share.from_user_id)
    to_id = ObjectId(share.to_user_id)
    image_id = ObjectId(share.image_id)

    image_data = images_collection.find_one({"_id": image_id})
    if not image_data:
        raise HTTPException(status_code=404, detail="Image not found")

    image_link = image_data.get("Link")

    # ✅ GET LATEST MESSAGE
    message = messages_collection.find_one(
        {
            "from_user_id": from_id,
            "to_user_id": to_id,
            "message": image_link,
            "type": "image",
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

    # ✅ USER DATA
    user_data = users_collection.find_one({"_id": from_id})
    if not user_data:
        raise HTTPException(status_code=404, detail="User not found")

    decrypted_display = decrypt_data(user_data.get('Display', ''), ENCRYPTION_KEY) if user_data.get('Display') else ''

    # ✅ DELETE PAYLOAD
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
            "type": "image"
        },
    }

    await manager_chat.broadcast(str(message["from_user_id"]), message_payload)
    await manager_chat.broadcast(str(message["to_user_id"]), message_payload)

    # ✅ UPDATE REPLIES
    for reply_msg in replied_messages:
        updated_reply_info = {
            "message_id": str(message["_id"]),
            "text": "[Deleted image]",
            "from_username": user_data["Username"],
            "from_user_id": str(message["from_user_id"]),
            "message_type": "image",
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
    images_collection.update_one(
        {"_id": image_id},
        {"$inc": {"CountShare": -1}}
    )

    updated_image = images_collection.find_one({"_id": image_id})

    await manager_image.broadcast(str(share.image_id), {
        "type": "share_count",
        "value": max(0, updated_image.get("CountShare", 0))
    })

    return {"success": True}

class ImageReportRequest(BaseModel):
    user_id: str
    image_id: str
    reason: str

@router.post("/report-image")
async def report_image(request: ImageReportRequest):
    # Validate ObjectId
    if not ObjectId.is_valid(request.user_id) or not ObjectId.is_valid(request.image_id):
        raise HTTPException(status_code=400, detail="Invalid user_id or image_id format")

    # Check if comment exists
    image = images_collection.find_one({"_id": ObjectId(request.image_id)})
    if not image:
        raise HTTPException(status_code=404, detail="image not found")

    # Check if user exists
    user = users_collection.find_one({"_id": ObjectId(request.user_id)})
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # Check for duplicate report
    existing_report = reports_of_image.find_one({
        "user_id": ObjectId(request.user_id),
        "image_id": ObjectId(request.image_id)
    })
    if existing_report:
        raise HTTPException(status_code=401, detail="You have already reported this image")

    # Encrypt reason
    encrypted_reason = encrypt_data(request.reason, ENCRYPTION_KEY)

    # Save report in ImageReports table
    report_data = {
        "user_id": ObjectId(request.user_id),
        "image_id": ObjectId(request.image_id),
        "reason": encrypted_reason,
        "created_at": datetime.datetime.now(datetime.timezone.utc)
    }
    reports_of_image.insert_one(report_data)

    send_email(
        recipient=my_email,
        message=f"""Шикоят аз расми https://www.anyvoice.world/image/{image["Link"]}.\n
        Шикоят кунанда: @{user['Username']}\n
        Сабаб: {request.reason}\n""",
        subject='Шикоят⚠️'
    )

    return {"success": True}

class DeletePostRequest(BaseModel):
    image_id: str
    user_id: str

@router.post("/delete-post-image")
async def delete_post_api(data: DeletePostRequest):
    image_id = ObjectId(data.image_id)
    user_id = ObjectId(data.user_id)

    # Fetch the image/post
    image = images_collection.find_one({"_id": image_id})
    if not image:
        raise HTTPException(status_code=404, detail="Post not found")

    is_owner = image.get("UserId") == user_id
    collaborators_raw = image.get("CollaborationAccounts", "[]")

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
            images_collection.update_one(
                {"_id": image_id},
                {"$set": {"CollaborationAccounts": [str(cid) for cid in collaborators]}}
            )
            # Decrement collaborator's CountPosts by 1
            users_collection.update_one(
                {"_id": user_id},
                {"$inc": {"CountPosts": -1}}
            )

            users_collection.update_one(
                {"_id": user_id},
                {"$inc": {"CountImages": -1}}
            )

            # Broadcast delete_post message
            await manager_account.broadcast(str(user_id), {
                "type": "delete_post",
                "post_id": str(data.image_id),
            })

        return {"status": "deleted"}

    elif is_owner:
        # Owner case: Delete the post and decrement owner's CountPosts
        images_collection.delete_one({"_id": image_id})
        images_comment_collection.delete_many({"image_id": image_id})
        images_comment_likes.delete_many({"image_id": image_id})
        reports_of_image.delete_many({"image_id": image_id})
        images_support_collection.delete_many({"PostImageId": image_id})
        images_save_collection.delete_many({"PostImageId": image_id})
        notifications_collection.delete_many({"PostId": image_id})
        messages_db["Messages"].delete_many({"image_id": image_id})

        # Delete associated files from GridFS
        for img_id in image.get("ImageIds", []):
            try:
                images_fs.delete(ObjectId(img_id))
            except Exception as e:
                raise HTTPException(status_code=400, detail=f"Error deleting image file {img_id} from GridFS: {e}")

        # Decrement owner's CountPosts by 1
        users_collection.update_one(
            {"_id": user_id},
            {"$inc": {"CountPosts": -1}}
        )

        users_collection.update_one(
            {"_id": user_id},
            {"$inc": {"CountImages": -1}}
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
                    {"$inc": {"CountImages": -1}}
                )

        # Broadcast delete_post message
        await manager_account.broadcast(str(user_id), {
            "type": "delete_post",
            "post_id": str(data.image_id),
        })

        # Broadcast delete_post message
        await manager_image.broadcast(str(data.image_id), {
            "type": "delete_post",
            "post_id": str(data.image_id),
        })

        return {"status": "deleted"}
