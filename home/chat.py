# backend/home/chat.py

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect, Query, Body
from pydantic import BaseModel
from cryptography.fernet import Fernet
import os
from bson import ObjectId
from fastapi import Query
import base64
from cryptography.fernet import Fernet
from menu.menu import users_collection, users_fs, messages_collection
from typing import List, Optional
from home.home import serialize_notification, broadcast_notification
from home.status import status_manager
from datetime import datetime, timezone
from menu.menu import encrypt_data, decrypt_data

ENCRYPTION_KEY = os.getenv("ENCRYPTION_KEY")
fernet = Fernet(ENCRYPTION_KEY)

router = APIRouter()

# Connection Manager for WebSocket
class ConnectionManagerChat:
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

manager_chat = ConnectionManagerChat()

@router.websocket("/ws/chat-updates/{user_id}")
async def websocket_updates(websocket: WebSocket, user_id: str):
    await manager_chat.connect(websocket, user_id)
    try:
        while True:
            # Wait for messages to keep connection alive
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager_chat.disconnect(websocket, user_id)
    except Exception as e:
        manager_chat.disconnect(websocket, user_id)

class Messager(BaseModel):
    from_user_id: str
    to_user_id: str
    text: str
    reply_to_message_id: Optional[str] = None  # Барои ҷавоб ба паём

@router.post("/messanger")
async def messanger_accounts(messanger: Messager):
    created_at = datetime.now(timezone.utc)
    encrypted_text = encrypt_data(messanger.text, ENCRYPTION_KEY)
    message_type = "text"

    message_data = {
        "from_user_id": ObjectId(messanger.from_user_id),
        "to_user_id": ObjectId(messanger.to_user_id),
        "message": encrypted_text,
        "created_at": created_at,
        "is_edited": False,
        "is_read": False,
        "is_deleted": False,
        "deleted_by": None,
        "deleted_at": None,
    }

    # Агар паём ҷавоб бошад
    if messanger.reply_to_message_id and ObjectId.is_valid(messanger.reply_to_message_id):
        message_data["reply_to_message_id"] = ObjectId(messanger.reply_to_message_id)

    result = messages_collection.insert_one(message_data)

    user_data = users_collection.find_one({"_id": ObjectId(messanger.from_user_id)})
    if not user_data:
        raise HTTPException(status_code=404, detail="User not found")
    decrypted_display = user_data.get('Display', '')
    try:
        decrypted_display = decrypt_data(decrypted_display, ENCRYPTION_KEY)
    except Exception:
        pass

    profile_image_id = user_data.get("ProfileImageId")
    avatar_base64 = ''
    if profile_image_id:
        try:
            file_avatar = users_fs.get(ObjectId(profile_image_id))
            avatar_base64 = base64.b64encode(file_avatar.read()).decode('utf-8')
        except Exception as e:
            avatar_base64 = ''

    username = user_data.get("Username")

    message_payload = {
        "type": "new_messanger",
        "value": {
            'from_user_id': str(messanger.from_user_id),
            'to_user_id': str(messanger.to_user_id),
            'username': user_data['Username'],
            'display': decrypted_display,
            'message': messanger.text,
            'created_at': created_at.isoformat(),
            'message_id': str(result.inserted_id),
            "is_edited": False,
            "is_deleted": False,
            "from_user_avatar": f"data:image/jpeg;base64,{avatar_base64}",
            "from_username": username,
        },
    }

    # Агар паём ҷавоб бошад, маълумоти паёми асосиро илова кун
    if messanger.reply_to_message_id and ObjectId.is_valid(messanger.reply_to_message_id):
        reply_to_msg = messages_collection.find_one({"_id": ObjectId(messanger.reply_to_message_id)})
        if reply_to_msg:
            try:
                reply_text = decrypt_data(reply_to_msg["message"], ENCRYPTION_KEY)
            except Exception:
                message_type = "voice"
                reply_text = None

            reply_from_user = users_collection.find_one({"_id": reply_to_msg["from_user_id"]})
            reply_username = reply_from_user.get("Username", "Unknown") if reply_from_user else "Unknown"
            
            message_payload["value"]["reply_to"] = {
                "message_id": str(reply_to_msg["_id"]),
                "text": reply_text,
                "from_username": reply_username,
                "from_user_id": str(reply_to_msg["from_user_id"]),
                "message_type": message_type,
            }

    serialized_notification = serialize_notification(message_payload)
    await broadcast_notification(str(messanger.to_user_id), "new_messanger", serialized_notification)

    await manager_chat.broadcast(str(messanger.from_user_id), message_payload)
    await manager_chat.broadcast(str(messanger.to_user_id), message_payload)

    return {"success": True, "message_id": str(result.inserted_id), "created_at": created_at.isoformat()}

