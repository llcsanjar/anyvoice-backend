# backend/dispute/theory/theory_loader.py

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from bson import ObjectId
import os
import datetime
import base64
from fastapi import Query
from typing import List
from pydantic import BaseModel
from menu.menu import notifications_collection, users_collection, theory_collection, messages_collection, \
users_fs, theory_confirmations_collection, theory_rejections_collection, theories_save_collection, \
theory_readings_collection, theories_comment_collection, theories_comment_likes, reports_of_theory
from menu.menu import encrypt_data, decrypt_data
from datetime import timezone
from home.chat import manager_chat
from home.home import send_email

ENCRYPTION_KEY = os.getenv("ENCRYPTION_KEY")
my_email = os.getenv("MY_EMAIL")

router = APIRouter()

# Connection Manager for WebSocket
class ConnectionManager:
    def __init__(self):
        self.active_connections: dict[str, list[WebSocket]] = {}

    async def connect(self, websocket: WebSocket, theory_id: str):
        try:
            await websocket.accept()
            if theory_id not in self.active_connections:
                self.active_connections[theory_id] = []
            self.active_connections[theory_id].append(websocket)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Error in WebSocket connect: {e}")

    def disconnect(self, websocket: WebSocket, theory_id: str):
        try:
            if theory_id in self.active_connections:
                if websocket in self.active_connections[theory_id]:
                    self.active_connections[theory_id].remove(websocket)
                if not self.active_connections[theory_id]:
                    del self.active_connections[theory_id]
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Error in WebSocket disconnect: {e}")

    async def broadcast(self, theory_id: str, message: dict):
        if theory_id in self.active_connections:
            connections_to_remove = []
            for connection in self.active_connections[theory_id]:
                try:
                    await connection.send_json(message)
                except Exception as e:
                    connections_to_remove.append(connection)
            # Remove invalid connections
            for connection in connections_to_remove:
                self.disconnect(connection, theory_id)

manager_theory = ConnectionManager()

@router.websocket("/ws/updates-theory/{theory_id}")
async def websocket_updates(websocket: WebSocket, theory_id: str):
    await manager_theory.connect(websocket, theory_id)
    try:
        while True:
            # Wait for messages to keep connection alive
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager_theory.disconnect(websocket, theory_id)
    except Exception as e:
        manager_theory.disconnect(websocket, theory_id)

@router.get("/theories/{theory_id}/full")
async def get_theory_by_id(theory_id: str):
    """Get specific theory by ID"""
    theory = theory_collection.find_one({"_id": ObjectId(theory_id)})
    if not theory:
        raise HTTPException(status_code=404, detail="Theory not found")

    user_info = users_collection.find_one({'_id': ObjectId(theory["user_id"])})
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

    # Prepare data for sending
    theory_data = {
        "id": str(theory["_id"]),
        "user_id": str(theory["user_id"]),
        "username": username,
        "display": decrypted_display,
        "avatar": avatar_base64,
        "name": theory.get("name", ""),
        "definition": theory.get("definition", ""),
        "count_readings": theory.get("count_readings", 0),
        "count_confirmations": theory.get("count_confirmations", 0),
        "count_rejections": theory.get("count_rejections", 0),
        "questions": theory.get("questions", 0),
        "created_at": theory.get("created_at") if isinstance(theory.get("created_at"), str) else theory.get("created_at").isoformat() + "Z" if theory.get("created_at") else "",
        "link": theory.get("link", ""),
        "principles": theory.get("principles", []),
        "evidence": theory.get("evidence", []),
        "conclusions": theory.get("conclusions", []),
        "rejections": theory.get("rejections", []),
        "predictions": theory.get("predictions", []),
        "limitations": theory.get("limitations", []),
        "terms": theory.get("terms", []),
        "relationships": theory.get("relationships", {}),
        "additional_info": theory.get("additional_info", ""),
        "CountShare": theory.get("CountShare", 0),
        "CountComment": theory.get("CountComment", 0),
        "CountSave": theory.get("CountSave", 0),
        "advertisement_checkbox": theory.get("AdvertisementCheckbox", False),
        "advertisement_count": theory.get("AdvertisementCount", 0),
        "updated": theory.get("Updated", False),
    }

    return theory_data

