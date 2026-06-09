# backend/home/home.py

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from cryptography.fernet import Fernet
from bson import ObjectId
from bson.errors import InvalidId
import os
import datetime
import random
import base64
from fastapi import Query
import json
from typing import List
from typing import Optional
from pydantic import BaseModel
from menu.menu import notifications_collection, images_collection, users_collection, \
followers_collection, videos_collection, products_collection, shopings_collection, \
viewed_ads_collection, theory_collection, physical_product_purchases_collection, products_buy_collection, \
articles_collection, messages_collection
import requests
from menu.menu import encrypt_data, decrypt_data

ENCRYPTION_KEY = os.getenv("ENCRYPTION_KEY")

router = APIRouter()

# WebSocket connection manager for users
connected_clients = {}

def send_email(recipient, message, subject="Sanjar"):
    api_key = os.getenv("BREVO_API_KEY")

    url = "https://api.brevo.com/v3/smtp/email"

    headers = {
        "accept": "application/json",
        "api-key": api_key,
        "content-type": "application/json"
    }

    payload = {
        "sender": {
            "name": "Sanjar",
            "email": "noreply@anyvoice.world"
        },
        "to": [
            {"email": recipient}
        ],
        "subject": subject,
        "htmlContent": f"<p>{message}</p>"
    }

    response = requests.post(url, json=payload, headers=headers)

    print(response.status_code)
    print(response.text)

    if response.status_code not in [200, 201]:
        raise Exception(f"Brevo error: {response.text}")

def serialize_notification(notification):
    notification_dict = dict(notification)
    for key, value in notification_dict.items():
        if isinstance(value, ObjectId):
            notification_dict[key] = str(value)
        elif isinstance(value, datetime.datetime):
            notification_dict[key] = value.isoformat()

    if 'Message' in notification_dict and notification_dict['Message']:
        try:
            notification_dict['Message'] = decrypt_data(notification_dict['Message'], ENCRYPTION_KEY)
        except ValueError as e:
            notification_dict['Message'] = f"Error decrypting message: {str(e)}"

    if 'Type' in notification_dict and notification_dict['Type']:
        try:
            notification_dict['DecryptedType'] = decrypt_data(notification_dict['Type'], ENCRYPTION_KEY)
        except ValueError as e:
            notification_dict['DecryptedType'] = f"Error decrypting type: {str(e)}"

    return notification_dict

async def broadcast_notification(user_id: str, action: str, notification: dict = None):
    """Send notification update to specific user via WebSocket."""
    if user_id in connected_clients:
        for ws in connected_clients[user_id]:
            try:
                await ws.send_json({"action": action, "notification": notification})
            except Exception as e:
                raise HTTPException(status_code=400, detail=f"Error broadcasting to {user_id}: {str(e)}")

@router.websocket("/ws/notifications/{user_id}")
async def websocket_notifications(websocket: WebSocket, user_id: str):
    await websocket.accept()
    try:
        # Add WebSocket to user's connection list
        if user_id not in connected_clients:
            connected_clients[user_id] = []
        connected_clients[user_id].append(websocket)

        # Send existing notifications to user
        try:
            user_object_id = ObjectId(user_id)
            notifications = list(notifications_collection.find({"NotificationTo": user_object_id}).sort("UploadAt", -1))
            serialized_notifications = [serialize_notification(notification) for notification in notifications]
            await websocket.send_json({"action": "initial", "notifications": serialized_notifications})
        except InvalidId:
            await websocket.send_json({"action": "error", "message": "Invalid user ID format"})
            return

        while True:
            # Wait for incoming messages (to manage connection termination)
            await websocket.receive_text()

    except WebSocketDisconnect:
        if user_id in connected_clients and websocket in connected_clients[user_id]:
            connected_clients[user_id].remove(websocket)
            if not connected_clients[user_id]:
                del connected_clients[user_id]
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"WebSocket error for {user_id}: {str(e)}")
    finally:
        if user_id in connected_clients and websocket in connected_clients[user_id]:
            connected_clients[user_id].remove(websocket)
            if not connected_clients[user_id]:
                del connected_clients[user_id]

@router.get("/notifications/{user_id}")
async def get_notifications(
    user_id: str,
    limit: int = Query(10, ge=1),
    skip: int = Query(0, ge=0)
):
    user_object_id = ObjectId(user_id)
    notifications = list(
        notifications_collection
        .find({"NotificationTo": user_object_id})
        .sort("UploadAt", -1)
        .skip(skip)
        .limit(limit)
    )
    serialized_notifications = [serialize_notification(notification) for notification in notifications]
    return serialized_notifications

@router.get("/notifications/unread_count/{user_id}")
async def get_unread_count(user_id: str):
    try:
        user_object_id = ObjectId(user_id)
        count = notifications_collection.count_documents({"NotificationTo": user_object_id, "IsRead": False})
        return {"unread_count": count}
    except InvalidId:
        raise HTTPException(status_code=400, detail="Invalid user ID format")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching unread count: {str(e)}")

