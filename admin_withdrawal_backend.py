# backend/admin_withdrawal.py

from fastapi import APIRouter, HTTPException, Query, Body
from bson import ObjectId
import os
from cryptography.fernet import Fernet
from pydantic import BaseModel
from menu.menu import users_collection, withdrawal_requests_collection, notifications_collection, withdrawal_requests_password
import datetime
from fastapi import HTTPException
from home.home import serialize_notification, broadcast_notification
from account.account import encrypt_data
import os

ENCRYPTION_KEY = os.getenv("ENCRYPTION_KEY")
fernet = Fernet(ENCRYPTION_KEY)

router = APIRouter()

@router.get("/get-all-withdrawal-requests")
async def get_all_withdrawal_requests(
    page: int = Query(1, ge=1, description="Page number"),
    limit: int = Query(20, ge=1, le=100, description="Number of requests per page")
):
    skip = (page - 1) * limit
    
    # Гирифтани дархостҳо бо пагинация
    requests = list(withdrawal_requests_collection.find()
                    .sort("created_at", -1)
                    .skip(skip)
                    .limit(limit))
    
    # Шумораи умумии дархостҳо
    total_count = withdrawal_requests_collection.count_documents({})

    # Гирифтани маълумоти корбарон
    requests_with_user_info = []
    for req in requests:
        user = users_collection.find_one({"_id": req["user_id"]})
        username = user.get("Username", "Unknown") if user else "Unknown"

        requests_with_user_info.append({
            "id": str(req["_id"]),
            "user_id": str(req["user_id"]),
            "username": username,
            "phone_or_card": req["phone_or_card"],
            "amount": req.get('amount', ''),
            "status": req["status"],
            "created_at": req["created_at"].isoformat(),
            "updated_at": req["updated_at"].isoformat(),
            "rejection_reason": req.get("rejection_reason", None),
        })

    return {
        "requests": requests_with_user_info,
        "total_count": total_count,
        "page": page,
        "limit": limit,
        "has_more": skip + len(requests) < total_count
    }
    
@router.post("/approve-withdrawal-request/{request_id}")
async def approve_withdrawal_request(request_id: str, notification_data: dict = Body(...)):
    if not ObjectId.is_valid(request_id):
        raise HTTPException(status_code=400, detail="Invalid request ID")
    
    # Санҷидани вуҷуди дархост
    request = withdrawal_requests_collection.find_one({"_id": ObjectId(request_id)})
    if not request:
        raise HTTPException(status_code=404, detail="Request not found")
    
    if request["status"] == "completed":
        raise HTTPException(status_code=400, detail="Request already completed")
    
    # Навсозӣ кардани статус ба "completed"
    withdrawal_requests_collection.update_one(
        {"_id": ObjectId(request_id)},
        {
            "$set": {
                "status": "completed",
                "updated_at": datetime.datetime.utcnow()
            }
        }
    )
    
    # Пул аз ҳисоби корбар кам карда намешавад (аллакай дар вақти дархост кам шудааст)
    # Танҳо статус тағир меёбад

    # Сохтани огоҳӣ дар колексияи notifications
    notification = {
        "NotificationFrom": ObjectId(notification_data["NotificationFrom"]),
        "NotificationTo": ObjectId(notification_data["NotificationTo"]),
        "Message": encrypt_data(notification_data["Message"], ENCRYPTION_KEY),
        "IsRead": False,
        "UploadAt": datetime.datetime.utcnow(),
        "Type": notification_data.get("Type", "system"),
        "status": "pending"
    }

    result = notifications_collection.insert_one(notification)

    # Serialize ва фиристодани паёми WebSocket
    serialized_notification = serialize_notification(notification)
    await broadcast_notification(str(notification_data["NotificationTo"]), "add", serialized_notification)

    return {
        "status": "success",
        "message": "Дархост бомуваффақият тасдиқ шуд"
    }