@router.get("/check-status-confirmation-theory")
def get_confirmation_info(
    user_id: str = Query(..., description="User ID"),
    theory_id: str = Query(..., description="Image ID")
):
    try:
        # Validate ObjectId for user_id and theory_id
        if not ObjectId.is_valid(user_id) or not ObjectId.is_valid(theory_id):
            return False  # Return False instead of error

        # Check if image exists in theorysData
        theory_exists = theory_collection.find_one({'_id': ObjectId(theory_id)})
        if not theory_exists:
            return False  # Return False instead of error

        # Check support
        confirmation = theory_confirmations_collection.find_one({
            'UserId': ObjectId(user_id),
            'PostTheoryId': ObjectId(theory_id),
        })

        return bool(confirmation)  # Return True if support exists, False otherwise
    except Exception as e:
        return False  # Return False instead of error

@router.get("/check-status-rejection-theory")
def get_rejection_info(
    user_id: str = Query(..., description="User ID"),
    theory_id: str = Query(..., description="Image ID")
):
    try:
        # Validate ObjectId for user_id and theory_id
        if not ObjectId.is_valid(user_id) or not ObjectId.is_valid(theory_id):
            return False  # Return False instead of error

        # Check if image exists in theorysData
        theory_exists = theory_collection.find_one({'_id': ObjectId(theory_id)})
        if not theory_exists:
            return False  # Return False instead of error

        # Check support
        rejection = theory_rejections_collection.find_one({
            'UserId': ObjectId(user_id),
            'PostTheoryId': ObjectId(theory_id),
        })

        return bool(rejection)  # Return True if support exists, False otherwise
    except Exception as e:
        return False  # Return False instead of error

@router.get("/check-save-theory-status")
def check_save_status(theory_id: str, user_id: str):
    if not ObjectId.is_valid(theory_id) or not ObjectId.is_valid(user_id):
        raise HTTPException(status_code=400, detail="Invalid ID format")

    saved = theories_save_collection.find_one({
        "PostTheoryId": ObjectId(theory_id),
        "UserId": ObjectId(user_id)
    })

    return {"saved": bool(saved)}  # True or False

@router.post("/theories/{theory_id}/read/{user_id}")
async def record_theory_reading(theory_id: str, user_id: str):
    """Record theory reading by user"""
    # Check if theory exists
    theory = theory_collection.find_one({"_id": ObjectId(theory_id)})
    
    if not theory:
        raise HTTPException(status_code=404, detail="Theory not found")
    
    # Check if previous record exists
    existing_reading = theory_readings_collection.find_one({
        "user_id": ObjectId(user_id),
        "theory_id": ObjectId(theory_id)
    })
    
    if existing_reading:
        # Update existing record
        theory_readings_collection.update_one(
            {"_id": existing_reading["_id"]},
            {
                "$set": {
                    "read_at": datetime.now(timezone.utc),
                }
            }
        )
        message = "Theory reading record updated"
        # In case of update, count_readings does not change
        new_count_readings = theory.get('count_readings', 0)
    else:
        # Create new record
        reading_record = {
            "user_id": ObjectId(user_id),
            "theory_id": ObjectId(theory_id),
            "read_at": datetime.now(timezone.utc),
        }
        theory_readings_collection.insert_one(reading_record)
        message = "Theory reading record saved"

        # Increment count_readings in theory_collection
        result = theory_collection.update_one(
            {"_id": ObjectId(theory_id)}, 
            {"$inc": {"count_readings": 1}}
        )
        
        # Get new count_readings value AFTER update
        updated_theory = theory_collection.find_one({"_id": ObjectId(theory_id)})
        new_count_readings = updated_theory.get('count_readings', 1)

    # === SEND count_readings UPDATE TO FRONTEND VIA WEBSOCKET ===
    # Only send for new record
    if not existing_reading:
        await manager_theory.broadcast(
            theory_id, 
            {
                "type": "count_readings_updated",
                "theory_id": theory_id,
                "count_readings": new_count_readings,
                "updated_at": datetime.now(timezone.utc).isoformat() + "Z"
            }
        )

    return {
        "success": True, 
        "message": message,
        "count_readings": new_count_readings
    }