@router.post("/notifications/mark_as_read")
async def mark_notifications_as_read(notification_ids: List[str]):
    try:
        object_ids = [ObjectId(nid) for nid in notification_ids if ObjectId.is_valid(nid)]
        if not object_ids:
            return {"message": "No valid notification IDs provided"}

        result = notifications_collection.update_many(
            {"_id": {"$in": object_ids}},
            {"$set": {"IsRead": True}}
        )

        return {
            "message": "Notifications marked as read",
            "modified_count": result.modified_count
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error marking notifications as read: {str(e)}")

@router.post("/notifications/{notification_id}/accept")
async def accept_notification(notification_id: str):
    # Find notification
    notification = notifications_collection.find_one({"_id": ObjectId(notification_id)})
    if not notification:
        raise HTTPException(status_code=404, detail="Notification not found")

    encrypted_type = notification.get("Type", "")
    try:
        notification_type = decrypt_data(encrypted_type, ENCRYPTION_KEY)

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to decrypt notification type: {str(e)}")

    from_user_id = notification.get("NotificationFrom")
    to_user_id = notification.get("NotificationTo")
    shoping_id = notification.get("ShopingId", "")
    post_id = notification.get("PostId")

    if shoping_id:
        shoping_data = shopings_collection.find_one({"_id": ObjectId(shoping_id)})
        shoping_id = shoping_data["_id"]
        shoping_name = shoping_data["ShopingName"]

    # Validate user
    user = users_collection.find_one({"_id": ObjectId(to_user_id)})
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # Initialize CountPosts if it doesn't exist
    if "CountPosts" not in user:
        users_collection.update_one(
            {"_id": ObjectId(to_user_id)},
            {"$set": {"CountPosts": 0}}
        )

    user_username = f'{user.get("Username", "")}'

    if notification_type == "collaboration":
        post = images_collection.find_one({"_id": ObjectId(post_id)})
        post_type = 'image'

        if not post:
            post = videos_collection.find_one({"_id": ObjectId(post_id)})
            post_type = 'video'

        if not post:
            post = products_collection.find_one({"_id": ObjectId(post_id)})
            post_type = 'product'

        if not post:
            post_type = None

            notifications_collection.delete_one({"_id": ObjectId(notification_id)})
            await broadcast_notification(str(to_user_id), "delete", {"_id": notification_id})
            raise HTTPException(status_code=404, detail="Post not found")

        # Check post visibility
        visibility = post.get("Visibility", "").lower()
        if visibility == "private":
            notifications_collection.delete_one({"_id": ObjectId(notification_id)})
            await broadcast_notification(str(to_user_id), "delete", {"_id": notification_id})
            raise HTTPException(status_code=403, detail="This post is private and cannot be collaborated on")

        # Check if user is blocked
        blocked_users = post.get("BlockUsersList", [])
        if ObjectId(to_user_id) in blocked_users:
            notifications_collection.delete_one({"_id": ObjectId(notification_id)})
            await broadcast_notification(str(to_user_id), "delete", {"_id": notification_id})
            raise HTTPException(status_code=403, detail="You are blocked from collaborating on this post")

        collaboration_accounts = post.get("CollaborationAccounts", [])
        user_collaborations = []

        if not shoping_id:
            if ObjectId(to_user_id) not in collaboration_accounts:
                is_video = images_collection.find_one({"_id": ObjectId(post_id)})

                # Add user to collaboration accounts
                if is_video:
                    result = images_collection.update_one(
                        {"_id": ObjectId(post_id)},
                        {"$push": {"CollaborationAccounts": ObjectId(to_user_id)}}
                    )

                else:
                    result = videos_collection.update_one(
                        {"_id": ObjectId(post_id)},
                        {"$push": {"CollaborationAccounts": ObjectId(to_user_id)}}
                    )

                user_collaborations = post.get("CollaborationAccounts", [])

                if post_type == 'video':
                    users_collection.update_one(
                        {"_id": ObjectId(to_user_id)},
                        {"$inc": {"CountVideos": 1}}
                    )

                elif post_type == 'image':
                    users_collection.update_one(
                        {"_id": ObjectId(to_user_id)},
                        {"$inc": {"CountImages": 1}}
                    )

                elif post_type == 'product':
                    users_collection.update_one(
                        {"_id": ObjectId(to_user_id)},
                        {"$inc": {"CountProducts": 1}}
                    )

                users_collection.update_one(
                    {"_id": ObjectId(to_user_id)},
                    {
                        "$inc": {"CountPosts": 1},
                    }
                )

                # Send notification to all followers
                followers = followers_collection.find({"target_user_id": ObjectId(to_user_id)})
                user_username = user["Username"]
                post_link = post.get("Link", "")
                encrypted_follower_message = encrypt_data(f"@{user_username} started a new collaboration. View post: https://www.anyvoice.world/{post_type}/{post_link}", ENCRYPTION_KEY)
                encrypted_follower_type = encrypt_data("new_post", ENCRYPTION_KEY)

                for follower in followers:
                    follower_id = follower["follower_id"]
                    if follower_id != ObjectId(to_user_id):  # Skip self-notification
                        notification_doc = {
                            "NotificationFrom": ObjectId(to_user_id),
                            "NotificationTo": follower_id,
                            "Message": encrypted_follower_message,
                            "PostId": post_id,
                            "IsRead": False,
                            "UploadAt": datetime.datetime.now(datetime.timezone.utc).isoformat().replace('Z', '+00:00'),
                            "Type": encrypted_follower_type,
                            "status": "pending"
                        }
                        notifications_collection.insert_one(notification_doc)
                        serialized_notification = serialize_notification(notification_doc)
                        await broadcast_notification(str(follower_id), "add", serialized_notification)

                # Send response notification to the sender
                message = f"@{user_username} accepted your collaboration request."
                if notification_type == "collaboration" and post_link:
                    message += f" View post: https://www.anyvoice.world/{post_type}/{post_link}"
                encrypted_message = encrypt_data(message, ENCRYPTION_KEY)
                encrypted_type = encrypt_data("response", ENCRYPTION_KEY)

                notification_doc = {
                    "NotificationFrom": ObjectId(to_user_id),
                    "NotificationTo": ObjectId(from_user_id),
                    "Message": encrypted_message,
                    "PostId": ObjectId(post_id) if post_id else None,
                    "IsRead": False,
                    "UploadAt": datetime.datetime.now(datetime.timezone.utc).isoformat().replace('Z', '+00:00'),
                    "Type": encrypted_type,
                    "status": "pending"
                }
                notifications_collection.insert_one(notification_doc)

                serialized_response_notification = serialize_notification(notification_doc)
                await broadcast_notification(str(from_user_id), "add", serialized_response_notification)

        else:
            collaboration_shopings = post.get("CollaborationShopings", [])
            if shoping_id not in collaboration_shopings:
                products_collection.find_one({"_id": ObjectId(post_id)})

                # Add user to collaboration accounts
                products_collection.update_one(
                    {"_id": ObjectId(post_id)},
                    {"$push": {"CollaborationShopings": ObjectId(shoping_id)}}
                )

                shopings_collection.update_one(
                    {"_id": ObjectId(shoping_id)},
                    {"$inc": {"CountProducts": 1}}
                )

                shoping_data = shopings_collection.find_one({"_id": shoping_id})

                # Send notification to all followers
                followers = followers_collection.find({"target_user_id": to_user_id})
                user_username = user["Username"]
                post_link = post.get("Link", "")
                encrypted_follower_message = encrypt_data(f"@{user_username} added a new product in shop ${shoping_name}. View product: https://www.anyvoice.world/product/{post_link}", ENCRYPTION_KEY)
                encrypted_follower_type = encrypt_data("new_post", ENCRYPTION_KEY)

                for follower in followers:
                    follower_id = follower["follower_id"]
                    notification_doc = {
                        "NotificationFrom": from_user_id,
                        "NotificationTo": follower_id,
                        "Message": encrypted_follower_message,
                        "PostId": post_id,
                        "IsRead": False,
                        "UploadAt": datetime.datetime.now(datetime.timezone.utc).isoformat().replace('Z', '+00:00'),
                        "Type": encrypted_follower_type,
                        "status": "pending"
                    }
                    notifications_collection.insert_one(notification_doc)
                    serialized_notification = serialize_notification(notification_doc)
                    await broadcast_notification(str(follower_id), "add", serialized_notification)

                # Send response notification to the sender
                message = f"@{user_username} added your product in shop ${shoping_name}. "
                if notification_type == "collaboration" and post_link:
                    message += f" View product: https://www.anyvoice.world/product/{post_link}"
                encrypted_message = encrypt_data(message, ENCRYPTION_KEY)
                encrypted_type = encrypt_data("response", ENCRYPTION_KEY)

                notification_doc = {
                    "NotificationFrom": ObjectId(to_user_id),
                    "NotificationTo": ObjectId(from_user_id),
                    "Message": encrypted_message,
                    "PostId": ObjectId(post_id) if post_id else None,
                    "IsRead": False,
                    "UploadAt": datetime.datetime.now(datetime.timezone.utc).isoformat().replace('Z', '+00:00'),
                    "Type": encrypted_type,
                    "status": "pending"
                }
                notifications_collection.insert_one(notification_doc)

                serialized_response_notification = serialize_notification(notification_doc)
                await broadcast_notification(str(from_user_id), "add", serialized_response_notification)

    # Delete the original notification
    result = notifications_collection.delete_one({"_id": ObjectId(notification_id)})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Notification not found or already deleted")

    await broadcast_notification(str(to_user_id), "delete", {"_id": notification_id})

    # Broadcast CountPosts update to the accepting user's frontend
    if notification_type == "collaboration" and post_id not in user_collaborations:
        count_posts = user.get("CountPosts", 0)
        await broadcast_notification(
            str(to_user_id),
            "update_count_posts",
            {"user_id": str(to_user_id), "count_posts": count_posts}
        )

    return {"message": "Notification accepted, deleted, and response sent to sender"}

@router.post("/notifications/{notification_id}/reject")
async def reject_notification(notification_id: str):
    try:
        notification = notifications_collection.find_one({"_id": ObjectId(notification_id)})
        if not notification:
            raise HTTPException(status_code=404, detail="Notification not found")

        from_user_id = notification.get("NotificationFrom")
        to_user_id = notification.get("NotificationTo")
        shoping_id = notification.get("ShopingId", "")
        post_id = notification.get("PostId")

        user = users_collection.find_one({"_id": ObjectId(to_user_id)})
        user_display = user.get("Username", "")

        if shoping_id:
            shoping_data = shopings_collection.find_one({"_id": ObjectId(shoping_id)})
            shoping_name = shoping_data["ShopingName"]

            message = f"@{user_display} rejected your request to add your product in shop ${shoping_name}. "
            if post_id:
                post = products_collection.find_one({"_id": ObjectId(post_id)})

                if post:
                    post_link = post.get("Link", "")
                    if post_link:
                        message += f"View product: https://www.anyvoice.world/product/{post_link}"

        else:

            message = f"@{user_display} rejected your collaboration request. "
            if post_id:
                post = images_collection.find_one({"_id": ObjectId(post_id)})

                if not post:
                    post = videos_collection.find_one({"_id": ObjectId(post_id)})

                if post:
                    post_link = post.get("Link", "")
                    if post_link:
                        message += f"View post: {post_link}"

        encrypted_message = encrypt_data(message, ENCRYPTION_KEY)
        encrypted_type = encrypt_data("response", ENCRYPTION_KEY)

        notification_doc = {
            "NotificationFrom": ObjectId(to_user_id),
            "NotificationTo": ObjectId(from_user_id),
            "Message": encrypted_message,
            "PostId": ObjectId(post_id) if post_id else None,
            "IsRead": False,
            "UploadAt": datetime.datetime.now(datetime.timezone.utc).isoformat().replace('Z', '+00:00'),
            "Type": encrypted_type,
            "status": "pending"
        }
        notifications_collection.insert_one(notification_doc)

        # Send response notification to NotificationFrom
        serialized_response_notification = serialize_notification(notification_doc)
        await broadcast_notification(str(from_user_id), "add", serialized_response_notification)

        # Delete original notification
        result = notifications_collection.delete_one({"_id": ObjectId(notification_id)})
        if result.deleted_count == 0:
            raise HTTPException(status_code=404, detail="Notification not found or already deleted")

        # Notify rejecting user about deletion
        await broadcast_notification(str(to_user_id), "delete", {"_id": notification_id})

        return {"message": "Notification rejected, deleted, and response sent to sender"}

    except InvalidId:
        raise HTTPException(status_code=400, detail="Invalid notification ID")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error rejecting notification: {str(e)}")

class VerifyQRRequest(BaseModel):
    qr_data: Optional[str] = None
    qr_image: Optional[str] = None
    user_id: str

@router.post("/verify-physical-product-qr")
async def verify_physical_product_qr(request: VerifyQRRequest):
    import cv2
    import numpy as np
    qr_json = None

    if request.qr_data:
        try:
            qr_json = json.loads(request.qr_data)
        except:
            qr_json = {"raw_data": request.qr_data}

    elif request.qr_image:
        # Decode image from base64
        image_data = request.qr_image.split("base64,")[-1] if "base64," in request.qr_image else request.qr_image
        image_bytes = base64.b64decode(image_data)
        nparr = np.frombuffer(image_bytes, np.uint8)
        image = cv2.imdecode(nparr, cv2.IMREAD_COLOR)

        detector = cv2.QRCodeDetector()
        data, bbox, _ = detector.detectAndDecode(image)
        if not data:
            raise HTTPException(status_code=400, detail="No QR code found in image")
        try:
            qr_json = json.loads(data)
        except:
            qr_json = {"raw_data": data}

    else:
        raise HTTPException(status_code=400, detail="No QR data or image provided")

    if not qr_json:
        raise HTTPException(status_code=400, detail="Could not extract QR data")

    purchase_id = qr_json.get("purchase_id")
    if not purchase_id or not ObjectId.is_valid(purchase_id):
        raise HTTPException(status_code=401, detail="Invalid purchase ID")

    purchase = physical_product_purchases_collection.find_one({"_id": ObjectId(purchase_id)})
    if not purchase:
        raise HTTPException(status_code=401, detail="Purchase not found")

    # Санҷиши баланси харидор
    user = users_collection.find_one({"_id": ObjectId(purchase["user_id"])})
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    user_balance = user.get("Balance", 0)
    product_price = purchase.get("price", 0)
    if user_balance < product_price:
        raise HTTPException(status_code=402, detail="Insufficient funds")

    if purchase.get("status") == "used":
        buyer = users_collection.find_one({"_id": purchase["user_id"]})
        return {
            "success": True,
            "verified": False,
            "already_used": True,
            "purchase_data": {
                "purchase_id": str(purchase["_id"]),
                "product_name": purchase.get("product_name", ""),
                "physical_product_name": purchase.get("physical_product_name", ""),
                "purchase_date": purchase["purchase_date"].isoformat() + "Z",
                "buyer_username": buyer.get("Username") if buyer else "Unknown",
                "status": "used"
            }
        }

    product = products_collection.find_one({"_id": purchase["product_id"]})
    if not product:
        raise HTTPException(status_code=401, detail="Product not found")

    # Check if scanner is seller or buyer
    if str(product.get("UserId")) != request.user_id:
        raise HTTPException(status_code=403, detail="Only seller can verify this QR code")

    # Mark as used
    physical_product_purchases_collection.update_one(
        {"_id": ObjectId(purchase_id)},
        {
            "$set": {
                "status": "used",
                "used_at": datetime.datetime.now(datetime.timezone.utc),
                "verified_by": ObjectId(request.user_id)
            }
        }
    )

    # Сабти харид дар products_buy_collection
    products_buy_collection.insert_one({
        "UserId": ObjectId(purchase["user_id"]),
        "PostProductId": ObjectId(purchase["product_id"]),
        "BuyIn": datetime.datetime.now(datetime.timezone.utc),
        "Price": purchase.get("price", 0),
        "ProductType": "physical"
    })

    # Increase CountBuy only after verification
    products_collection.update_one(
        {"_id": purchase["product_id"]},
        {"$inc": {"CountBuy": 1}}
    )

    # ✅ АГАР МАҲСУЛ ЯК БОР ФУРӮХТАШАВАНДА БОШАД, ОНРО ҲАМЧУН ФУРӮХТАШУДА ИШОРА КУНЕД
    product_data = products_collection.find_one({"_id": purchase["product_id"]})
    if product_data.get("ProductType") == "physical":
        # Агар маҳсул якумин бор фурӯхта шавад, онро ҳамчун фурӯхташуда ишора кун
        # Шумо метавонед ягон флаг ё майдони махсус илова кунед
        if not product_data.get("IsSold", False):
            products_collection.update_one(
                {"_id": purchase["product_id"]},
                {"$set": {"IsSold": True, "SoldAt": datetime.datetime.now(datetime.timezone.utc)}}
            )
            print(f"✅ Product {purchase['product_id']} marked as sold")

    # Кам кардани пул (escrow) — харидорро пардохт мекунад, аммо фурӯшанда ҳанӯз намегирад
    users_collection.update_one(
        {"_id": ObjectId(purchase["user_id"])},
        {"$inc": {"Balance": -product_price}}
    )

    # Pay seller (escrow release) with 1% commission - ТАНҲО ЯК БОР
    seller_id = purchase.get("seller_user_id")
    commission = 0
    seller_amount = 0
    if seller_id:
        price = purchase.get("price", 0)
        commission = round(price * 0.01, 2)
        seller_amount = price - commission

        # Pay seller
        users_collection.update_one(
            {"_id": seller_id},
            {"$inc": {"Balance": seller_amount}}
        )

        # Transfer commission to admin/sanjar account
        users_collection.update_one(
            {"Username": "sanjar"},
            {"$inc": {"Balance": commission}}
        )
        
        print(f"💰 Commission: {commission} taken from {price} payment, seller receives {seller_amount}")

    buyer = users_collection.find_one({"_id": purchase["user_id"]})

    return {
        "success": True,
        "verified": True,
        "already_used": False,
        "commission": commission,
        "seller_amount": seller_amount,
        "purchase_data": {
            "purchase_id": str(purchase["_id"]),
            "product_name": purchase.get("product_name", ""),
            "physical_product_name": purchase.get("physical_product_name", ""),
            "purchase_date": purchase["purchase_date"].isoformat() + "Z",
            "buyer_username": buyer.get("Username") if buyer else "Unknown",
            "status": "used"
        }
    }

@router.get('/ad/{user_id}')
async def get_ad(user_id: str):
    # Add random advertisement to the beginning of the list
    user_object_id = ObjectId(user_id)

    # Get list of ads already viewed by user from viewed_ads_collection
    user_viewed_ads = set()
    viewed_ads_cursor = viewed_ads_collection.find({"user_id": ObjectId(user_id)})
    for viewed_ad in viewed_ads_cursor:
        if viewed_ad.get("ad_id"):
            # Convert ObjectId to string for comparison
            user_viewed_ads.add(str(viewed_ad["ad_id"]))

    print(f"📊 User {user_id} has already viewed {len(user_viewed_ads)} ads")

    # Get all possible advertisements (excluding the user themselves)
    all_advertisements = []

    # Unified function to get unseen ads
    def get_ads_from_collection(collection, query_filter, ad_type, name_field, user_id_field, link_field=None):
        ads = list(collection.find(query_filter))
        for ad in ads:
            ad_id = ad["_id"]
            ad_id_str = str(ad_id)  # Convert to string

            # Filter out already viewed ads
            if ad_id_str in user_viewed_ads:
                continue
                
            # IMPORTANT: Skip ads created by the user themselves
            ad_user_id = ad.get(user_id_field)
            if ad_user_id and str(ad_user_id) == user_id:
                continue

            # Create link
            if link_field and ad.get(link_field):
                link = ad[link_field]
            else:
                # For shopings_collection use ShopingName
                if ad_type == "shop" and ad.get("ShopingName"):
                    link = f"${ad['ShopingName']}"
                else:
                    link = f"https://www.anyvoice.world/{ad_type}/{ad_id_str}"

            all_advertisements.append({
                "type": ad_type,
                "data": ad,
                "collection": collection,
                "collection_name": collection.name,
                "link": link,
                "name": ad.get(name_field, ad_type.capitalize()),
                "user_id": ad_user_id,
            })

    # Get ads from all collections - EXCLUDING user's own ads
    user_filter = {
        "AdvertisementCheckbox": True,
        "AdvertisementCount": {"$gt": 0},
        # "UserId": {"$ne": user_object_id}  # This is now handled inside the function
    }

    # For each collection, specify the correct user_id field name
    get_ads_from_collection(videos_collection, user_filter, "video", "Title", "UserId", "Link")
    get_ads_from_collection(images_collection, user_filter, "image", "Title", "UserId", "Link")
    get_ads_from_collection(articles_collection, user_filter, "article", "Title", "user_id", "Link")  # articles uses 'user_id'
    get_ads_from_collection(products_collection, user_filter, "product", "ProductName", "UserId", "Link")
    get_ads_from_collection(shopings_collection, user_filter, "shop", "ShopingName", "UserId")
    get_ads_from_collection(theory_collection, user_filter, "theory", "Title", "user_id", "link")  # theories uses 'user_id'

    print(f"🔍 Found {len(all_advertisements)} unseen advertisements for user {user_id} (excluding user's own ads)")

    # Select a random ad from unseen list
    if all_advertisements:
        random_ad = random.choice(all_advertisements)
        ad_data = random_ad["data"]
        ad_id = ad_data["_id"]  # This is ObjectId
        ad_id_str = str(ad_id)  # For use in response
        ad_name = random_ad["name"]
        ad_link = random_ad["link"]
        ad_type = random_ad["type"]
        collection = random_ad["collection"]
        collection_name = random_ad["collection_name"]
        ad_user_id = random_ad.get("user_id")

        # SAVE THAT THIS AD HAS BEEN VIEWED IN viewed_ads_collection
        try:
            # Check if already exists in collection
            existing_view = viewed_ads_collection.find_one({
                "user_id": ObjectId(user_id),
                "ad_id": ad_id
            })

            if not existing_view:
                # Add data to viewed_ads_collection
                viewed_ad_doc = {
                    "user_id": ObjectId(user_id),
                    "ad_id": ad_id,  # Store as ObjectId here
                    "ad_type": ad_type,
                    "ad_name": ad_name,
                    "collection_name": collection_name,
                    "viewed_at": datetime.datetime.now(datetime.timezone.utc),
                    "created_at": datetime.datetime.now(datetime.timezone.utc)
                }
                viewed_ads_collection.insert_one(viewed_ad_doc)
                print(f"📝 Added to viewed_ads_collection for user {user_id}: {ad_id_str}")
            else:
                # If already exists, update view time
                viewed_ads_collection.update_one(
                    {"_id": existing_view["_id"]},
                    {"$set": {"viewed_at": datetime.datetime.now(datetime.timezone.utc)}}
                )
                print(f"🔄 Updated view time for ad {ad_id_str} for user {user_id}")
        except Exception as e:
            print(f"❌ Error saving to viewed_ads_collection: {str(e)}")

        # Decrease AdvertisementCount for displayed ad
        current_count = ad_data.get("AdvertisementCount", 0)
        if current_count > 0:
            # Update collection
            new_count = current_count - 1
            collection.update_one(
                {"_id": ad_id},
                {"$set": {"AdvertisementCount": new_count}}
            )

            print(f"📉 Decreased AdvertisementCount for {ad_type} {ad_id_str}: {current_count} → {new_count}")

            # Check if AdvertisementCount reached 0
            if new_count == 0:
                # Send notification to ad owner
                if ad_user_id:
                    try:
                        owner_notification_message = f"Your advertisement {ad_link} has been displayed the requested number of times. Thank you for advertising🥰!"
                        encrypted_owner_message = encrypt_data(owner_notification_message, ENCRYPTION_KEY)
                        encrypted_owner_type = encrypt_data("advertisement_completed", ENCRYPTION_KEY)

                        owner_notification_doc = {
                            "NotificationFrom": None,  # System
                            "NotificationTo": ad_user_id,
                            "Message": encrypted_owner_message,
                            "PostId": ad_id if ad_type in ["video", "image", "article", "product", "theory"] else None,
                            "ShopingId": ad_id if ad_type == "shop" else None,
                            "IsRead": False,
                            "UploadAt": datetime.datetime.now(datetime.timezone.utc).isoformat().replace('Z', '+00:00'),
                            "Type": encrypted_owner_type,
                            "status": "pending",
                            "isAdvertisementCompletion": True
                        }

                        notifications_collection.insert_one(owner_notification_doc)

                        # Send notification to owner's WebSocket
                        serialized_owner_notification = serialize_notification(owner_notification_doc)
                        await broadcast_notification(str(ad_user_id), "add", serialized_owner_notification)

                        print(f"✅ Sent completion notification to owner of {ad_type} {ad_id_str}")
                    except Exception as e:
                        print(f"❌ Error sending completion notification: {str(e)}")

        # Create advertisement notification for current user
        ad_notification = {
            "_id": ObjectId(),  # New random ID
            "NotificationFrom": None,
            "NotificationTo": user_object_id,
            "Message": '📢 Advertisement',
            "PostId": ad_id if ad_type in ["video", "image", "article", "product", "theory"] else None,
            "ShopingId": ad_id if ad_type == "shop" else None,
            "IsRead": False,
            "UploadAt": datetime.datetime.now(datetime.timezone.utc).isoformat().replace('Z', '+00:00'),
            "Type": "advertisement",
            "status": "pending",
            "isAdvertisement": True,
            "ad_name": ad_name,
            "ad_link": ad_link,
            "ad_type": ad_type,
            "collection_type": collection_name,
            "advertisement_type": f"{ad_type}_promotion",
            "advertisement_count_remaining": new_count if 'new_count' in locals() else current_count,
            "is_new_ad": True  # Indicator that this is a new ad
        }

        # Create serialized version of this notification
        ad_dict = dict(ad_notification)
        for key, value in ad_dict.items():
            if isinstance(value, ObjectId):
                ad_dict[key] = str(value)
            elif isinstance(value, datetime.datetime):
                ad_dict[key] = value.isoformat()

        # Add additional fields for frontend
        ad_dict["ad_id"] = ad_id_str  # Use string here
        ad_dict["DecryptedType"] = "advertisement"
        ad_dict["AdvertisementCheckbox"] = ad_data["AdvertisementCheckbox"]
        
        # Add user_id of ad owner to check if it's the current user
        ad_dict["ad_owner_id"] = str(ad_user_id) if ad_user_id else None

        print(f"✅ Added NEW advertisement notification: {ad_type} - {ad_name} (ID: {ad_id_str})")

        return ad_dict

    else:
        print(f"ℹ️ No unseen advertisements available for user {user_id}")

        # If no unseen ads available, maybe show a seen ad
        if user_viewed_ads:
            print(f"📋 User {user_id} has seen all available ads ({len(user_viewed_ads)} total)")

        return None

@router.get("/chats/unread_count/{user_id}")
async def get_unread_count(user_id: str):
    user_object_id = ObjectId(user_id)
    count = messages_collection.count_documents({
        "to_user_id": user_object_id, 
        "is_read": False,
        "is_deleted": {"$ne": True}
    })
    return {"unread_count": count}

@router.get("/get-following-articles")
async def get_following_articles(
    limit: int = 20,
    exclude_ids: List[str] = Query(default=[]),
    user_id: str = Query(..., description="ID of the requesting user")
):
    if not ObjectId.is_valid(user_id):
        raise HTTPException(status_code=400, detail="Invalid user ID format")

    try:
        excluded_object_ids = [ObjectId(i) for i in exclude_ids if ObjectId.is_valid(i)]
    except Exception:
        excluded_object_ids = []

    following = followers_collection.find({"follower_id": ObjectId(user_id)})
    followed_user_ids = [follow["target_user_id"] for follow in following if ObjectId.is_valid(follow["target_user_id"])]

    if not followed_user_ids:
        return {"articles": []}

    match_criteria = {
        "_id": {"$nin": excluded_object_ids},
        "user_id": {"$in": followed_user_ids}
    }

    pipeline = [
        {"$match": match_criteria},
        {"$sample": {"size": limit}}
    ]

    results = list(articles_collection.aggregate(pipeline))
    
    articles_id = []
    for article in results:
        try:
            articles_id.append({"id": str(article["_id"])})
        except Exception as e:
            print(f"Error processing article {article.get('_id')}: {e}")
            continue
    
    return {
        "articles": articles_id
    }

@router.get("/get-following-images")
def get_following_images(
    limit: int = 20,
    exclude_ids: List[str] = Query(default=[]),
    user_id: str = Query(..., description="ID of the requesting user")
):
    # Validate user_id
    if not ObjectId.is_valid(user_id):
        raise HTTPException(status_code=400, detail="Invalid user ID format")

    # Convert exclude_ids to ObjectIds
    try:
        excluded_object_ids = [ObjectId(i) for i in exclude_ids if ObjectId.is_valid(i)]
    except Exception:
        excluded_object_ids = []

    # Get list of followed users
    following = followers_collection.find({"follower_id": ObjectId(user_id)})
    followed_user_ids = [follow["target_user_id"] for follow in following if ObjectId.is_valid(follow["target_user_id"])]

    if not followed_user_ids:
        return {"images": []}

    # Convert followed_user_ids to strings for string-based CollaborationAccounts
    followed_user_ids_str = [str(uid) for uid in followed_user_ids]

    # Build match criteria
    match_criteria = {
        "_id": {"$nin": excluded_object_ids},
        "Visibility": "public",
        "$or": [
            {"UserId": {"$in": followed_user_ids}},
            {
                "$or": [
                    {"CollaborationAccounts": {"$in": followed_user_ids}},  # For ObjectId
                    {"CollaborationAccounts": {"$in": followed_user_ids_str}},  # For string IDs
                    {
                        "CollaborationAccounts": {
                            "$regex": "|".join(followed_user_ids_str),
                            "$options": "i"
                        }
                    }  # For JSON or malformed string
                ]
            }
        ]
    }

    # Exclude images where user is blocked
    match_criteria["BlockUsersList"] = {"$ne": ObjectId(user_id)}

    pipeline = [
        {"$match": match_criteria},
        {"$sample": {"size": limit}}
    ]

    results = list(images_collection.aggregate(pipeline))
    return {
        "images": [{"id": str(item["_id"]), "user_id": str(item["UserId"])} for item in results]
    }

@router.get("/get-following-videos")
def get_following_videos(
    limit: int = 20,
    exclude_ids: List[str] = Query(default=[]),
    user_id: str = Query(..., description="ID of the requesting user")
):
    # Validate user_id
    if not ObjectId.is_valid(user_id):
        raise HTTPException(status_code=400, detail="Invalid user ID format")

    # Convert exclude_ids to ObjectIds
    try:
        excluded_object_ids = [ObjectId(i) for i in exclude_ids if ObjectId.is_valid(i)]
    except Exception:
        excluded_object_ids = []

    # Get list of followed users
    following = followers_collection.find({"follower_id": ObjectId(user_id)})
    followed_user_ids = [follow["target_user_id"] for follow in following if ObjectId.is_valid(follow["target_user_id"])]

    if not followed_user_ids:
        return {"videos": []}

    # Convert followed_user_ids to strings for string-based CollaborationAccounts
    followed_user_ids_str = [str(uid) for uid in followed_user_ids]

    # Build match criteria
    match_criteria = {
        "_id": {"$nin": excluded_object_ids},
        "Visibility": "public",
        "$or": [
            {"UserId": {"$in": followed_user_ids}},
            {
                "$or": [
                    {"CollaborationAccounts": {"$in": followed_user_ids}},  # For ObjectId
                    {"CollaborationAccounts": {"$in": followed_user_ids_str}},  # For string IDs
                    {
                        "CollaborationAccounts": {
                            "$regex": "|".join(followed_user_ids_str),
                            "$options": "i"
                        }
                    }  # For JSON or malformed string
                ]
            }
        ]
    }

    # Exclude videos where user is blocked
    match_criteria["BlockUsersList"] = {"$ne": ObjectId(user_id)}

    pipeline = [
        {"$match": match_criteria},
        {"$sample": {"size": limit}}
    ]

    results = list(videos_collection.aggregate(pipeline))
    return {
        "videos": [{"id": str(item["_id"]), "user_id": str(item["UserId"])} for item in results]
    }

@router.get("/get-following-products")
def get_following_products(
    limit: int = 20,
    exclude_ids: List[str] = Query(default=[]),
    user_id: str = Query(..., description="ID of the requesting user")
):
    try:
        # Validate user_id
        if not ObjectId.is_valid(user_id):
            raise HTTPException(status_code=400, detail="Invalid user ID format")

        # Convert exclude_ids to ObjectIds
        try:
            excluded_object_ids = [ObjectId(i) for i in exclude_ids if ObjectId.is_valid(i)]
        except Exception:
            excluded_object_ids = []

        # Get list of followed users
        following = followers_collection.find({"follower_id": ObjectId(user_id)})
        followed_user_ids = [follow["target_user_id"] for follow in following if ObjectId.is_valid(follow["target_user_id"])]

        if not followed_user_ids:
            return {"products": []}

        # Convert followed_user_ids to strings for string-based CollaborationShopings
        followed_user_ids_str = [str(uid) for uid in followed_user_ids]

        # Build match criteria
        match_criteria = {
            "_id": {"$nin": excluded_object_ids},
            "$or": [
                {"UserId": {"$in": followed_user_ids}},
                {
                    "$or": [
                        {"CollaborationShopings": {"$in": followed_user_ids}},  # For ObjectId
                        {"CollaborationShopings": {"$in": followed_user_ids_str}},  # For string IDs
                        {
                            "CollaborationShopings": {
                                "$regex": "|".join(followed_user_ids_str),
                                "$options": "i"
                            }
                        }  # For JSON or malformed string
                    ]
                }
            ]
        }

        # Exclude products where user is blocked
        match_criteria["BlockUsersList"] = {"$ne": ObjectId(user_id)}

        pipeline = [
            {"$match": match_criteria},
            {"$sample": {"size": limit}}
        ]

        results = list(products_collection.aggregate(pipeline))
        return {
            "products": [{"id": str(item["_id"]), "user_id": str(item["UserId"])} for item in results]
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.get("/get-following-theories")
def get_following_theories(
    limit: int = 20,
    exclude_ids: List[str] = Query(default=[]),
    user_id: str = Query(..., description="ID of the requesting user")
):
    # Validate user_id
    if not ObjectId.is_valid(user_id):
        raise HTTPException(status_code=400, detail="Invalid user ID format")

    # Convert exclude_ids to ObjectIds
    try:
        excluded_object_ids = [ObjectId(i) for i in exclude_ids if ObjectId.is_valid(i)]
    except Exception:
        excluded_object_ids = []

    # Get list of followed users
    following = followers_collection.find({"follower_id": ObjectId(user_id)})
    followed_user_ids = [follow["target_user_id"] for follow in following if ObjectId.is_valid(follow["target_user_id"])]

    if not followed_user_ids:
        return {"theories": []}

    # Convert followed_user_ids to strings for string-based CollaborationAccounts
    followed_user_ids_str = [str(uid) for uid in followed_user_ids]

    # Build match criteria
    match_criteria = {
        "_id": {"$nin": excluded_object_ids},
        "$or": [
            {"user_id": {"$in": followed_user_ids}},
        ]
    }

    pipeline = [
        {"$match": match_criteria},
        {"$sample": {"size": limit}}
    ]

    results = list(theory_collection.aggregate(pipeline))
    return {
        "theories": [{"id": str(item["_id"]), "user_id": str(item["user_id"])} for item in results]
    }

@router.get("/get-following-shopings")
def get_following_shopings(
    limit: int = 20,
    exclude_ids: List[str] = Query(default=[]),
    user_id: str = Query(..., description="ID of the requesting user")
):
    # Validate user_id
    if not ObjectId.is_valid(user_id):
        raise HTTPException(status_code=400, detail="Invalid user ID format")

    # Convert exclude_ids to ObjectIds
    try:
        excluded_object_ids = [ObjectId(i) for i in exclude_ids if ObjectId.is_valid(i)]
    except Exception:
        excluded_object_ids = []

    # Get list of followed users
    following = followers_collection.find({"follower_id": ObjectId(user_id)})
    followed_user_ids = [follow["target_user_id"] for follow in following if ObjectId.is_valid(follow["target_user_id"])]

    if not followed_user_ids:
        return {"shopings": []}

    # Build match criteria
    match_criteria = {
        "_id": {"$nin": excluded_object_ids},
        "$or": [
            {"UserId": {"$in": followed_user_ids}},
        ]
    }

    pipeline = [
        {"$match": match_criteria},
        {"$sample": {"size": limit}}
    ]

    results = list(shopings_collection.aggregate(pipeline))
    return {
        "shopings": [
            {
                "id": str(item["_id"]),
                "user_id": str(item["UserId"]),
            }
        for item in results]
    }