@router.post("/reject-withdrawal-request/{request_id}")
async def reject_withdrawal_request(request_id: str, notification_data: dict = Body(...)):
    if not ObjectId.is_valid(request_id):
        raise HTTPException(status_code=400, detail="Invalid request ID")

    # Санҷидани вуҷуди дархост
    request = withdrawal_requests_collection.find_one({"_id": ObjectId(request_id)})
    if not request:
        raise HTTPException(status_code=404, detail="Request not found")

    # Гирифтани сабаби рад кардан аз notification_data
    rejection_reason = notification_data.get("rejection_reason", "")

    # Навсозӣ кардани статус ба "rejected" ва сабаби рад кардан
    withdrawal_requests_collection.update_one(
        {"_id": ObjectId(request_id)},
        {
            "$set": {
                "status": "rejected",
                "rejection_reason": rejection_reason,  # 🔹 Илова кардани сабаби рад кардан
                "updated_at": datetime.datetime.utcnow()
            }
        }
    )

    # Бозгардонидани пул ба ҳисоби корбар
    users_collection.update_one(
        {"_id": request["user_id"]},
        {"$inc": {"Balance": request["amount"]}}
    )

    # Сохтани огоҳӣ дар колексияи notifications
    notification = {
        "NotificationFrom": ObjectId(notification_data["NotificationFrom"]),
        "NotificationTo": ObjectId(notification_data["NotificationTo"]),
        "Message": encrypt_data(notification_data["Message"], ENCRYPTION_KEY),
        "IsRead": False,
        "UploadAt": datetime.datetime.utcnow(),
        "Type": notification_data.get("Type", "system"),
        "status": "pending"
    }

    result = notifications_collection.insert_one(notification)

    # Serialize ва фиристодани паёми WebSocket
    serialized_notification = serialize_notification(notification)
    await broadcast_notification(str(notification_data["NotificationTo"]), "add", serialized_notification)

    return {
        "status": "success",
        "message": "Дархост бомуваффақият рад шуд"
    }