class TheoryRelationships(BaseModel):
    compatible: str
    opposing: str
    stronger_than: str

class TheorySectionItem(BaseModel):
    title: str
    description: str

class TheoryTerm(BaseModel):
    term: str
    definition: str

class TheoryCreateRequest(BaseModel):
    name: str
    definition: str
    principles: List[TheorySectionItem]
    evidence: List[TheorySectionItem]
    conclusions: List[TheorySectionItem]
    rejections: List[TheorySectionItem]
    predictions: List[TheorySectionItem]
    limitations: List[TheorySectionItem]
    terms: List[TheoryTerm]
    relationships: TheoryRelationships
    additional_info: str
    advertisement_checkbox: bool = False
    advertisement_count: int = 0

@router.put("/theories/{theory_id}")
async def update_theory(user_id: str, theory_id: str, theory_data: TheoryCreateRequest):
    """Update existing theory"""
    # Check if theory exists
    existing_theory = theory_collection.find_one({"_id": ObjectId(theory_id)})
    if not existing_theory:
        raise HTTPException(status_code=404, detail="Theory not found")
    
    # Prepare update data
    update_data = theory_data.dict()
    
    # Remove fields that should not be updated
    update_data.pop("user_id", None)
    update_data.pop("created_at", None)
    update_data.pop("link", None)
    update_data.pop("previous_advertisement_count", None)
    update_data.pop("previous_advertisement_checkbox", None)

    advertisement_count = float(theory_data.advertisement_count)
    advertisement_checkbox = theory_data.advertisement_checkbox
    
    # Get previous advertisement data
    previous_ad_count = existing_theory.get("AdvertisementCount", 0)
    previous_ad_checkbox = existing_theory.get("AdvertisementCheckbox", False)

    # Compare previous and new advertisement count
    if advertisement_checkbox and advertisement_count > previous_ad_count:
        # Only charge for the difference
        additional_amount = (advertisement_count - previous_ad_count) / 100
        
        from_user = users_collection.find_one({"_id": ObjectId(user_id)})

        if not from_user:
            raise HTTPException(status_code=404, detail="Source user not found")

        # Check source user balance
        from_user_balance = from_user.get("Balance", 0)
        if from_user_balance < additional_amount:
            raise HTTPException(status_code=408, detail="Insufficient balance")

        # Deduct amount from user account
        users_collection.update_one(
            {"_id": ObjectId(user_id)},
            {"$inc": {"Balance": -additional_amount}}
        )

        # Add amount to target account
        users_collection.update_one(
            {"Username": "sanjar"},
            {"$inc": {"Balance": additional_amount}}
        )
    
    # If advertisement is turned off
    elif previous_ad_checkbox and not advertisement_checkbox:
        # Here you can decide what to do
        # For example, refund or not
        pass

    update_data["AdvertisementCount"] = int(advertisement_count)
    update_data["AdvertisementCheckbox"] = advertisement_checkbox
    update_data["Updated"] = True

    # Update theory in database
    result = theory_collection.update_one(
        {"_id": ObjectId(theory_id)},
        {"$set": update_data}
    )
    
    if result.modified_count == 0:
        return {"success": False, "message": "No changes made"}

    return {
        "success": True, 
        "message": "Theory updated successfully",
        "theory_id": theory_id
    }

class ShareMessage(BaseModel):
    from_user_id: str
    to_user_id: str
    theory_id: str

