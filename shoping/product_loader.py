# backend/shoping/product_loader.py

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from dotenv import load_dotenv
from fastapi import Query
from bson import ObjectId
import os
from menu.menu import products_collection, files_products_collection, \
users_collection, products_comment_collection, products_fs, users_fs, \
messages_collection, reports_of_product, products_views_collection, \
notifications_collection, products_buy_collection, product_comment_likes, \
products_save_collection, shopings_collection, physical_product_purchases_collection, shopings_fs
import datetime
from pydantic import BaseModel
from typing import Optional
import base64
from account.account import manager_account
import json
import re
from home.home import broadcast_notification, serialize_notification
import qrcode
from io import BytesIO
from home.chat import manager_chat
from urllib.parse import quote
from menu.menu import encrypt_data, decrypt_data
from home.home import send_email

# Load environment variables
load_dotenv()

my_email = os.getenv("MY_EMAIL")

router = APIRouter()

ENCRYPTION_KEY = os.getenv("ENCRYPTION_KEY")

class ConnectionManager:
    def __init__(self):
        self.active_connections: dict[str, list[WebSocket]] = {}

    async def connect(self, websocket: WebSocket, product_id: str):
        try:
            await websocket.accept()
            if product_id not in self.active_connections:
                self.active_connections[product_id] = []
            self.active_connections[product_id].append(websocket)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Error in WebSocket connect: {e}")

    def disconnect(self, websocket: WebSocket, product_id: str):
        try:
            if product_id in self.active_connections:
                if websocket in self.active_connections[product_id]:
                    self.active_connections[product_id].remove(websocket)
                if not self.active_connections[product_id]:
                    del self.active_connections[product_id]
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Error in WebSocket disconnect: {e}")

    async def broadcast(self, product_id: str, message: dict):
        if product_id in self.active_connections:
            connections_to_remove = []
            for connection in self.active_connections[product_id]:
                try:
                    await connection.send_json(message)
                except Exception as e:
                    connections_to_remove.append(connection)
            # Remove invalid connections
            for connection in connections_to_remove:
                self.disconnect(connection, product_id)

manager_product = ConnectionManager()

@router.websocket("/ws/updates-product/{product_id}")
async def websocket_updates(websocket: WebSocket, product_id: str):
    await manager_product.connect(websocket, product_id)
    try:
        while True:
            # Wait for messages to keep connection alive
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager_product.disconnect(websocket, product_id)
    except Exception as e:
        manager_product.disconnect(websocket, product_id)

# Function to send notifications to users
async def send_purchase_notification(product_owner_id, shoping_owner_ids, buyer_id, product_data, product_id):
    try:
        buyer_user = users_collection.find_one({"_id": ObjectId(buyer_id)})
        product_owner = users_collection.find_one({"_id": ObjectId(product_owner_id)})
        
        if not buyer_user or not product_owner:
            return
        
        buyer_username = buyer_user.get("Username", "User")
        product_link = product_data.get("Link", "")
        
        # Notification for product owner
        encrypted_purchase_type = encrypt_data("purchase", ENCRYPTION_KEY)
        message_to_owner = encrypt_data(
            f"Your product was purchased by @{buyer_username}. View product: {product_link}", 
            ENCRYPTION_KEY
        )
        
        notification_to_owner = {
            "NotificationFrom": ObjectId(buyer_id),
            "NotificationTo": ObjectId(product_owner_id),
            "Message": message_to_owner,
            "PostId": ObjectId(product_id),
            "IsRead": False,
            "UploadAt": datetime.datetime.now(datetime.timezone.utc).isoformat().replace('Z', '+00:00'),
            "Type": encrypted_purchase_type,
            "status": "pending"
        }
        notifications_collection.insert_one(notification_to_owner)
        serialized_notification = serialize_notification(notification_to_owner)
        await broadcast_notification(str(product_owner_id), "add", serialized_notification)

        # 🛍️ Notification for shop owners
        for shoping_id in shoping_owner_ids:
            try:
                shoping_data = shopings_collection.find_one({"_id": ObjectId(shoping_id)})
                if not shoping_data:
                    continue

                shoping_name = shoping_data.get("ShopingName", "Shop")
                shoping_owner_id = shoping_data.get("UserId")

                if not shoping_owner_id:
                    continue

                message_to_shoping_owner = encrypt_data(
                    f"Product in shop ${shoping_name} was purchased by @{buyer_username}. "
                    f"View product: {product_link}",
                    ENCRYPTION_KEY
                )

                notification_to_shoping_owner = {
                    "NotificationFrom": ObjectId(buyer_id),
                    "NotificationTo": ObjectId(shoping_owner_id),
                    "ShopingId": ObjectId(shoping_id),
                    "Message": message_to_shoping_owner,
                    "PostId": ObjectId(product_id),
                    "IsRead": False,
                    "UploadAt": datetime.datetime.now(datetime.timezone.utc).isoformat().replace('Z', '+00:00'),
                    "Type": encrypted_purchase_type,
                    "status": "pending"
                }

                notifications_collection.insert_one(notification_to_shoping_owner)
                serialized_notification = serialize_notification(notification_to_shoping_owner)
                await broadcast_notification(str(shoping_owner_id), "add", serialized_notification)

            except Exception as inner_e:
                print(f"Error sending notification to shop owner: {str(inner_e)}")
                continue

    except Exception as e:
        print(f"Error sending notifications: {str(e)}")