@router.post("/voice-message")
async def send_voice_message(
    from_user_id: str = Body(...),
    to_user_id: str = Body(...),
    voice_data: str = Body(...),  # Base64 encoded voice data
    duration: int = Body(...),     # Дарозии овоз дар сония
    reply_to_message_id: Optional[str] = Body(None)
):
    """Фиристодани паёми овозӣ (рамзгузоришуда)"""
    created_at = datetime.now(timezone.utc)
    
    # ⭐ Рамзгузории маълумоти овозӣ пеш аз захира
    encrypted_voice_data = encrypt_data(voice_data, ENCRYPTION_KEY)
    
    message_data = {
        "from_user_id": ObjectId(from_user_id),
        "to_user_id": ObjectId(to_user_id),
        "message_type": "voice",
        "voice_data": encrypted_voice_data,  # ⭐ Маълумоти рамзгузоришуда
        "voice_duration": duration,
        "created_at": created_at,
        "is_edited": False,
        "is_read": False,
        "is_deleted": False,
        "deleted_by": None,
        "deleted_at": None,
    }
    
    if reply_to_message_id and ObjectId.is_valid(reply_to_message_id):
        message_data["reply_to_message_id"] = ObjectId(reply_to_message_id)
    
    result = messages_collection.insert_one(message_data)
    
    # Гирифтани маълумоти фиристанда
    user_data = users_collection.find_one({"_id": ObjectId(from_user_id)})
    if not user_data:
        raise HTTPException(status_code=404, detail="User not found")
        
    decrypted_display = user_data.get('Display', '')
    try:
        decrypted_display = fernet.decrypt(decrypted_display.encode()).decode()
    except Exception:
        pass
        
    profile_image_id = user_data.get("ProfileImageId")
    avatar_base64 = ''
    if profile_image_id:
        try:
            file_avatar = users_fs.get(ObjectId(profile_image_id))
            avatar_base64 = base64.b64encode(file_avatar.read()).decode('utf-8')
        except Exception as e:
            avatar_base64 = ''
    
    username = user_data.get("Username")
    
    # ⭐ Барои паёми WebSocket маълумоти аслӣ (рамзкушонашуда)-ро мефиристем
    message_payload = {
        "type": "new_messanger",
        "value": {
            'from_user_id': str(from_user_id),
            'to_user_id': str(to_user_id),
            'username': username,
            'display': decrypted_display,
            'message_type': 'voice',
            'voice_data': voice_data,  # ⭐ Маълумоти аслӣ барои пахш
            'voice_duration': duration,
            'created_at': created_at.isoformat(),
            'message_id': str(result.inserted_id),
            "is_edited": False,
            "is_deleted": False,
            "from_user_avatar": f"data:image/jpeg;base64,{avatar_base64}",
            "from_username": username,
        },
    }
    
    # Агар паём ҷавоб бошад
    if reply_to_message_id and ObjectId.is_valid(reply_to_message_id):
        reply_to_msg = messages_collection.find_one({"_id": ObjectId(reply_to_message_id)})
        if reply_to_msg:
            reply_text = ""
            if reply_to_msg.get("message_type") == "voice":
                reply_text = "[Voice message]"
            else:
                try:
                    reply_text = decrypt_data(reply_to_msg["message"], ENCRYPTION_KEY)
                except Exception:
                    reply_text = reply_to_msg.get("message", "")
            
            reply_from_user = users_collection.find_one({"_id": reply_to_msg["from_user_id"]})
            reply_username = reply_from_user.get("Username", "Unknown") if reply_from_user else "Unknown"
            
            message_payload["value"]["reply_to"] = {
                "message_id": str(reply_to_msg["_id"]),
                "text": reply_text,
                "from_username": reply_username,
                "from_user_id": str(reply_to_msg["from_user_id"]),
                "message_type": reply_to_msg.get("message_type", "text")
            }
    
    await manager_chat.broadcast(str(from_user_id), message_payload)
    await manager_chat.broadcast(str(to_user_id), message_payload)
    
    return {"success": True, "message_id": str(result.inserted_id)}