@router.post("/return-withdrawal-request/{request_id}")
async def return_withdrawal_request(request_id: str):
    try:
        if not ObjectId.is_valid(request_id):
            raise HTTPException(status_code=400, detail="Invalid request ID")
        
        # Санҷидани вуҷуди дархост
        request = withdrawal_requests_collection.find_one({"_id": ObjectId(request_id)})
        if not request:
            raise HTTPException(status_code=404, detail="Request not found")
        
        if request["status"] != "rejected":
            raise HTTPException(status_code=400, detail="Only rejected requests can be returned")
        
        # Навсозӣ кардани статус ба "pending"
        withdrawal_requests_collection.update_one(
            {"_id": ObjectId(request_id)},
            {
                "$set": {
                    "status": "pending",
                    "updated_at": datetime.datetime.utcnow()
                }
            }
        )
        
        # Кам кардани пул аз ҳисоби корбар (боз)
        users_collection.update_one(
            {"_id": request["user_id"]},
            {"$inc": {"Balance": -request["amount"]}}
        )

        return {
            "status": "success",
            "message": "Дархост бомуваффақият бозгашт дода шуд"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error returning request: {str(e)}")

class AdminPaymentRequest(BaseModel):
    user_id: str
    amount: float

class AdminPaymentData(BaseModel):
    payment_request: AdminPaymentRequest
    notification_data: dict

@router.post("/admin-payment")
async def admin_payment(data: AdminPaymentData):
    payment_request = data.payment_request
    notification_data = data.notification_data

    user_id = payment_request.user_id
    amount = payment_request.amount

    if not ObjectId.is_valid(user_id):
        raise HTTPException(status_code=400, detail="Invalid user ID")

    if amount <= 0:
        raise HTTPException(status_code=400, detail="Amount must be greater than 0")

    # Санҷидани вуҷуди корбар
    user = users_collection.find_one({"_id": ObjectId(user_id)})
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # Зиёд кардани баланси корбар
    users_collection.update_one(
        {"_id": ObjectId(user_id)},
        {"$inc": {"Balance": amount}}
    )

    # Бор кардани маълумоти нав
    updated_user = users_collection.find_one({"_id": ObjectId(user_id)})

    # Сохтани огоҳӣ дар колексияи notifications
    notification = {
        "NotificationFrom": ObjectId(notification_data["NotificationFrom"]),
        "NotificationTo": ObjectId(notification_data["NotificationTo"]),
        "Message": encrypt_data(notification_data["Message"], ENCRYPTION_KEY),
        "IsRead": False,
        "UploadAt": datetime.datetime.utcnow(),
        "Type": notification_data.get("Type", "system"),
        "status": "pending"
    }

    result = notifications_collection.insert_one(notification)

    # Serialize ва фиристодани паёми WebSocket
    serialized_notification = serialize_notification(notification)
    await broadcast_notification(str(notification_data["NotificationTo"]), "add", serialized_notification)

    return {
        "status": "success",
        "message": f"Amount {amount} successfully paid to user",
        "new_balance": updated_user.get("Balance", 0),
        "username": user.get("Username", "Unknown")
    }

@router.get("/get-withdrawal-stats")
async def get_withdrawal_stats():
    """
    Гирифтани омори умумии дархостҳои гирифтани пул:
    - ҳамагӣ
    - мунтазир
    - тасдиқшуда
    - радшуда
    """
    try:
        total_requests = withdrawal_requests_collection.count_documents({})
        pending_requests = withdrawal_requests_collection.count_documents(
            {"status": "pending"}
        )
        completed_requests = withdrawal_requests_collection.count_documents(
            {"status": "completed"}
        )
        rejected_requests = withdrawal_requests_collection.count_documents(
            {"status": "rejected"}
        )
        joined_requests = withdrawal_requests_collection.count_documents(
            {"status": "join"}
        )

        return {
            "status": "success",
            "data": {
                "total": total_requests,
                "pending": pending_requests,
                "completed": completed_requests,
                "rejected": rejected_requests,
                "joined": joined_requests,
            }
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching withdrawal stats: {str(e)}")

@router.get("/search-withdrawal-requests")
async def search_withdrawal_requests(
    search_query: str = Query(..., description="Қайди ҷустуҷӯ (номи корбар, рақам, ID)"),
    status_filter: str = Query("pending", description="Филтри статус (all, pending, completed, rejected)"),
    page: int = Query(1, ge=1, description="Page number"),
    limit: int = Query(20, ge=1, le=100, description="Number of requests per page")
):
    skip = (page - 1) * limit
    
    # Сохтани шартҳои ҷустуҷӯ
    search_criteria = {
        "$or": [
            {"phone_or_card": {"$regex": search_query, "$options": "i"}},
        ]
    }
    
    # Илова кардани филтри статус
    if status_filter != "all":
        search_criteria["status"] = status_filter
    
    # Илова кардани ҷустуҷӯ барои номи корбар
    users_with_username = list(users_collection.find(
        {"Username": {"$regex": search_query, "$options": "i"}},
        {"_id": 1}
    ))
    if users_with_username:
        user_ids = [user["_id"] for user in users_with_username]
        search_criteria["$or"].append({"user_id": {"$in": user_ids}})
    
    # Илова кардани ҷустуҷӯ барои ID-и корбар
    if ObjectId.is_valid(search_query):
        search_criteria["$or"].append({"user_id": ObjectId(search_query)})
    
    # Гирифтани дархостҳо бо пагинация
    requests = list(withdrawal_requests_collection.find(search_criteria)
                    .sort("created_at", -1)
                    .skip(skip)
                    .limit(limit))
    
    # Шумораи умумии дархостҳо
    total_count = withdrawal_requests_collection.count_documents(search_criteria)
    
    # Гирифтани маълумоти корбарон
    requests_with_user_info = []
    for req in requests:
        user = users_collection.find_one({"_id": req["user_id"]})
        username = user.get("Username", "Unknown") if user else "Unknown"
        
        requests_with_user_info.append({
            "id": str(req["_id"]),
            "user_id": str(req["user_id"]),
            "username": username,
            "phone_or_card": req["phone_or_card"],
            "amount": req.get('amount', ''),
            "status": req["status"],
            "created_at": req["created_at"].isoformat(),
            "updated_at": req["updated_at"].isoformat() if req.get("updated_at") else None,
            "rejection_reason": req.get("rejection_reason", None),
        })
    
    return {
        "requests": requests_with_user_info,
        "total_count": total_count,
        "page": page,
        "limit": limit,
        "has_more": skip + len(requests) < total_count,
        "search_query": search_query,
        "status_filter": status_filter
    }

@router.post("/verify-admin-password")
async def verify_admin_password(password_data: dict = Body(...)):
    """
    Санҷиши дурустии рамзи маъмурӣ
    """
    try:
        input_password = password_data.get("password")
        if not input_password:
            raise HTTPException(status_code=400, detail="Password is required")

        # Гирифтани рамзи маъмурӣ аз база
        admin_password_doc = withdrawal_requests_password.find_one({})
        
        if not admin_password_doc:
            raise HTTPException(status_code=404, detail="Admin password not set. Please generate one first.")

        if input_password == admin_password_doc["password"]:
            return {
                "status": "success",
                "message": "Рамз дуруст аст",
                "authenticated": True
            }
        else:
            return {
                "status": "error",
                "message": "Рамз нодуруст аст",
                "authenticated": False
            }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error verifying admin password: {str(e)}")

# === Нав: Рад кардани дархости join (бо бозгашти пул) ===
@router.post("/reject-join-request/{request_id}")
async def reject_join_request(request_id: str, notification_data: dict = Body(...)):
    if not ObjectId.is_valid(request_id):
        raise HTTPException(status_code=400, detail="Invalid request ID")

    request = withdrawal_requests_collection.find_one({"_id": ObjectId(request_id)})
    if not request:
        raise HTTPException(status_code=404, detail="Request not found")
    if request["status"] != "join":
        raise HTTPException(status_code=400, detail="Only join requests can be rejected with this endpoint")

    rejection_reason = notification_data.get("rejection_reason", "")

    withdrawal_requests_collection.update_one(
        {"_id": ObjectId(request_id)},
        {"$set": {
            "status": "rejected",  # Боз ба join мемонад
            "rejection_reason": rejection_reason,
            "updated_at": datetime.datetime.utcnow()
        }}
    )

    amount = request.get("amount", '')

    if amount:
        # Пулро бармегардонем (чунки ҳангоми эҷоди join кам шуда буд)
        users_collection.update_one(
            {"_id": request["user_id"]},
            {"$inc": {"Balance": request["amount"]}}
        )

    # Огоҳӣ
    notification = {
        "NotificationFrom": ObjectId(notification_data["NotificationFrom"]),
        "NotificationTo": ObjectId(notification_data["NotificationTo"]),
        "Message": encrypt_data(notification_data["Message"], ENCRYPTION_KEY),
        "IsRead": False,
        "UploadAt": datetime.datetime.utcnow(),
        "Type": notification_data.get("Type", "system"),
        "status": "pending"
    }
    notifications_collection.insert_one(notification)
    serialized = serialize_notification(notification)
    await broadcast_notification(str(notification_data["NotificationTo"]), "add", serialized)

    return {"status": "success", "message": "Дархости join рад шуд ва пул баргардонида шуд"}


# === Нав: Тасдиқи дархости join бо миқдори нав ===
@router.post("/approve-join-request/{request_id}")
async def approve_join_request(request_id: str, data: dict = Body(...)):
    """
    data = {
        "approved_amount": float,
        "notification_data": { ... }
    }
    """
    if not ObjectId.is_valid(request_id):
        raise HTTPException(status_code=400, detail="Invalid request ID")

    request = withdrawal_requests_collection.find_one({"_id": ObjectId(request_id)})
    if not request:
        raise HTTPException(status_code=404, detail="Request not found")
    if request["status"] != "join":
        raise HTTPException(status_code=400, detail="Only join requests can be approved with this endpoint")

    approved_amount = float(data["approved_amount"])
    if approved_amount <= 0:
        raise HTTPException(status_code=400, detail="Approved amount must be > 0")

    # Навсозии статус ба completed
    withdrawal_requests_collection.update_one(
        {"_id": ObjectId(request_id)},
        {"$set": {
            "status": "completed",
            "updated_at": datetime.datetime.utcnow(),
            "approved_amount": approved_amount  # барои сабт
        }}
    )

    # Пулро ба корбар илова мекунем (миқдори тасдиқшуда)
    users_collection.update_one(
        {"_id": request["user_id"]},
        {"$inc": {"Balance": approved_amount}}
    )

    # Огоҳӣ
    notif_data = data["notification_data"]
    notification = {
        "NotificationFrom": ObjectId(notif_data["NotificationFrom"]),
        "NotificationTo": ObjectId(notif_data["NotificationTo"]),
        "Message": encrypt_data(notif_data["Message"], ENCRYPTION_KEY),
        "IsRead": False,
        "UploadAt": datetime.datetime.utcnow(),
        "Type": notif_data.get("Type", "system"),
        "status": "pending"
    }
    notifications_collection.insert_one(notification)
    serialized = serialize_notification(notification)
    await broadcast_notification(str(notif_data["NotificationTo"]), "add", serialized)

    return {"status": "success", "message": f"Дархости join тасдиқ шуд, {approved_amount} сомонӣ илова карда шуд"}

class WithdrawalRequest(BaseModel):
    user_id: str
    phone_or_card: str

@router.post("/create-withdrawal-request-for-add-balance")
async def create_withdrawal_request(withdrawal_request: WithdrawalRequest):
    user_id = withdrawal_request.user_id
    phone_or_card = withdrawal_request.phone_or_card

    if not ObjectId.is_valid(user_id):
        raise HTTPException(status_code=400, detail="Invalid user ID")

    # Санҷиш, оё корбар аллакай дархости фаъол дорад
    existing_request = withdrawal_requests_collection.find_one({
        "user_id": ObjectId(user_id),
        "status": {"$in": ["pending", "processing", "join"]}
    })

    if existing_request:
        raise HTTPException(
            status_code=403, 
            detail="Шумо наметавонед дар як вақт ду дархости ҳамроҳ кардани пул диҳед"
        )

    # Санҷиши баланси корбар
    user = users_collection.find_one({"_id": ObjectId(user_id)})
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # Сохтани дархости нав
    new_request = {
        "user_id": ObjectId(user_id),
        "phone_or_card": phone_or_card,
        "status": "join",  # pending, processing, completed, rejected
        "created_at": datetime.datetime.utcnow(),
        "updated_at": datetime.datetime.utcnow()
    }

    result = withdrawal_requests_collection.insert_one(new_request)

    # Бор кардани маълумоти нав
    updated_user = users_collection.find_one({"_id": ObjectId(user_id)})

    return {
        "status": "success",
        "message": "Дархости гирифтани пул бомуваффақият сохта шуд",
        "request_id": str(result.inserted_id),
        "new_balance": updated_user.get("Balance", 0)
    }