@router.post("/share-theory")
async def share_theory(share: ShareMessage):
    if not ObjectId.is_valid(share.theory_id) or not ObjectId.is_valid(share.from_user_id) or not ObjectId.is_valid(share.to_user_id):
        raise HTTPException(status_code=400, detail="Invalid ObjectId")

    created_at = datetime.now(timezone.utc)

    theory_data = theory_collection.find_one({"_id": ObjectId(share.theory_id)})
    if not theory_data:
        raise HTTPException(status_code=404, detail="Theory not found")

    theory_link = f'https://www.anyvoice.world/theory/{theory_data.get("link")}'

    # ✅ INSERT MESSAGE
    result = messages_collection.insert_one({
        "from_user_id": ObjectId(share.from_user_id),
        "to_user_id": ObjectId(share.to_user_id),
        "message": theory_link,
        "theory_id": ObjectId(share.theory_id),
        "created_at": created_at,
        "is_deleted": False,
        "is_edited": False,
        "is_read": False,
        "type": "theory"
    })

    message_id = str(result.inserted_id)

    # ✅ UPDATE SHARE COUNT
    theory_collection.update_one(
        {"_id": ObjectId(share.theory_id)},
        {"$inc": {"CountShare": 1}}
    )

    updated_theory = theory_collection.find_one({"_id": ObjectId(share.theory_id)})

    await manager_theory.broadcast(str(share.theory_id), {
        "type": "share_count",
        "value": updated_theory.get("CountShare", 0),
        "theory_id": share.theory_id,
    })

    # ✅ USER DATA
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
            "message": theory_link,
            "theory_id": share.theory_id,
            "created_at": created_at.isoformat() + "Z",
            "message_id": message_id,
            "is_edited": False,
            "is_deleted": False,
            "type": "theory"
        },
    }

    await manager_chat.broadcast(str(share.from_user_id), message_payload)
    await manager_chat.broadcast(str(share.to_user_id), message_payload)

    return {"success": True, "message_id": message_id}