@router.get("/get-product-preview/{product_id}")
async def get_product_preview(product_id: str, user_id: str = Query(None, description="ID of the requesting user")):
    # Validate ObjectId
    if not ObjectId.is_valid(product_id):
        raise HTTPException(status_code=400, detail="Invalid product ID format")

    post_info = products_collection.find_one({"_id": ObjectId(product_id)})
    if not post_info:
        raise HTTPException(status_code=404, detail="Post not found")

    user_is_blocked = False

    # If user_id is provided, check that user is not in BlockUsersList
    if user_id and ObjectId.is_valid(user_id):
        block_list = post_info.get("BlockUsersList", [])
        block_object_ids = [
            ObjectId(uid) for uid in block_list if ObjectId.is_valid(str(uid))
        ]
        if ObjectId(user_id) in block_object_ids:
            user_is_blocked = True

    # Check for CollaborationShopings
    collaboration_shopings = post_info.get('CollaborationShopings', [])

    # If CollaborationShopings is empty, check UserCanSeeProduct
    if not collaboration_shopings:
        user_can_see_product = post_info.get('UserCanSeeProduct', [])

        # If user_id is not provided or not in UserCanSeeProduct, error
        if str(user_id) in [str(uid) for uid in user_can_see_product]:
            pass
        else:
            user_is_blocked = True

    if user_is_blocked:
        return {
            'user_is_blocked': user_is_blocked,
        }

    product_ids = post_info.get("ProductImageIds", [])
    if not product_ids:
        raise HTTPException(status_code=404, detail="No products found for this post")

    # Get only the first image
    first_product_data = products_fs.get(product_ids[0]).read()
    first_product_base64 = base64.b64encode(first_product_data).decode()

    user_info = users_collection.find_one({'_id': post_info['UserId']})
    if not user_info:
        raise HTTPException(status_code=404, detail="User not found")

    username = user_info['Username']
    display = user_info.get('Display', '')
    decrypted_display = decrypt_data(display, ENCRYPTION_KEY) if display else ''
    title = post_info.get('Title', '')
    data_of_product = post_info.get('DataOfProduct', '')
    decrypted_link = post_info['Link']
    UploadAt = post_info.get('UploadAt').isoformat() + "Z"
    UpdateAt = post_info.get('UpdateAt')
    personal_product_sales = post_info.get('PersonalProductSales', False)

    profile_image_id = user_info.get("ProfileImageId")
    if profile_image_id:
        file_avatar = users_fs.get(ObjectId(profile_image_id))
        avatar_base64 = base64.b64encode(file_avatar.read()).decode('utf-8')
    else:
        avatar_base64 = ''

    # print(post_info.get("PersonalProductSales", False))

    return {
        "id": str(post_info['_id']),
        "images_data": [first_product_base64],  # Only first image
        "product_count": len(product_ids),  # Total number of images
        "title": title,
        "data_of_product": data_of_product,
        "username": str(username),
        "display": str(decrypted_display),
        "avatar": avatar_base64,
        "buy_count": post_info.get('CountBuy', 0),
        "comment_count": post_info.get('CountComment', 0),
        "collaborator_ids": str(post_info['CollaborationShopings']),
        "share_count": post_info.get('CountShare', 0),
        "save_count": post_info.get('CountSave', 0),
        "count_view": post_info.get('CountView', 0),
        "Link": decrypted_link,
        "BlockUsersList": [str(uid) for uid in post_info.get('BlockUsersList', [])],
        "UploadAt": UploadAt,
        "UpdateAt": UpdateAt,
        'allow_comments': post_info.get('AllowComments', False),
        'price': post_info.get('PriceProduct', 0),
        "personal_product_sales": personal_product_sales,
        "product_type": post_info.get('ProductType', ''),
        "physical_product_name": post_info.get('PhysicalProductName', ''),
        "is_sold": post_info.get("IsSold", False),  # Илова кунед
        "sold_at": post_info.get("SoldAt").isoformat() + "Z" if post_info.get("SoldAt") else None,
        "physical_delivery_method": post_info.get("PhysicalDeliveryMethod", "pickup"),
        "physical_pickup_address": post_info.get("PhysicalPickupAddress", ""),
        "physical_courier_available": post_info.get("PhysicalCourierAvailable", False),
    }

class BlockMessage(BaseModel):
    user_id: str
    block_user: str
    product_id: str