@router.get("/get-messages")
async def get_messages(
    user_id: str = Query(...),
    target_user_id: str = Query(None, description="ID-и корбари дигар (ихтиёрӣ)"),
    offset: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=1000),
    only_unread: bool = Query(False),
    last_sync_time: str = Query(None),
    include_deleted: bool = Query(False)
):
    user_obj_id = ObjectId(user_id)

    query = {}

    # conversation messages
    if target_user_id:
        target_obj_id = ObjectId(target_user_id)
        query = {
            "$or": [
                {
                    "from_user_id": user_obj_id,
                    "to_user_id": target_obj_id
                },
                {
                    "from_user_id": target_obj_id,
                    "to_user_id": user_obj_id
                }
            ]
        }
    else:
        query = {
            "$or": [
                {"from_user_id": user_obj_id},
                {"to_user_id": user_obj_id}
            ]
        }

    # deleted filter
    if not include_deleted:
        query["is_deleted"] = {"$ne": True}

    # unread only
    if only_unread:
        query = {
            "to_user_id": user_obj_id,
            "is_read": False,
            "is_deleted": {"$ne": True}
        }

        if target_user_id:
            query["from_user_id"] = ObjectId(target_user_id)

    # sync time filter
    if last_sync_time:
        try:
            sync_time = datetime.fromisoformat(
                last_sync_time.replace("Z", "+00:00")
            )
            query["created_at"] = {"$gte": sync_time}
        except Exception:
            pass

    total_count = messages_collection.count_documents(query)

    cursor = (
        messages_collection
        .find(query)
        .sort("created_at", -1)
        .skip(offset)
        .limit(limit)
    )

    raw_messages = list(cursor)

    # reply ids
    reply_ids = {
        msg["reply_to_message_id"]
        for msg in raw_messages
        if msg.get("reply_to_message_id")
    }

    reply_messages_data = {}

    if reply_ids:
        reply_messages = messages_collection.find({
            "_id": {"$in": list(reply_ids)},
            "is_deleted": {"$ne": True}
        })

        for reply_msg in reply_messages:
            reply_text = None
            message_type = reply_msg.get("message_type", "text")

            if message_type == "text":
                try:
                    reply_text = decrypt_data(
                        reply_msg["message"],
                        ENCRYPTION_KEY
                    )
                except Exception:
                    reply_text = reply_msg.get("message", "")
            else:
                reply_text = "[Voice message]"

            reply_user = users_collection.find_one({
                "_id": reply_msg["from_user_id"]
            })

            reply_messages_data[str(reply_msg["_id"])] = {
                "message_id": str(reply_msg["_id"]),
                "text": reply_text,
                "from_username": (
                    reply_user.get("Username", "Unknown")
                    if reply_user else "Unknown"
                ),
                "from_user_id": str(reply_msg["from_user_id"]),
                "message_type": message_type
            }

    messages_list = []
    deleted_message_ids = []

    for msg in raw_messages:
        message_type = msg.get("message_type", "text")

        from_user = users_collection.find_one({
            "_id": msg["from_user_id"]
        })

        from_username = (
            from_user.get("Username", "Unknown")
            if from_user else "Unknown"
        )

        message_data = {
            "id": str(msg["_id"]),
            "from_user_id": str(msg["from_user_id"]),
            "to_user_id": str(msg["to_user_id"]),
            "message_type": message_type,
            "created_at": msg["created_at"].isoformat() + "Z",
            "is_edited": msg.get("is_edited", False),
            "is_read": msg.get("is_read", False),
            "is_deleted": msg.get("is_deleted", False),
            "from_username": from_username,
            "deleted_by": (
                str(msg.get("deleted_by"))
                if msg.get("deleted_by") else None
            ),
            "deleted_at": (
                msg.get("deleted_at").isoformat() + "Z"
                if msg.get("deleted_at") else None
            )
        }

        if msg.get("is_deleted", False):
            deleted_message_ids.append(str(msg["_id"]))
        else:
            if message_type == "text":
                try:
                    message_data["text"] = decrypt_data(
                        msg["message"],
                        ENCRYPTION_KEY
                    )
                except Exception:
                    message_data["text"] = msg.get("message", "")

            elif message_type == "voice":
                message_data["voice_data"] = decrypt_data(
                    msg.get("voice_data", ""),
                    ENCRYPTION_KEY
                )
                message_data["voice_duration"] = msg.get(
                    "voice_duration", 0
                )

        # reply
        if msg.get("reply_to_message_id"):
            reply_id = str(msg["reply_to_message_id"])
            if reply_id in reply_messages_data:
                message_data["reply_to"] = reply_messages_data[reply_id]

        messages_list.append(message_data)

    grouped_messages = {}

    if only_unread:
        for msg in messages_list:
            sender = msg["from_user_id"]
            grouped_messages.setdefault(sender, []).append(msg)

    return {
        "success": True,
        "messages": messages_list,
        "total_count": total_count,
        "has_more": offset + len(messages_list) < total_count,
        "deleted_message_ids": deleted_message_ids,
        "grouped_messages": grouped_messages if only_unread else {},
        "unread_count": len(messages_list) if only_unread else 0
    }