@router.post("/cancel-share-theory")
async def cancel_share_theory(share: ShareMessage):
    from_id = ObjectId(share.from_user_id)
    to_id = ObjectId(share.to_user_id)
    theory_id = ObjectId(share.theory_id)

    theory_data = theory_collection.find_one({"_id": theory_id})
    if not theory_data:
        raise HTTPException(status_code=404, detail="Theory not found")

    theory_link = f'https://www.anyvoice.world/theory/{theory_data.get("link")}'

    # ✅ GET NEWEST MESSAGE
    message = messages_collection.find_one(
        {
            "from_user_id": from_id,
            "to_user_id": to_id,
            "message": theory_link,
            "type": "theory",
            "is_deleted": False,
        },
        sort=[("created_at", -1)]
    )

    if not message:
        raise HTTPException(status_code=404, detail="Message not found")

    if message.get("is_deleted", False):
        raise HTTPException(status_code=400, detail="Already deleted")

    deleted_at = datetime.now(timezone.utc)

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
            "type": "theory"
        },
    }

    await manager_chat.broadcast(str(message["from_user_id"]), message_payload)
    await manager_chat.broadcast(str(message["to_user_id"]), message_payload)

    # ✅ UPDATE REPLIES
    for reply_msg in replied_messages:
        updated_reply_info = {
            "message_id": str(message["_id"]),
            "text": "[Deleted theory]",
            "from_username": user_data["Username"],
            "from_user_id": str(message["from_user_id"]),
            "message_type": "theory",
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
    theory_collection.update_one(
        {"_id": theory_id},
        {"$inc": {"CountShare": -1}}
    )

    updated_theory = theory_collection.find_one({"_id": theory_id})

    await manager_theory.broadcast(str(share.theory_id), {
        "type": "share_count",
        "value": max(0, updated_theory.get("CountShare", 0)),
        "theory_id": share.theory_id,
    })

    return {"success": True}

class DeleteTheoryRequest(BaseModel):
    user_id: str
    theory_id: str

@router.post("/delete-theory")
async def delete_theory(request: DeleteTheoryRequest):
    """
    Complete deletion of theory and all related data
    """
    # Validate ObjectId
    if not ObjectId.is_valid(request.user_id) or not ObjectId.is_valid(request.theory_id):
        raise HTTPException(status_code=400, detail="Invalid ID format")
    
    # Get theory
    theory = theory_collection.find_one({"_id": ObjectId(request.theory_id)})
    if not theory:
        raise HTTPException(status_code=404, detail="Theory not found")
    
    # Check permission (only theory owner can delete)
    if str(theory["user_id"]) != request.user_id:
        raise HTTPException(status_code=403, detail="You are not authorized to delete this theory")
    
    # 1. Collect all comment and replay IDs
    all_comment_ids = []
    
    # Get top comments
    top_comments = theories_comment_collection.find({
        "theory_id": ObjectId(request.theory_id),
        "parent_comment_id": None
    })
    
    for comment in top_comments:
        all_comment_ids.append(comment["_id"])
        
        # Get replays
        replay_comments = theories_comment_collection.find({
            "parent_comment_id": comment["_id"]
        })
        for replay in replay_comments:
            all_comment_ids.append(replay["_id"])
            
            # Get replays of replays (chain)
            def collect_nested_replays(parent_id):
                nested_replays = theories_comment_collection.find({
                    "parent_comment_id": parent_id
                })
                for nested in nested_replays:
                    all_comment_ids.append(nested["_id"])
                    collect_nested_replays(nested["_id"])
            
            collect_nested_replays(replay["_id"])
    
    # 2. Delete comments and replays
    if all_comment_ids:
        theories_comment_collection.delete_many({
            "_id": {"$in": all_comment_ids}
        })
    
    # 3. Delete comment likes
    if all_comment_ids:
        theories_comment_likes.delete_many({
            "comment_id": {"$in": all_comment_ids}
        })
    
    # 4. Delete notifications related to theory and comments
    # Notifications about theory
    notifications_collection.delete_many({
        "PostId": ObjectId(request.theory_id)
    })
    
    # Notifications about comments
    if all_comment_ids:
        notifications_collection.delete_many({
            "PostId": {"$in": all_comment_ids}
        })
    
    # 5. Delete confirmations
    theory_confirmations_collection.delete_many({
        "PostTheoryId": ObjectId(request.theory_id)
    })
    
    # 6. Delete rejections
    theory_rejections_collection.delete_many({
        "PostTheoryId": ObjectId(request.theory_id)
    })
    
    # 7. Delete saves
    theories_save_collection.delete_many({
        "PostTheoryId": ObjectId(request.theory_id)
    })
    
    # 8. Delete reading records
    theory_readings_collection.delete_many({
        "theory_id": ObjectId(request.theory_id)
    })
    
    # 9. Delete theory from main collection
    theory_collection.delete_one({"_id": ObjectId(request.theory_id)})
    
    # 10. Update user statistics
    users_collection.update_one(
        {"_id": ObjectId(request.user_id)},
        {"$inc": {"CountPosts": -1, "CountTheories": -1}}
    )
    
    # 11. Send WebSocket for deletion notification
    await manager_theory.broadcast(request.theory_id, {
        "type": "theory_deleted",
        "theory_id": request.theory_id,
        "message": "Theory deleted"
    })
    
    return {
        "success": True,
        "message": "Theory and all related data deleted successfully"
    }

@router.get("/theory-confirmation-save")
async def confirmation_theory_save(
    user_id: str = Query(..., description="User ID"),
    theory_id: str = Query(..., description="Image ID")
):
    # Check if the user has already confirmed this theory
    existing_confirmation = theory_confirmations_collection.find_one({
        'UserId': ObjectId(user_id),
        'PostTheoryId': ObjectId(theory_id)
    })

    # If they had rejected, remove the rejection
    existing_rejection = theory_rejections_collection.find_one({
        'UserId': ObjectId(user_id),
        'PostTheoryId': ObjectId(theory_id)
    })

    if existing_rejection:
        theory_rejections_collection.delete_one({
            'UserId': ObjectId(user_id),
            'PostTheoryId': ObjectId(theory_id)
        })
        theory_collection.update_one(
            {'_id': ObjectId(theory_id)},
            {'$inc': {'count_rejections': -1}}
        )

    if existing_confirmation:
        raise HTTPException(
            status_code=400,
            detail="This user has already confirmed this theory"
        )

    theory_confirmations_collection.insert_one({
        'UserId': ObjectId(user_id),
        'PostTheoryId': ObjectId(theory_id),
        "UploadAt": datetime.now(timezone.utc),
    })

    theory_collection.update_one(
        {'_id': ObjectId(theory_id)},
        {'$inc': {'count_confirmations': 1}},
    )

    # Broadcast updated confirmation count
    theory_data = theory_collection.find_one({'_id': ObjectId(theory_id)})
    await manager_theory.broadcast(theory_id, {
        "type": "confirmation_count",
        "count_rejections": theory_data.get('count_rejections', 0),
        "count_confirmations": theory_data.get('count_confirmations', 0),
        "user_id": user_id,
        "theory_id": theory_id,
        "confirmation": True,
    })

    return {"success": True}

@router.get("/theory-confirmation-delete")
async def confirmation_theory_delete(
    user_id: str = Query(..., description="User ID"),
    theory_id: str = Query(..., description="Image ID")
):
    # Check if the user has already confirmed this theory
    existing_confirmation = theory_confirmations_collection.find_one({
        'UserId': ObjectId(user_id),
        'PostTheoryId': ObjectId(theory_id)
    })

    if not existing_confirmation:
        raise HTTPException(
            status_code=400,
            detail="This user has not confirmed this theory or has already removed confirmation"
        )

    theory_confirmations_collection.delete_one({
        'UserId': ObjectId(user_id),
        'PostTheoryId': ObjectId(theory_id),
    })

    theory_collection.update_one(
        {'_id': ObjectId(theory_id)},
        {'$inc': {'count_confirmations': -1}},
    )

    # Broadcast updated confirmation count
    theory_data = theory_collection.find_one({'_id': ObjectId(theory_id)})
    await manager_theory.broadcast(theory_id, {
        "type": "confirmation_count",
        "count_rejections": theory_data.get('count_rejections', 0),
        "count_confirmations": theory_data.get('count_confirmations', 0),
        "user_id": user_id,
        "theory_id": theory_id,
        "confirmation": False,
    })

    return {"success": True}

@router.get("/theory-rejection-save")
async def rejection_theory_save(
    user_id: str = Query(..., description="User ID"),
    theory_id: str = Query(..., description="Image ID")
):
    # Check if the user has already supported this image
    existing_rejection = theory_rejections_collection.find_one({
        'UserId': ObjectId(user_id),
        'PostTheoryId': ObjectId(theory_id)
    })

    # If they had confirmed, remove the confirmation
    existing_confirmation = theory_confirmations_collection.find_one({
        'UserId': ObjectId(user_id),
        'PostTheoryId': ObjectId(theory_id)
    })

    if existing_confirmation:
        theory_confirmations_collection.delete_one({
            'UserId': ObjectId(user_id),
            'PostTheoryId': ObjectId(theory_id)
        })
        theory_collection.update_one(
            {'_id': ObjectId(theory_id)},
            {'$inc': {'count_confirmations': -1}}
        )

    if existing_rejection:
        raise HTTPException(
            status_code=400,
            detail="This user has already rejected this theory"
        )

    theory_rejections_collection.insert_one({
        'UserId': ObjectId(user_id),
        'PostTheoryId': ObjectId(theory_id),
        "UploadAt": datetime.now(timezone.utc),
    })

    theory_collection.update_one(
        {'_id': ObjectId(theory_id)},
        {'$inc': {'count_rejections': 1}},
    )

    # Broadcast updated rejection count
    theory_data = theory_collection.find_one({'_id': ObjectId(theory_id)})
    await manager_theory.broadcast(theory_id, {
        "type": "rejection_count",
        "count_rejections": theory_data.get('count_rejections', 0),
        "count_confirmations": theory_data.get('count_confirmations', 0),
        "user_id": user_id,
        "theory_id": theory_id,
        "rejection": True,
    })

    return {"success": True}

@router.get("/theory-rejection-delete")
async def rejection_theory_delete(
    user_id: str = Query(..., description="User ID"),
    theory_id: str = Query(..., description="Image ID")
):
    # Check if the user has already supported this image
    existing_rejection = theory_rejections_collection.find_one({
        'UserId': ObjectId(user_id),
        'PostTheoryId': ObjectId(theory_id)
    })

    if not existing_rejection:
        raise HTTPException(
            status_code=400,
            detail="This user has not rejected this theory or has already removed rejection"
        )

    theory_rejections_collection.delete_one({
        'UserId': ObjectId(user_id),
        'PostTheoryId': ObjectId(theory_id),
    })

    theory_collection.update_one(
        {'_id': ObjectId(theory_id)},
        {'$inc': {'count_rejections': -1}},
    )

    # Broadcast updated rejection count
    theory_data = theory_collection.find_one({'_id': ObjectId(theory_id)})
    await manager_theory.broadcast(theory_id, {
        "type": "rejection_count",
        "count_rejections": theory_data.get('count_rejections', 0),
        "count_confirmations": theory_data.get('count_confirmations', 0),
        "user_id": user_id,
        "theory_id": theory_id,
        "rejection": False,
    })

    return {"success": True}

@router.get("/save-theory")
async def save_theory(user_id: str, theory_id: str):
    saved = theories_save_collection.find_one({
        "UserId": ObjectId(user_id),
        "PostTheoryId": ObjectId(theory_id)
    })
    if saved:
        theories_save_collection.delete_one({
            "UserId": ObjectId(user_id),
            "PostTheoryId": ObjectId(theory_id)
        })
        theory_collection.update_one(
            {"_id": ObjectId(theory_id)},
            {"$inc": {"CountSave": -1}}
        )
        await manager_theory.broadcast(theory_id, {
            "type": "save_count",
            "value": theory_collection.find_one({"_id": ObjectId(theory_id)}).get("CountSave", 0),
            "user_id": user_id,
            "theory_id": theory_id,
            "saved": not bool(saved)
        })
        return {"saved": False}
    else:
        theories_save_collection.insert_one({
            "UserId": ObjectId(user_id),
            "PostTheoryId": ObjectId(theory_id),
            "SavedAt": datetime.now(timezone.utc)
        })
        theory_collection.update_one(
            {"_id": ObjectId(theory_id)},
            {"$inc": {"CountSave": 1}}
        )
        await manager_theory.broadcast(theory_id, {
            "type": "save_count",
            "value": theory_collection.find_one({"_id": ObjectId(theory_id)}).get("CountSave", 0),
            "user_id": user_id,
            "theory_id": theory_id,
            "saved": not bool(saved)
        })
        return {"saved": True}

class TheoryReportRequest(BaseModel):
    user_id: str
    theory_id: str
    reason: str

@router.post("/report-theory")
async def report_theory(request: TheoryReportRequest):
    # Validate ObjectId
    if not ObjectId.is_valid(request.user_id) or not ObjectId.is_valid(request.theory_id):
        raise HTTPException(status_code=400, detail="Invalid user_id or theory_id format")

    # Check if comment exists
    theory = theory_collection.find_one({"_id": ObjectId(request.theory_id)})
    if not theory:
        raise HTTPException(status_code=404, detail="theory not found")

    # Check if user exists
    user = users_collection.find_one({"_id": ObjectId(request.user_id)})
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # Check for duplicate report
    existing_report = reports_of_theory.find_one({
        "user_id": ObjectId(request.user_id),
        "theory_id": ObjectId(request.theory_id)
    })
    if existing_report:
        raise HTTPException(status_code=401, detail="You have already reported this theory")

    # Encrypt reason
    encrypted_reason = encrypt_data(request.reason, ENCRYPTION_KEY)

    # Save report in TheoryReports table
    report_data = {
        "user_id": ObjectId(request.user_id),
        "theory_id": ObjectId(request.theory_id),
        "reason": encrypted_reason,
        "created_at": datetime.now(timezone.utc)
    }
    reports_of_theory.insert_one(report_data)

    send_email(
        recipient=my_email,
        message=f"""Шикоят аз назарияи https://www.anyvoice.world/theory/{theory["Link"]}.\n
        Шикоят кунанда: @{user['Username']}\n
        Сабаб: {request.reason}\n""",
        subject='Шикоят⚠️'
    )

    return {"success": True}