@router.post("/block-product")
async def block_product(block: BlockMessage):
    try:
        # Validate ObjectId
        if not ObjectId.is_valid(block.user_id) or not ObjectId.is_valid(block.block_user) or not ObjectId.is_valid(block.product_id):
            raise HTTPException(status_code=400, detail="Invalid user_id, block_user, or product_id format")

        # Get product information
        product = products_collection.find_one({"_id": ObjectId(block.product_id)})
        if not product:
            raise HTTPException(status_code=404, detail="Product not found")

        # Check permission: user_id must be owner or collaborator
        is_owner = str(product.get("UserId")) == block.user_id
        collaborator_ids = []
        collaboration_accounts = product.get("CollaborationShopings", "")
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
            raise HTTPException(status_code=403, detail="Not authorized to block users for this product")

        # Check if user to block exists
        block_user_info = users_collection.find_one({"_id": ObjectId(block.block_user)})
        if not block_user_info:
            raise HTTPException(status_code=404, detail="User to block not found")

        # Add block_user as ObjectId to BlockUsersList
        block_users_list = product.get("BlockUsersList", [])
        block_user_object_id = ObjectId(block.block_user)
        if block_user_object_id not in block_users_list:
            block_users_list.append(block_user_object_id)
            products_collection.update_one(
                {"_id": ObjectId(block.product_id)},
                {"$set": {"BlockUsersList": block_users_list}}
            )

        # Broadcast update (with string ID for frontend)
        await manager_product.broadcast(block.product_id, {
            "type": "block_user",
            "block_user_id": block.block_user,  # string for frontend
            "product_id": block.product_id
        })

        return {"success": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/cancel-block-product")
async def cancel_block(block: BlockMessage):
    # Validate ObjectId
    if not ObjectId.is_valid(block.user_id) or not ObjectId.is_valid(block.block_user) or not ObjectId.is_valid(block.product_id):
        raise HTTPException(status_code=400, detail="Invalid user_id, block_user, or product_id format")

    # Get product information
    product = products_collection.find_one({"_id": ObjectId(block.product_id)})
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    # Check permission: user_id must be owner or collaborator
    is_owner = str(product.get("UserId")) == block.user_id
    collaborator_ids = []
    collaboration_accounts = product.get("CollaborationShopings", "")
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
        raise HTTPException(status_code=403, detail="Not authorized to cancel block for this product")

    # Check if user to unblock exists
    block_user_info = users_collection.find_one({"_id": ObjectId(block.block_user)})
    if not block_user_info:
        raise HTTPException(status_code=404, detail="User to unblock not found")

    # Remove block_user as ObjectId from BlockUsersList
    block_users_list = product.get("BlockUsersList", [])
    block_user_object_id = ObjectId(block.block_user)
    if block_user_object_id in block_users_list:
        block_users_list.remove(block_user_object_id)
        products_collection.update_one(
            {"_id": ObjectId(block.product_id)},
            {"$set": {"BlockUsersList": block_users_list}}
        )

    # Broadcast update (with string ID for frontend)
    await manager_product.broadcast(block.product_id, {
        "type": "cancel_block_user",
        "block_user_id": block.block_user,  # string for frontend
        "product_id": block.product_id
    })

    return {"success": True}

@router.get("/get-product-by-id/{product_id}")
def get_product_by_id_v2(product_id: str, user_id: str = Query(None, description="ID of the requesting user")):
    """
    Version 2: Return product information more efficiently.
    """
    # Validate ObjectId
    if not ObjectId.is_valid(product_id):
        raise HTTPException(status_code=400, detail="Invalid product ID format")

    post_info = products_collection.find_one({"_id": ObjectId(product_id)})
    if not post_info:
        raise HTTPException(status_code=404, detail="Product not found")

    # If user_id is provided, check that user is not in BlockUsersList
    if user_id and ObjectId.is_valid(user_id):
        block_list = post_info.get("BlockUsersList", [])
        block_object_ids = [
            ObjectId(uid) for uid in block_list if ObjectId.is_valid(str(uid))
        ]
        if ObjectId(user_id) in block_object_ids:
            raise HTTPException(status_code=403, detail="Access denied")

    # Check for CollaborationShopings
    collaboration_shopings = post_info.get('CollaborationShopings', [])

    # If CollaborationShopings is empty, check UserCanSeeProduct
    if not collaboration_shopings:
        user_can_see_product = post_info.get('UserCanSeeProduct', [])

        # If user_id is not provided or not in UserCanSeeProduct, error
        if not user_id or str(user_id) not in [str(uid) for uid in user_can_see_product]:
            raise HTTPException(
                status_code=403, 
                detail="Access denied: This product is not available for public viewing or you don't have permission"
            )

    product_ids = post_info.get("ProductImageIds", [])
    if not product_ids:
        raise HTTPException(status_code=404, detail="No images found for this product")

    # Load only the first image for efficiency
    # Frontend can load remaining images with /get-product-image-by-index
    max_images_to_load = min(1, len(product_ids))
    images_data = []
    
    for i in range(max_images_to_load):
        try:
            file = products_fs.find_one({"_id": ObjectId(product_ids[i])})
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
    data_of_product = post_info.get('DataOfProduct', '')
    decrypted_link = post_info['Link']
    UploadAt = post_info.get('UploadAt').isoformat() + "Z"
    UpdateAt = post_info.get('UpdateAt')

    profile_image_id = user_info.get("ProfileImageId")
    if profile_image_id:
        file_avatar = users_fs.get(ObjectId(profile_image_id))
        avatar_base64 = base64.b64encode(file_avatar.read()).decode('utf-8')
    else:
        avatar_base64 = ''

    file_id = post_info.get('FileId', None)
    user_id_for_sell = post_info.get('UserIdForSell', None)

    metadata_file_id = None
    username_for_sell = None

    if file_id:
        metadata = files_products_collection.find_one({'_id': ObjectId(file_id)})
        if metadata:
            metadata_file_id = metadata.get('file_id')

    if user_id_for_sell:
        userdata = users_collection.find_one({'_id': ObjectId(user_id_for_sell)})
        if userdata:
            username_for_sell = userdata.get('Username')

    return {
        "id": str(post_info['_id']),
        "images_data": images_data,  # Only first image
        "total_images": len(product_ids),  # Total number of images
        "title": title,
        "data_of_product": data_of_product,
        "username": str(username),
        "display": str(decrypted_display),
        "avatar": avatar_base64,
        "buy_count": post_info.get('CountBuy', 0),
        "comment_count": post_info.get('CountComment', 0),
        'collaborator_ids': str(post_info['CollaborationShopings']),
        'share_count': post_info.get('CountShare', 0),
        'save_count': post_info.get('CountSave', 0),
        'count_view': post_info.get('CountView', 0),
        'Link': decrypted_link,
        'BlockUsersList': [str(uid) for uid in post_info.get('BlockUsersList', [])],
        'UploadAt': UploadAt,
        'UpdateAt': UpdateAt,
        'allow_comments': post_info.get('AllowComments', False),
        'metadata_file_id': str(metadata_file_id) if metadata_file_id else None,
        'username_for_sell': str(username_for_sell) if username_for_sell else None,
        'user_id_for_sell': str(user_id_for_sell) if user_id_for_sell else None,
        'price': post_info.get('PriceProduct', 0),
        "is_sold": post_info.get("IsSold", False),  # Илова кунед
        "sold_at": post_info.get("SoldAt").isoformat() + "Z" if post_info.get("SoldAt") else None,
        "physical_delivery_method": post_info.get("PhysicalDeliveryMethod", "pickup"),
        "physical_pickup_address": post_info.get("PhysicalPickupAddress", ""),
        "physical_courier_available": post_info.get("PhysicalCourierAvailable", False),
    }

@router.get("/get-product-image-by-index/{product_id}/{index}")
def get_product_image_by_index(product_id: str, index: int, user_id: str = Query(None)):
    """
    Get a specific image from the product's image collection by index.
    """
    if not ObjectId.is_valid(product_id):
        raise HTTPException(status_code=400, detail="Invalid product ID format")

    # Get product information
    post_info = products_collection.find_one({"_id": ObjectId(product_id)})
    if not post_info:
        raise HTTPException(status_code=404, detail="Product not found")

    # Check blocking
    if user_id and ObjectId.is_valid(user_id):
        block_list = post_info.get("BlockUsersList", [])
        block_object_ids = [
            ObjectId(uid) for uid in block_list if ObjectId.is_valid(str(uid))
        ]
        if ObjectId(user_id) in block_object_ids:
            raise HTTPException(status_code=403, detail="Access denied")

    # Check for CollaborationShopings
    collaboration_shopings = post_info.get('CollaborationShopings', [])

    # If CollaborationShopings is empty, check UserCanSeeProduct
    if not collaboration_shopings:
        user_can_see_product = post_info.get('UserCanSeeProduct', [])

        # If user_id is not provided or not in UserCanSeeProduct, error
        if not user_id or str(user_id) not in [str(uid) for uid in user_can_see_product]:
            raise HTTPException(
                status_code=403, 
                detail="Access denied: This product is not available for public viewing or you don't have permission"
            )

    # Get image IDs
    product_ids = post_info.get("ProductImageIds", [])
    if not product_ids:
        raise HTTPException(status_code=404, detail="No images found for this product")

    # Check index validity
    if index < 0 or index >= len(product_ids):
        raise HTTPException(status_code=400, detail="Invalid image index")

    # Get specific image
    try:
        image_id_obj = ObjectId(product_ids[index])
        file = products_fs.find_one({"_id": image_id_obj})
        if not file:
            raise HTTPException(status_code=404, detail="Image file not found")
        
        image_binary = file.read()
        encoded = base64.b64encode(image_binary).decode('utf-8')
        
        # Return only one image
        return {
            "image_id": encoded,
            "index": index,
            "total_images": len(product_ids)
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error loading image: {str(e)}")

@router.get("/check-buy-product")
def get_buy_info(
    user_id: str = Query(..., description="User ID"),
    product_id: str = Query(..., description="Image ID"),
):
    try:
        # Validate ObjectId for user_id and product_id
        if not ObjectId.is_valid(user_id) or not ObjectId.is_valid(product_id):
            return False  # Return False instead of error

        # Check if product exists in ProductsData
        product_exists = products_collection.find_one({'_id': ObjectId(product_id)})
        if not product_exists:
            return False  # Return False instead of error

        # Check purchase
        buy = products_buy_collection.find_one({
            'UserId': ObjectId(user_id),
            'PostProductId': ObjectId(product_id),
        })

        return bool(buy)  # Return True if purchase exists, False otherwise
    except Exception as e:
        return False  # Return False instead of error

@router.get("/check-save-product-status")
def check_save_status(product_id: str, user_id: str):
    if not ObjectId.is_valid(product_id) or not ObjectId.is_valid(user_id):
        raise HTTPException(status_code=400, detail="Invalid ID format")

    saved = products_save_collection.find_one({
        "PostProductId": ObjectId(product_id),
        "UserId": ObjectId(user_id)
    })

    return {"saved": bool(saved)}  # True or False

class ViewEndRequest(BaseModel):
    user_id: str
    product_id: str

@router.post("/track-view-product")
async def track_view_end(request: ViewEndRequest):
    if not ObjectId.is_valid(request.user_id) or not ObjectId.is_valid(request.product_id):
        raise HTTPException(status_code=400, detail="Invalid user_id or product_id format")

    user_id = ObjectId(request.user_id)
    product_id = ObjectId(request.product_id)

    product = products_collection.find_one({"_id": product_id})
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    # Check: does view record already exist
    existing_view = products_views_collection.find_one({
        "user_id": user_id,
        "product_id": product_id
    })

    # ✅ If record does not exist, create it and increment CountView once
    if not existing_view:
        products_views_collection.insert_one({
            "user_id": user_id,
            "product_id": product_id,
            "viewed_at": datetime.datetime.now(datetime.timezone.utc)
        })

        products_collection.update_one(
            {"_id": product_id},
            {"$inc": {"CountView": 1}}
        )

        product_data = products_collection.find_one({"_id": product_id})
        await manager_product.broadcast(str(product_id), {
            "type": "view_count",
            "value": product_data.get("CountView", 0)
        })

    # If record already exists, do nothing
    return {"success": True}

@router.get("/check-balance-for-product/{product_id}-{user_id_from_me}")
async def check_balance_for_product(product_id: str, user_id_from_me: str):
    product_data = products_collection.find_one({'_id': ObjectId(product_id)})
    if not product_data:
        raise HTTPException(status_code=404, detail="Product not found")

    user_data = users_collection.find_one({'_id': ObjectId(user_id_from_me)})
    if not user_data:
        raise HTTPException(status_code=404, detail="User not found")

    user_balance = user_data.get("Balance", 0)
    product_price = product_data.get("PriceProduct", 0)
    sold_out = product_data.get("SoldOut", False)
    purchased_account = product_data.get("PurchasedAccount")
    current_user_id = ObjectId(user_id_from_me)

    # If product is already sold
    if sold_out:
        # If this product was purchased by this user
        if purchased_account == current_user_id:
            return {
                "status": "ok",
                "message": f"You have already purchased this product. Balance: {user_balance}, Price: {product_price}"
            }
        else:
            # If sold to another person
            raise HTTPException(
                status_code=403,
                detail="This product has already been sold and you are not authorized to purchase it"
            )

    # If product is not sold yet — check balance
    if user_balance < product_price:
        if user_balance < product_price:
            raise HTTPException(
                status_code=402,
                detail="Insufficient balance"
            )

    return {
        "status": "ok",
        "message": f"Sufficient balance. Balance: {user_balance}, Price: {product_price}"
    }

class PhysicalProductPurchaseRequest(BaseModel):
    user_id: str
    product_id: str
    user_id_of_product: str
    price: int
    address: Optional[str] = None

@router.post("/purchase-physical-product")
async def purchase_physical_product(request: PhysicalProductPurchaseRequest):
    if not ObjectId.is_valid(request.user_id) or not ObjectId.is_valid(request.product_id):
        raise HTTPException(status_code=400, detail="Invalid user_id or product_id format")

    product = products_collection.find_one({"_id": ObjectId(request.product_id)})
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    delivery_method = product.get("PhysicalDeliveryMethod", "pickup")
    is_courier = delivery_method.lower() == "courier"

    buyer_address = None
    if is_courier:
        if not request.address or not request.address.strip():
            raise HTTPException(
                status_code=400, 
                detail="Delivery address is required for courier delivery"
            )
        buyer_address = request.address.strip()

    # ────────────────────────────────────────────────
    #        Check for previous purchase (duplicate)
    # ────────────────────────────────────────────────
    existing = physical_product_purchases_collection.find_one({
        "user_id": ObjectId(request.user_id),
        "product_id": ObjectId(request.product_id)
    })

    if existing:
        # 🧠 UPDATE address if courier
        if is_courier and buyer_address:
            physical_product_purchases_collection.update_one(
                {"_id": existing["_id"]},
                {
                    "$set": {
                        "buyer_address": buyer_address,
                        "updated_at": datetime.datetime.now(datetime.timezone.utc)
                    }
                }
            )

            # 👉 update local variable for later use
            existing["buyer_address"] = buyer_address

        # ────────────────────────────────────────────────
        #        Send notification
        # ────────────────────────────────────────────────
        if is_courier and buyer_address:
            buyer = users_collection.find_one({"_id": ObjectId(request.user_id)})
            if buyer:
                buyer_username = buyer.get("Username", "User")

                message = (
                    f"@{buyer_username} updated the address:\n\n"
                    f"{buyer_address}\n\n"
                    f"Product: {product.get('PhysicalProductName', '—')}\n"
                    f"Link: {product.get('Link', '')}"
                )

                encrypted_message = encrypt_data(message, ENCRYPTION_KEY)
                encrypted_type = encrypt_data("courier_delivery_request", ENCRYPTION_KEY)

                notification_doc = {
                    "NotificationFrom": ObjectId(request.user_id),
                    "NotificationTo": ObjectId(request.user_id_of_product),
                    "Message": encrypted_message,
                    "PostId": ObjectId(request.product_id),
                    "IsRead": False,
                    "UploadAt": datetime.datetime.now(datetime.timezone.utc).isoformat().replace('Z', '+00:00'),
                    "Type": encrypted_type,
                    "status": "product"
                }

                notifications_collection.insert_one(notification_doc)

                serialized = serialize_notification(notification_doc)
                await broadcast_notification(
                    str(request.user_id_of_product),
                    "add",
                    serialized
                )

        return {
            "success": True,
            "already_purchased": True,
            "qr_code_data": existing.get("qr_code_data"),
            "purchase_id": str(existing["_id"]),
            "delivery_method": existing.get("delivery_method", "pickup"),
            "buyer_address": existing.get("buyer_address"),
            "pickup_address": product.get("PhysicalPickupAddress", "")
        }

    # CHECK IF THIS PRODUCT HAS ALREADY BEEN SOLD TO ANOTHER USER
    # Check if the product has already been purchased by someone else
    other_user_purchase = physical_product_purchases_collection.find_one({
        "product_id": ObjectId(request.product_id),
        "user_id": {"$ne": ObjectId(request.user_id)}  # different user_id
    })
    
    # If product was purchased by another user and status is "used"
    if other_user_purchase and other_user_purchase.get("status") == "used":
        raise HTTPException(status_code=400, detail="This product has already been sold to another user and is no longer available")
    
    # If product was purchased by another user and status is "pending"
    if other_user_purchase and other_user_purchase.get("status") == "pending":
        raise HTTPException(status_code=400, detail="This product is currently pending purchase by another user")
    
    # Check buyer's balance
    user = users_collection.find_one({"_id": ObjectId(request.user_id)})
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    user_balance = user.get("Balance", 0)
    product_price = request.price
    if user_balance < product_price:
        raise HTTPException(status_code=402, detail="Insufficient funds")

    # Generate unique purchase_id and QR
    purchase_id = ObjectId()
    product_link = product.get("Link", "")
    qr_data_dict = {
        "purchase_id": str(purchase_id),
        "user_id": request.user_id,
        "product_id": request.product_id,
        "product_link": product_link,
        "purchase_date": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "product_name": product.get("Title", "Physical Product"),
        "physical_product_name": product.get("PhysicalProductName", "")
    }
    qr_json = json.dumps(qr_data_dict)

    qr = qrcode.QRCode(version=1, box_size=10, border=5)
    qr.add_data(qr_json)
    qr.make(fit=True)
    qr_image = qr.make_image(fill_color="black", back_color="white")
    buffered = BytesIO()
    qr_image.save(buffered, format="PNG")
    qr_base64 = base64.b64encode(buffered.getvalue()).decode('utf-8')
    qr_data_url = f"data:image/png;base64,{qr_base64}"

    # Save purchase in DB with status "pending"
    purchase_record = {
        "_id": purchase_id,
        "user_id": ObjectId(request.user_id),
        "product_id": ObjectId(request.product_id),
        "seller_user_id": ObjectId(request.user_id_of_product),
        "price": product_price,
        "purchase_date": datetime.datetime.now(datetime.timezone.utc),
        "qr_code_data": qr_data_url,
        "qr_code_json": qr_json,
        "product_link": product_link,
        "product_name": product.get("Title", ""),
        "physical_product_name": product.get("PhysicalProductName", ""),
        "delivery_method": delivery_method,
        "buyer_address": buyer_address if is_courier else None,
        "status": "pending"
    }
    physical_product_purchases_collection.insert_one(purchase_record)

    # Response to frontend
    return {
        "success": True,
        "already_purchased": False,
        "qr_code_data": qr_data_url,
        "purchase_id": str(purchase_record["_id"]),
        "delivery_method": delivery_method,
        "buyer_address": buyer_address,
        "pickup_address": product.get("PhysicalPickupAddress", "")
    }

@router.get("/download-file-of-product-save/{file_id}-{product_id}-{user_id}-{user_id_of_product}-{admin_id}")
async def download_file(file_id: str, product_id: str, user_id: str, user_id_of_product: str, admin_id: str):
    try:
        # Check if file exists
        if not products_fs.exists(ObjectId(file_id)):
            raise HTTPException(status_code=404, detail="File not found")

        metadata = files_products_collection.find_one({'file_id': ObjectId(file_id)})

        if not metadata:
            raise HTTPException(status_code=404, detail="File not found")

        # Get product information
        product_data = products_collection.find_one({'_id': ObjectId(product_id)})
        if not product_data:
            raise HTTPException(status_code=404, detail="Product not found")

        # Check if product is already sold
        if product_data.get("SoldOut") == True:
            purchased_account = product_data.get("PurchasedAccount")
            current_user_id = ObjectId(user_id)

            # If product is sold and current user is not the buyer
            if purchased_account and purchased_account != current_user_id:
                raise HTTPException(
                    status_code=403, 
                    detail="This product has already been sold and you are not authorized to purchase it"
                )

        filename = metadata['filename']
        file_size = metadata.get('size', 0)

        # Proper encoding of filename for non-ASCII characters
        encoded_filename = quote(filename, safe='')

        # Add purchase information (only if not already purchased)
        already_purchased = False

        # Check if this user has already purchased this product
        existing_purchase = products_buy_collection.find_one({
            'UserId': ObjectId(user_id),
            'PostProductId': ObjectId(product_id)
        })

        if existing_purchase:
            already_purchased = True
            print(f"User {user_id} has already purchased product {product_id}")
        else:
            # Create purchase record
            products_buy_collection.insert_one({
                'UserId': ObjectId(user_id),
                'PostProductId': ObjectId(product_id),
                'BuyIn': datetime.datetime.now(datetime.timezone.utc),
            })

            # Increment purchase count
            products_collection.update_one(
                {'_id': ObjectId(product_id)},
                {'$inc': {'CountBuy': 1}},
            )

            # 📉 Deduct amount from buyer and 📈 add amount to seller
            price = product_data.get("PriceProduct", 0)

            # Calculate commission
            commission = round(price * 0.01, 2)  # 1% commission
            seller_amount = price - commission    # amount that seller receives

            # Deduct amount from buyer's account
            users_collection.update_one(
                {"_id": ObjectId(user_id)},
                {"$inc": {"Balance": -price}}
            )

            # Add amount to seller's account (only 99%)
            users_collection.update_one(
                {"_id": ObjectId(user_id_of_product)},
                {"$inc": {"Balance": seller_amount}}
            )

            # Add commission to admin's account (if needed)
            admin_id = ObjectId(admin_id)
            users_collection.update_one(
                {"_id": admin_id},
                {"$inc": {"Balance": commission}}
            )

            # Get shop owner IDs
            collaboration_shopings = product_data.get("CollaborationShopings", [])
            shoping_owner_ids = []

            for shoping_id in collaboration_shopings:
                try:
                    shoping_data = shopings_collection.find_one({"_id": ObjectId(shoping_id)})
                    if shoping_data and shoping_data.get('_id'):
                        shoping_owner_ids.append(shoping_data['_id'])
                except Exception as e:
                    print(f"Error getting shop information: {str(e)}")
                    continue

            # Send notifications to product owner and shop owners
            product_owner_id = product_data.get("UserId")
            await send_purchase_notification(product_owner_id, shoping_owner_ids, user_id, product_data, product_id)

            # If product is personal sale, mark it as sold
            if product_data.get("PersonalProductSales"):
                products_collection.update_one(
                    {'_id': ObjectId(product_id)},
                    {
                        '$set': {
                            'SoldOut': True,
                            'PurchasedAccount': ObjectId(user_id)
                        }
                    }
                )

        # Update product data for broadcasting
        product_data_updated = products_collection.find_one({'_id': ObjectId(product_id)})

        # Send broadcast to display purchase count
        await manager_product.broadcast(product_id, {
            "type": "buy_count",
            "value": product_data_updated.get('CountBuy', 0),
            "user_id": user_id,
            "buy": not already_purchased,  # buy=True only for new purchase
        })

        # Streaming function to send file in chunks
        def file_stream():
            chunk_size = 1024 * 1024  # 1MB chunks
            try:
                with products_fs.get(ObjectId(file_id)) as file:
                    while True:
                        chunk = file.read(chunk_size)
                        if not chunk:
                            break
                        yield chunk
            except Exception as e:
                print(f"Error in file_stream: {str(e)}")
                raise

        # Return file with StreamingResponse
        from fastapi.responses import StreamingResponse

        return StreamingResponse(
            file_stream(),
            media_type=metadata['file_type'] or 'application/octet-stream',
            headers={
                'Content-Disposition': f'attachment; filename="{encoded_filename}"; filename*=UTF-8\'\'{encoded_filename}',
                'Content-Length': str(file_size),
                'Accept-Ranges': 'bytes'
            }
        )

    except MemoryError:
        raise HTTPException(status_code=500, detail="File is too large. Please select a smaller file.")

@router.get("/save-product")
async def save_product(user_id: str, product_id: str):
    saved = products_save_collection.find_one({
        "UserId": ObjectId(user_id),
        "PostProductId": ObjectId(product_id)
    })
    if saved:
        products_save_collection.delete_one({
            "UserId": ObjectId(user_id),
            "PostProductId": ObjectId(product_id)
        })
        products_collection.update_one(
            {"_id": ObjectId(product_id)},
            {"$inc": {"CountSave": -1}}
        )
        await manager_product.broadcast(product_id, {
            "type": "save_count",
            "value": products_collection.find_one({"_id": ObjectId(product_id)}).get("CountSave", 0),
            "user_id": user_id,
            "saved": not bool(saved)
        })
        return {"saved": False}
    else:
        products_save_collection.insert_one({
            "UserId": ObjectId(user_id),
            "PostProductId": ObjectId(product_id),
            "SavedAt": datetime.datetime.now(datetime.timezone.utc)
        })
        products_collection.update_one(
            {"_id": ObjectId(product_id)},
            {"$inc": {"CountSave": 1}}
        )
        await manager_product.broadcast(product_id, {
            "type": "save_count",
            "value": products_collection.find_one({"_id": ObjectId(product_id)}).get("CountSave", 0),
            "user_id": user_id,
            "saved": not bool(saved)
        })
        return {"saved": True}

class ShareMessage(BaseModel):
    from_user_id: str
    to_user_id: str
    product_id: str

@router.post("/share-product")
async def share_product(share: ShareMessage):
    created_at = datetime.datetime.now(datetime.timezone.utc)

    # Дастрасӣ ба маълумоти маҳсулот
    product_data = products_collection.find_one({"_id": ObjectId(share.product_id)})
    if not product_data:
        raise HTTPException(status_code=404, detail="Product not found")

    # Insert message
    result = messages_collection.insert_one({
        "from_user_id": ObjectId(share.from_user_id),
        "to_user_id": ObjectId(share.to_user_id),
        "message": product_data.get('Link'),
        "product_id": ObjectId(share.product_id),
        "created_at": created_at,
        "is_deleted": False,
        "is_edited": False,
        "is_read": False,
        "type": "product"
    })
    message_id = str(result.inserted_id)

    # Update share count
    products_collection.update_one(
        {"_id": ObjectId(share.product_id)},
        {"$inc": {"CountShare": 1}}
    )

    # Broadcast updated share count
    updated_product = products_collection.find_one({"_id": ObjectId(share.product_id)})
    await manager_product.broadcast(str(share.product_id), {
        "type": "share_count",
        "value": updated_product.get("CountShare", 0)
    })

    # Get user info
    user_data = users_collection.find_one({"_id": ObjectId(share.from_user_id)})
    if not user_data:
        raise HTTPException(status_code=404, detail="User not found")
    decrypted_display = decrypt_data(user_data.get('Display', ''), ENCRYPTION_KEY) if user_data.get('Display') else ''

    # Create message payload
    message_payload = {
        "type": "new_messanger",
        "value": {
            "from_user_id": str(share.from_user_id),
            "to_user_id": str(share.to_user_id),
            "username": user_data['Username'],
            "display": decrypted_display,
            "message": product_data.get('Link'),
            "product_id": share.product_id,
            "created_at": created_at.isoformat() + "Z",
            "message_id": message_id,
            "is_edited": False,
            "type": "product"
        }
    }

    # Broadcast message to both users
    await manager_chat.broadcast(str(share.from_user_id), message_payload)
    await manager_chat.broadcast(str(share.to_user_id), message_payload)

    return {"success": True, "message_id": message_id}

@router.post("/cancel-share-product")
async def cancel_share_product(share: ShareMessage):
    from_id = ObjectId(share.from_user_id)
    to_id = ObjectId(share.to_user_id)
    product_id = ObjectId(share.product_id)

    # Дастрасӣ ба маҳсулот
    product_data = products_collection.find_one({"_id": product_id})
    if not product_data:
        raise HTTPException(status_code=404, detail="Product not found")

    # Find the message
    message = messages_collection.find_one({
        "from_user_id": from_id,
        "to_user_id": to_id,
        "message": product_data.get('Link'),
        "type": "product",
        "is_deleted": False
    }, sort=[("created_at", -1)])
    if not message:
        raise HTTPException(status_code=404, detail="Message not found")

    # Soft delete the message
    deleted_at = datetime.datetime.now(datetime.timezone.utc)
    messages_collection.update_one(
        {"_id": message["_id"]},
        {"$set": {
            "is_deleted": True,
            "deleted_by": from_id,
            "deleted_at": deleted_at
        }}
    )

    # Update share count
    products_collection.update_one(
        {"_id": product_id},
        {"$inc": {"CountShare": -1}}
    )
    updated_product = products_collection.find_one({"_id": product_id})
    await manager_product.broadcast(str(product_id), {
        "type": "share_count",
        "value": max(0, updated_product.get("CountShare", 0))
    })

    # Get user info
    user_data = users_collection.find_one({"_id": from_id})
    decrypted_display = decrypt_data(user_data.get('Display', ''), ENCRYPTION_KEY) if user_data.get('Display') else ''

    # Broadcast delete event
    message_payload = {
        "type": "delete_messanger",
        "value": {
            "from_user_id": str(from_id),
            "to_user_id": str(to_id),
            "username": user_data['Username'],
            "display": decrypted_display,
            "message_id": str(message["_id"]),
            "created_at": message["created_at"].isoformat() + "Z",
            "is_deleted": True,
            "deleted_by": str(from_id),
            "deleted_at": deleted_at.isoformat(),
            "type": "product"
        }
    }
    await manager_chat.broadcast(str(from_id), message_payload)
    await manager_chat.broadcast(str(to_id), message_payload)

    return {"success": True}

class ProductReportRequest(BaseModel):
    user_id: str
    product_id: str
    reason: str

@router.post("/report-product")
async def report_product(request: ProductReportRequest):
    # Validate ObjectId
    if not ObjectId.is_valid(request.user_id) or not ObjectId.is_valid(request.product_id):
        raise HTTPException(status_code=400, detail="Invalid user_id or product_id format")

    # Check if comment exists
    product = products_collection.find_one({"_id": ObjectId(request.product_id)})
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    # Check if user exists
    user = users_collection.find_one({"_id": ObjectId(request.user_id)})
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # Check for duplicate report
    existing_report = reports_of_product.find_one({
        "user_id": ObjectId(request.user_id),
        "product_id": ObjectId(request.product_id)
    })
    if existing_report:
        raise HTTPException(status_code=401, detail="You have already reported this product")

    # Encrypt reason
    encrypted_reason = encrypt_data(request.reason, ENCRYPTION_KEY)

    # Save report in ProductReports table
    report_data = {
        "user_id": ObjectId(request.user_id),
        "product_id": ObjectId(request.product_id),
        "reason": encrypted_reason,
        "created_at": datetime.datetime.now(datetime.timezone.utc)
    }
    reports_of_product.insert_one(report_data)

    send_email(
        recipient=my_email,
        message=f"""Шикоят аз маҳсули https://www.anyvoice.world/product/{product["Link"]}.\n
        Шикоят кунанда: @{user['Username']}\n
        Сабаб: {request.reason}\n""",
        subject='Шикоят⚠️'
    )

    return {"success": True}

class DeleteProductRequest(BaseModel):
    product_id: str
    user_id: str

@router.post("/delete-product")
async def delete_product_api(data: DeleteProductRequest):
    product_id = ObjectId(data.product_id)
    user_id = ObjectId(data.user_id)

    # Fetch the product
    product = products_collection.find_one({"_id": product_id})
    if not product:
        raise HTTPException(status_code=404, detail="Post not found")

    is_owner = product.get("UserId") == user_id
    collaborators_raw = product.get("CollaborationShopings", "[]")

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

    if is_collaborator and not is_owner:
        # Collaborator case: Remove user from CollaborationShopings and decrement their CountProducts
        if user_id in collaborators:
            collaborators.remove(user_id)
            products_collection.update_one(
                {"_id": product_id},
                {"$set": {"CollaborationShopings": [str(cid) for cid in collaborators]}}
            )

            # Decrement CountProducts for the collaborator
            users_collection.update_one(
                {"_id": user_id},
                {"$inc": {"CountPosts": -1, "CountProducts": -1}}
            )

            # Broadcast delete_product message
            await manager_account.broadcast(str(user_id), {
                "type": "delete_product",
                "product_id": str(data.product_id),
            })

        return {"status": "removed_from_collaborators"}

    elif is_owner:
        # Owner case: Delete the product and decrement owner's CountProducts
        products_collection.delete_one({"_id": product_id})
        products_comment_collection.delete_many({"product_id": product_id})
        product_comment_likes.delete_many({"product_id": product_id})
        reports_of_product.delete_many({"product_id": product_id})
        products_save_collection.delete_many({"PostProductId": product_id})
        notifications_collection.delete_many({"PostId": product_id})
        products_buy_collection.delete_many({"PostProductId": product_id})

        # Delete associated files from GridFS
        for img_id in product.get("ProductImageIds", []):
            try:
                products_fs.delete(ObjectId(img_id))
            except Exception as e:
                raise HTTPException(status_code=400, detail=f"Error deleting product file {img_id} from GridFS: {e}")

        # Decrement CountProducts for owner
        users_collection.update_one(
            {"_id": user_id},
            {"$inc": {"CountPosts": -1, "CountProducts": -1}}
        )

        # Decrement CountProducts for all collaborators
        for collaborator_id in collaborators:
            shopings_collection.update_one(
                {"_id": collaborator_id},
                {"$inc": {"CountProducts": -1}}
            )

        # Broadcast delete_product message
        await manager_account.broadcast(str(user_id), {
            "type": "delete_product",
            "product_id": str(data.product_id),
        })

        # Broadcast delete_product message
        await manager_product.broadcast(str(data.product_id), {
            "type": "delete_product",
            "product_id": str(data.product_id),
        })

        return {"status": "deleted"}

@router.get("/get-shoping-info/{shoping_id}")
def get_shoping_info(shoping_id: str):
    # Validate ObjectId
    if not ObjectId.is_valid(shoping_id):
        raise HTTPException(status_code=400, detail="Invalid shoping ID format")

    # Get user information
    shoping_info = shopings_collection.find_one({'_id': ObjectId(shoping_id)})
    if not shoping_info:
        raise HTTPException(status_code=404, detail="shoping not found")

    # Get avatar
    profile_image_id = shoping_info.get("ThumbnailId")
    avatar_base64 = ''
    if profile_image_id:
        try:
            file_avatar = shopings_fs.get(ObjectId(profile_image_id))
            avatar_base64 = base64.b64encode(file_avatar.read()).decode('utf-8')
        except Exception as e:
            avatar_base64 = ''

    # Decrypt display
    display = shoping_info.get('Display', '')
    decrypted_display = decrypt_data(display, ENCRYPTION_KEY) if display else ''

    return {
        "shoping_id": str(shoping_info['_id']),
        "shoping_name": shoping_info['ShopingName'],
        "display": decrypted_display,
        "avatar": avatar_base64
    }