@router.get("/get-deleted-messages")
async def get_deleted_messages(
    user_id: str = Query(...),
    last_sync_time: str = Query(None, description="Вақти охирин ҳамоҳангсозӣ")
):
    """
    Гирифтани паёмҳои ҳазфшуда барои ҳамоҳангсозӣ
    """
    try:
        user_obj_id = ObjectId(user_id)
        
        query = {
            "$or": [
                {"from_user_id": user_obj_id},
                {"to_user_id": user_obj_id}
            ],
            "is_deleted": True
        }
        
        if last_sync_time:
            try:
                sync_time = datetime.fromisoformat(last_sync_time.replace('Z', '+00:00'))
                query["deleted_at"] = {"$gt": sync_time}
            except Exception:
                pass
        
        messages = messages_collection.find(query).sort("deleted_at", -1).limit(100)
        
        deleted_messages = []
        for msg in messages:
            deleted_messages.append({
                "message_id": str(msg["_id"]),
                "from_user_id": str(msg["from_user_id"]),
                "to_user_id": str(msg["to_user_id"]),
                "deleted_by": str(msg.get("deleted_by")) if msg.get("deleted_by") else None,
                "deleted_at": msg["deleted_at"].isoformat() + "Z" if msg.get("deleted_at") else None,
                "is_deleted": True
            })
        
        return {
            "success": True,
            "deleted_messages": deleted_messages
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error getting deleted messages: {str(e)}")

@router.get("/chat-accounts")
async def get_chat_accounts(
    user_id: str = Query(...),
    skip: int = Query(0),
    limit: int = Query(10)
):
    user_obj_id = ObjectId(user_id)

    # Танҳо паёмҳои ҳазфнашуда
    messages = list(
        messages_collection.find({
            "$and": [
                {
                    "$or": [
                        {"from_user_id": user_obj_id},
                        {"to_user_id": user_obj_id}
                    ]
                },
                {"is_deleted": {"$ne": True}}
            ]
        }).sort("created_at", -1)
    )

    last_message_times = {}

    for msg in messages:
        contact_id = (
            msg["to_user_id"]
            if msg["from_user_id"] == user_obj_id
            else msg["from_user_id"]
        )

        if (
            contact_id not in last_message_times
            or msg["created_at"] >
            last_message_times[contact_id]["created_at"]
        ):
            message_type = msg.get("message_type", "text")
            message_preview = ""

            if message_type == "text":
                try:
                    decrypted_text = fernet.decrypt(
                        msg["message"].encode()
                    ).decode()

                    message_preview = (
                        decrypted_text[:50] + "..."
                        if len(decrypted_text) > 50
                        else decrypted_text
                    )
                except Exception:
                    raw_message = msg.get("message", "")
                    message_preview = (
                        raw_message[:50] + "..."
                        if len(raw_message) > 50
                        else raw_message
                    )

            elif message_type == "voice":
                message_preview = "🎤 Voice message"

            last_message_times[contact_id] = {
                "created_at": msg["created_at"],
                "message": message_preview,
                "message_type": message_type,
                "voice_duration": (
                    msg.get("voice_duration", 0)
                    if message_type == "voice"
                    else None
                )
            }

    sorted_contact_ids = sorted(
        last_message_times.items(),
        key=lambda x: x[1]["created_at"],
        reverse=True
    )

    paginated_contacts = sorted_contact_ids[skip:skip + limit]

    contacts = []

    for contact_id, msg_info in paginated_contacts:
        user = users_collection.find_one({"_id": contact_id})

        if not user:
            continue

        # unread count
        count_unread = messages_collection.count_documents({
            "from_user_id": contact_id,
            "to_user_id": user_obj_id,
            "is_read": False,
            "is_deleted": {"$ne": True}
        })

        # АГАР АККАУНТ БАНШУДА БОШАД 👇
        is_banned = user.get("Banned", False)

        if is_banned:
            contacts.append({
                "user_id": str(user["_id"]),
                "username": "Banned Account",
                "display_name": "",
                "avatar": "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Wn8K6sAAAAASUVORK5CYII=",
                "is_banned": True
            })
            continue

        # display decrypt
        decrypted_display = user.get("Display", "")
        try:
            decrypted_display = fernet.decrypt(
                decrypted_display.encode()
            ).decode()
        except Exception:
            pass

        # avatar
        avatar_base64 = ""
        profile_image_id = user.get("ProfileImageId")

        if profile_image_id:
            try:
                file_avatar = users_fs.get(
                    ObjectId(profile_image_id)
                )
                avatar_base64 = base64.b64encode(
                    file_avatar.read()
                ).decode("utf-8")
            except Exception:
                avatar_base64 = ""

        contacts.append({
            "user_id": str(user["_id"]),
            "username": user.get("Username"),
            "display_name": decrypted_display,
            "avatar": f"data:image/jpeg;base64,{avatar_base64}",
            "last_message": msg_info["message"],
            "last_message_time": msg_info["created_at"].isoformat(),
            "last_message_type": msg_info["message_type"],
            "last_voice_duration": msg_info.get("voice_duration"),
            "count_unread": count_unread,
            "is_banned": False
        })

    return {
        "success": True,
        "contacts": contacts
    }

class EditMessageRequest(BaseModel):
    user_id: str
    message_id: str
    text: str

@router.post("/edit-message")
async def edit_message(request: EditMessageRequest):
    try:
        if not ObjectId.is_valid(request.user_id) or not ObjectId.is_valid(request.message_id):
            raise HTTPException(status_code=400, detail="Invalid user_id or message_id format")

        message = messages_collection.find_one({"_id": ObjectId(request.message_id)})
        if not message:
            raise HTTPException(status_code=404, detail="Message not found")
        
        # Санҷидани он, ки паём ҳазф нашудааст
        if message.get("is_deleted", False):
            raise HTTPException(status_code=400, detail="Cannot edit deleted message")
            
        # Санҷидани он, ки паём матнӣ аст
        if message.get("message_type", "text") != "text":
            raise HTTPException(status_code=400, detail="Can only edit text messages")

        if str(message["from_user_id"]) != request.user_id:
            raise HTTPException(status_code=403, detail="You are not authorized to edit this message")

        encrypted_text = encrypt_data(request.text, ENCRYPTION_KEY)
        edited_at = datetime.now(timezone.utc)

        messages_collection.update_one(
            {"_id": ObjectId(request.message_id)},
            {
                "$set": {
                    "message": encrypted_text,
                    "is_edited": True,
                    "edited_at": edited_at
                }
            }
        )

        user_data = users_collection.find_one({"_id": ObjectId(request.user_id)})
        if not user_data:
            raise HTTPException(status_code=404, detail="User not found")
        decrypted_display = decrypt_data(user_data.get('Display', ''), ENCRYPTION_KEY) if user_data.get('Display') else ''

        message_payload = {
            "type": "edit_messanger",
            "value": {
                'from_user_id': str(message["from_user_id"]),
                'to_user_id': str(message["to_user_id"]),
                'username': user_data['Username'],
                'display': decrypted_display,
                'message': request.text,
                'created_at': message["created_at"].isoformat(),
                'message_id': str(message["_id"]),
                'is_edited': True,
                'edited_at': edited_at.isoformat(),
                'is_deleted': False,
            },
        }
        await manager_chat.broadcast(str(message["from_user_id"]), message_payload)
        await manager_chat.broadcast(str(message["to_user_id"]), message_payload)

        return {"success": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

class DeleteMessageRequest(BaseModel):
    user_id: str
    message_id: str

@router.post("/delete-message")
async def delete_message(request: DeleteMessageRequest):
    if not ObjectId.is_valid(request.user_id) or not ObjectId.is_valid(request.message_id):
        raise HTTPException(status_code=400, detail="Invalid user_id or message_id format")

    message = messages_collection.find_one({"_id": ObjectId(request.message_id)})
    if not message:
        raise HTTPException(status_code=404, detail="Message not found")
    
    # Санҷидани он, ки паём аллакай ҳазф нашудааст
    if message.get("is_deleted", False):
        raise HTTPException(status_code=400, detail="Message already deleted")

    # Ба ҷои ҳазф, is_deleted = True мекунем
    deleted_at = datetime.now(timezone.utc)
    messages_collection.update_one(
        {"_id": ObjectId(request.message_id)},
        {
            "$set": {
                "is_deleted": True,
                "deleted_by": ObjectId(request.user_id),
                "deleted_at": deleted_at
            }
        }
    )

    # Дарёфти ҳамаи паёмҳое, ки ба ин паём ҷавоб додаанд
    replied_messages = list(messages_collection.find({
        "reply_to_message_id": ObjectId(request.message_id),
        "is_deleted": {"$ne": True}
    }))

    user_data = users_collection.find_one({"_id": ObjectId(request.user_id)})
    if not user_data:
        raise HTTPException(status_code=404, detail="User not found")

    from_user_data = users_collection.find_one({"_id": message["from_user_id"]})
    if not from_user_data:
        raise HTTPException(status_code=404, detail="User not found")
    
    decrypted_display = from_user_data.get('Display', '')
    try:
        decrypted_display = fernet.decrypt(decrypted_display.encode()).decode()
    except Exception:
        pass

    # Фиристодани паёми ҳазф барои паёми аслӣ
    message_payload = {
        "type": "delete_messanger",
        "value": {
            'from_user_id': str(message["from_user_id"]),
            'to_user_id': str(message["to_user_id"]),
            'username': from_user_data['Username'],
            'display': decrypted_display,
            'message_id': str(message["_id"]),
            'created_at': message["created_at"].isoformat(),
            "is_deleted": True,
            "deleted_by": request.user_id,
            "deleted_at": deleted_at.isoformat()
        },
    }
    await manager_chat.broadcast(str(message["from_user_id"]), message_payload)
    await manager_chat.broadcast(str(message["to_user_id"]), message_payload)

    # Барои ҳар як паёми ҷавоб, навсозии reply_to
    for reply_msg in replied_messages:
        # Маълумоти нав барои reply_to (паёми ҳазфшуда)
        updated_reply_info = {
            "message_id": str(message["_id"]),
            "text": "[Deleted message]",
            "from_username": from_user_data['Username'],
            "from_user_id": str(message["from_user_id"]),
            "message_type": message.get("message_type", "text"),
            "is_deleted": True
        }
        
        # Фиристодани паёми навсозӣ барои ҳарду корбар
        update_payload = {
            "type": "update_reply_info",
            "value": {
                "message_id": str(reply_msg["_id"]),
                "reply_to": updated_reply_info
            }
        }
        
        await manager_chat.broadcast(str(reply_msg["from_user_id"]), update_payload)
        await manager_chat.broadcast(str(reply_msg["to_user_id"]), update_payload)

    return {"success": True}

@router.post("/delete-full-chat")
async def delete_full_chat(user_id: str = Body(...), target_user_id: str = Body(...)):
    if not ObjectId.is_valid(user_id) or not ObjectId.is_valid(target_user_id):
        raise HTTPException(status_code=400, detail="Invalid user_id or target_user_id format")

    user_obj_id = ObjectId(user_id)
    target_obj_id = ObjectId(target_user_id)

    # Ҳамаи паёмҳои байни ин ду корбарро ёфтан (танҳо ҳазфнашуда)
    messages = list(messages_collection.find({
        "$and": [
            {
                "$or": [
                    {"from_user_id": user_obj_id, "to_user_id": target_obj_id},
                    {"from_user_id": target_obj_id, "to_user_id": user_obj_id}
                ]
            },
            {"is_deleted": {"$ne": True}}
        ]
    }))

    message_ids = [str(msg["_id"]) for msg in messages]

    if not message_ids:
        return {"success": True, "message": "No messages to delete", "deleted_count": 0}

    deleted_at = datetime.now(timezone.utc)
    
    # Ба ҷои ҳазф, is_deleted = True мекунем барои ҳамаи паёмҳо
    result = messages_collection.update_many(
        {
            "$or": [
                {"from_user_id": user_obj_id, "to_user_id": target_obj_id},
                {"from_user_id": target_obj_id, "to_user_id": user_obj_id}
            ]
        },
        {
            "$set": {
                "is_deleted": True,
                "deleted_by": user_obj_id,
                "deleted_at": deleted_at
            }
        }
    )

    # Фиристодани огоҳинома тавассути WebSocket ба ҳарду корбар
    # барои user_id
    payload_user = {
        "type": "chat_deleted",
        "value": {
            "chat_with": target_user_id,
            "message_ids": message_ids,
            "deleted_at": deleted_at.isoformat()
        }
    }

    # барои target_user_id
    payload_target = {
        "type": "chat_deleted",
        "value": {
            "chat_with": user_id,
            "message_ids": message_ids,
            "deleted_at": deleted_at.isoformat()
        }
    }

    await manager_chat.broadcast(user_id, payload_user)
    await manager_chat.broadcast(target_user_id, payload_target)

    return {
        "success": True,
        "deleted_count": result.modified_count,
        "message": f"{result.modified_count} messages marked as deleted successfully"
    }

@router.post("/messages/mark_as_read")
async def mark_messages_as_read(message_ids: List[str]):
    object_ids = [ObjectId(nid) for nid in message_ids if ObjectId.is_valid(nid)]
    if not object_ids:
        return {"message": "No valid message IDs provided"}

    # Update messages as read (танҳо паёмҳои ҳазфнашуда)
    result = messages_collection.update_many(
        {
            "_id": {"$in": object_ids},
            "is_deleted": {"$ne": True}
        },
        {"$set": {"is_read": True}}
    )

    # Send WebSocket messages for messages being read
    for message_id in message_ids:
        if ObjectId.is_valid(message_id):
            message = messages_collection.find_one({"_id": ObjectId(message_id)})
            if message and not message.get("is_deleted", False):
                # Send message to sender (that their message was read)
                message_payload = {
                    "type": "message_read",
                    "value": {
                        "message_id": message_id,
                        "from_user_id": str(message["to_user_id"]),  # This user read it
                        "to_user_id": str(message["from_user_id"]),  # Sender
                        "is_read": True
                    }
                }
                await manager_chat.broadcast(str(message["from_user_id"]), message_payload)

    return {
        "message": "messages marked as read",
        "modified_count": result.modified_count
    }

@router.get("/get-unread-messages")
async def get_unread_messages(from_user_id: str, to_user_id: str, is_read: bool = False):
    try:
        if not ObjectId.is_valid(from_user_id) or not ObjectId.is_valid(to_user_id):
            raise HTTPException(status_code=400, detail="Invalid user ID format")

        messages = messages_collection.find({
            "from_user_id": ObjectId(from_user_id),
            "to_user_id": ObjectId(to_user_id),
            "is_read": is_read,
            "is_deleted": {"$ne": True}
        })

        message_list = []
        for message in messages:
            message_type = message.get("message_type", "text")
            
            if message_type == "text":
                try:
                    decrypted_text = fernet.decrypt(message["message"].encode()).decode()
                except Exception:
                    decrypted_text = message.get("message", "")
            else:
                decrypted_text = None

            message_list.append({
                "message_id": str(message["_id"]),
                "text": decrypted_text,
                "from_user_id": str(message["from_user_id"]),
                "to_user_id": str(message["to_user_id"]),
                "created_at": message["created_at"].isoformat(),
                "is_read": message.get("is_read", False),
                "message_type": message_type,
                "voice_duration": message.get("voice_duration") if message_type == "voice" else None
            })

        return {"success": True, "messages": message_list}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error getting unread messages: {str(e)}")

@router.get("/number-of-unread-messages")
async def get_unread_count(to_user_id: str, from_user_id: str):
    try:
        to_user_id = ObjectId(to_user_id)
        from_user_id = ObjectId(from_user_id)
        count = messages_collection.count_documents({
            "from_user_id": from_user_id, 
            "to_user_id": to_user_id, 
            "is_read": False,
            "is_deleted": {"$ne": True}
        })
        return {"unread_count": count}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching unread count: {str(e)}")

@router.get("/get-unread-messages-preview")
async def get_unread_messages_preview(to_user_id: str, limit: int = 30):
    try:
        if not ObjectId.is_valid(to_user_id):
            raise HTTPException(status_code=400, detail="Invalid user ID format")

        # Get unread messages (танҳо ҳазфнашуда)
        messages = messages_collection.find({
            "to_user_id": ObjectId(to_user_id),
            "is_read": False,
            "is_deleted": {"$ne": True}
        }).sort("created_at", -1).limit(limit)

        message_list = []
        for message in messages:
            message_type = message.get("message_type", "text")
            
            if message_type == "text":
                try:
                    decrypted_text = fernet.decrypt(message["message"].encode()).decode()
                except Exception:
                    decrypted_text = message.get("message", "")
            else:
                decrypted_text = "[Voice message]"

            # Get sender user information
            from_user = users_collection.find_one({"_id": message["from_user_id"]})

            profile_image_id = from_user.get("ProfileImageId")
            avatar_base64 = ''
            if profile_image_id:
                try:
                    file_avatar = users_fs.get(ObjectId(profile_image_id))
                    avatar_base64 = base64.b64encode(file_avatar.read()).decode('utf-8')
                except Exception as e:
                    avatar_base64 = ''

            username = from_user.get("Username", "Unknown") if from_user else "Unknown"

            try:
                display_name = fernet.decrypt(from_user.get("Display", "").encode()).decode() if from_user and from_user.get("Display") else ""
            except Exception:
                display_name = from_user.get("Display", "") if from_user else ""

            message_list.append({
                "message_id": str(message["_id"]),
                "message_text": decrypted_text,
                "from_user_id": str(message["from_user_id"]),
                "from_display_name": display_name,
                "created_at": message["created_at"].isoformat(),
                "is_read": message.get("is_read", False),
                "from_username": username,
                "from_user_avatar": f"data:image/jpeg;base64,{avatar_base64}",
                "message_type": message_type,
                "voice_duration": message.get("voice_duration") if message_type == "voice" else None
            })

        return {"success": True, "messages": message_list}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error getting unread messages preview: {str(e)}")

@router.get("/user-status/{user_id}")
async def get_user_status(user_id: str):
    """API барои гирифтани статуси корбар"""
    # Санҷидани дуруст будани ID
    if not ObjectId.is_valid(user_id):
        raise HTTPException(status_code=400, detail="Invalid user ID format")
    
    # Гирифтани статус аз менедҷери статус
    status = await status_manager.get_user_status(user_id)
    
    # Илова кардани маълумоти корбар барои намоиш
    user = users_collection.find_one({"_id": ObjectId(user_id)})
    if user:
        status["username"] = user.get("Username", "")
        try:
            status["display_name"] = fernet.decrypt(user.get("Display", "").encode()).decode() if user.get("Display") else ""
        except:
            status["display_name"] = user.get("Display", "")
    
    return status

@router.post("/user-status/multiple")
async def get_multiple_users_status(user_ids: List[str]):
    """API барои гирифтани статуси якчанд корбар"""
    # Фильтр кардани ID-ҳои нодуруст
    valid_ids = [uid for uid in user_ids if ObjectId.is_valid(uid)]
    
    # Гирифтани статусҳо
    statuses = await status_manager.get_multiple_users_status(valid_ids)
    
    # Илова кардани маълумоти корбарон
    result = {}
    for uid in valid_ids:
        if uid in statuses:
            result[uid] = statuses[uid]
            # Илова кардани маълумоти корбар
            user = users_collection.find_one({"_id": ObjectId(uid)})
            if user:
                result[uid]["username"] = user.get("Username", "")
                try:
                    result[uid]["display_name"] = fernet.decrypt(user.get("Display", "").encode()).decode() if user.get("Display") else ""
                except:
                    result[uid]["display_name"] = user.get("Display", "")
    
    return result

@router.post("/get-message-replies")
async def get_message_replies(message_ids: List[str] = Body(..., embed=True)):
    """
    Гирифтани ҳамаи паёмҳое, ки ба паёмҳои додашуда ҷавоб додаанд
    """
    # Фильтр кардани ID-ҳои нодуруст
    valid_ids = []
    for msg_id in message_ids:
        if ObjectId.is_valid(msg_id):
            valid_ids.append(ObjectId(msg_id))
    
    if not valid_ids:
        return {
            "success": True,
            "replies": []
        }
    
    # Ҷустуҷӯи паёмҳое, ки reply_to_message_id-и онҳо дар valid_ids аст
    replies_cursor = messages_collection.find({
        "reply_to_message_id": {"$in": valid_ids},
        "is_deleted": {"$ne": True}  # Танҳо паёмҳои ҳазфнашуда
    }).sort("created_at", 1)  # Аз қадимтарин ба навтарин
    
    replies = []
    reply_map = {}  # Барои гурӯҳбандӣ аз рӯи message_id-и аслӣ
    
    for reply in replies_cursor:
        reply_to_id = str(reply["reply_to_message_id"])
        
        # Маълумоти фиристанда
        from_user = users_collection.find_one({"_id": reply["from_user_id"]})
        from_username = from_user.get("Username", "Unknown") if from_user else "Unknown"
        
        from_display_name = ""
        if from_user and from_user.get("Display"):
            try:
                from_display_name = fernet.decrypt(from_user["Display"].encode()).decode()
            except Exception:
                from_display_name = from_user.get("Display", "")
        
        # Гирифтани аватар
        avatar_base64 = ""
        if from_user and from_user.get("ProfileImageId"):
            try:
                file_avatar = users_fs.get(ObjectId(from_user["ProfileImageId"]))
                avatar_base64 = base64.b64encode(file_avatar.read()).decode('utf-8')
            except Exception:
                pass
        
        # Матни паём (агар матнӣ бошад)
        message_text = None
        message_type = reply.get("message_type", "text")
        
        if message_type == "text" and not reply.get("is_deleted", False):
            try:
                message_text = fernet.decrypt(reply["message"].encode()).decode()
            except Exception:
                message_text = reply.get("message", "")
        elif message_type == "voice":
            message_preview = "🎤 Voice message"
        
        reply_data = {
            "message_id": str(reply["_id"]),
            "from_user_id": str(reply["from_user_id"]),
            "to_user_id": str(reply["to_user_id"]),
            "from_username": from_username,
            "from_display_name": from_display_name,
            "from_avatar": f"data:image/jpeg;base64,{avatar_base64}" if avatar_base64 else "",
            "message_type": message_type,
            "text": message_text,
            "voice_duration": reply.get("voice_duration") if message_type == "voice" else None,
            "created_at": reply["created_at"].isoformat() + "Z",
            "is_edited": reply.get("is_edited", False),
            "is_read": reply.get("is_read", False),
            "reply_to_message_id": reply_to_id
        }
        
        # Гурӯҳбандӣ аз рӯи паёми аслӣ
        if reply_to_id not in reply_map:
            reply_map[reply_to_id] = []
        reply_map[reply_to_id].append(reply_data)
        
        replies.append(reply_data)
    
    # Инчунин маълумотро дар бораи худи паёмҳои аслӣ мегирем
    original_messages_data = {}
    for msg_id in valid_ids:
        original_msg = messages_collection.find_one({"_id": msg_id})
        if original_msg:
            # Маълумоти фиристандаи паёми аслӣ
            original_from_user = users_collection.find_one({"_id": original_msg["from_user_id"]})
            original_username = original_from_user.get("Username", "Unknown") if original_from_user else "Unknown"
            
            original_text = None
            if original_msg.get("message_type") == "text" and not original_msg.get("is_deleted", False):
                try:
                    original_text = fernet.decrypt(original_msg["message"].encode()).decode()
                except Exception:
                    original_text = original_msg.get("message", "")
            elif original_msg.get("message_type") == "voice":
                original_text = "[Voice message]"
            
            original_messages_data[str(msg_id)] = {
                "message_id": str(msg_id),
                "from_user_id": str(original_msg["from_user_id"]),
                "from_username": original_username,
                "message_type": original_msg.get("message_type", "text"),
                "text": original_text,
                "is_deleted": original_msg.get("is_deleted", False),
                "created_at": original_msg["created_at"].isoformat() + "Z" if original_msg.get("created_at") else None
            }
    
    return {
        "success": True,
        "replies": replies,
        "replies_by_message": reply_map,  # Гурӯҳбандӣ аз рӯи паёми аслӣ
        "original_messages": original_messages_data,  # Маълумоти паёмҳои аслӣ
        "total_count": len(replies)
    }
