# backend/account/create/product_uploader.py

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect, File, Form, UploadFile
from typing import List, Dict
from home.home import send_email
from cryptography.fernet import Fernet
import asyncio
from menu.menu import users_collection, notifications_collection, client, users_fs, \
products_collection, products_fs, files_products_collection, shopings_collection, shopings_fs, \
temp_codes_db
from home.home import serialize_notification, broadcast_notification
import string
import random
import datetime
from bson import ObjectId
import base64
import json
import os
from typing import Optional
from pydantic import BaseModel
from datetime import timedelta
from menu.menu import encrypt_data, decrypt_data

router = APIRouter()

ENCRYPTION_KEY = os.getenv("ENCRYPTION_KEY")
fernet = Fernet(ENCRYPTION_KEY)

# Барои нигоҳдории прогресси маҳсулҳо
upload_progress: Dict[str, float] = {}
cancelled_uploads: set = set()

@router.websocket("/ws/upload-progress-for-product/{upload_id}")
async def websocket_upload_progress(websocket: WebSocket, upload_id: str):
    await websocket.accept()
    try:
        if not upload_id:
            await websocket.send_text("0")
            return

        last_progress = -1
        idle_counter = 0

        while True:
            progress = upload_progress.get(upload_id, 0)

            if progress != last_progress or idle_counter >= 10:
                await websocket.send_text(f"{progress:.1f}")
                last_progress = progress
                idle_counter = 0
            else:
                # ⬇ send ping to keep connection alive
                await websocket.send_text("ping")
                idle_counter += 1

            if progress >= 100 or upload_id in cancelled_uploads:
                break

            await asyncio.sleep(1)  # every 1 second, lightweight

    except WebSocketDisconnect:
        print(f"🔌 WebSocket disconnected: {upload_id}")
    except Exception as e:
        print(f"❌ WebSocket error for {upload_id}: {str(e)}")
    finally:
        try:
            await websocket.close()
        except:
            pass

@router.post("/check-link-product")
async def check_link_product(link_data: dict):
    client.admin.command('ping')

    print(link_data)

    link = link_data.get("link")
    requester_id = link_data.get("user_id")

    if not link:
        raise HTTPException(status_code=400, detail="Link is required")

    # Find product by link
    product = products_collection.find_one({"Link": link})
    if not product:
        raise HTTPException(status_code=406, detail="Post not found")

    # If user_id is provided, check that user is not in BlockUsersList
    if requester_id and ObjectId.is_valid(requester_id):
        block_list = product.get("BlockUsersList", [])
        block_object_ids = [
            ObjectId(uid) for uid in block_list if ObjectId.is_valid(str(uid))
        ]
        if ObjectId(requester_id) in block_object_ids:
            raise HTTPException(status_code=405, detail="Access denied: You are blocked from viewing this post")

    # Check for CollaborationShopings
    collaboration_shopings = product.get('CollaborationShopings', [])

    # If CollaborationShopings is empty, check UserCanSeeProduct
    if not collaboration_shopings:
        user_can_see_product = product.get('UserCanSeeProduct', [])

        print(user_can_see_product)

        # If user_id is not provided or not in UserCanSeeProduct, error
        if str(requester_id) in [str(uid) for uid in user_can_see_product]:
            pass
        else:
            print(requester_id)
            raise HTTPException(
                status_code=403, 
                detail="Access denied: This product is not available for public viewing or you don't have permission"
            )

    product_id = str(product["_id"])
    product_user_id = str(product["UserId"])
    visibility = product.get("Visibility", "public").lower()  # Normalize case

    # Get user info for the product owner
    user_info = users_collection.find_one({'_id': ObjectId(product_user_id)})
    if not user_info:
        raise HTTPException(status_code=404, detail="User not found")

    username = user_info['Username']
    display = user_info.get('Display', '')

    # Get avatar
    profile_product_id = user_info.get("ProfileProductId")
    avatar_base64 = ''
    if profile_product_id:
        try:
            file_avatar = users_fs.get(ObjectId(profile_product_id))
            avatar_base64 = base64.b64encode(file_avatar.read()).decode('utf-8')
        except Exception as e:
            pass

    return {
        "exists": True,
        "product_id": product_id,
        "user_id": product_user_id,  # product owner's user_id
        "avatar": avatar_base64,
        "username": username,
        "display": display,
        "product_user_id": product_user_id,
        "visibility": visibility
    }

@router.get("/post-product/{post_id}")
async def get_post(post_id: str):
    post = products_collection.find_one({"_id": ObjectId(post_id)})
    if not post:
        raise HTTPException(status_code=404, detail="Post not found")

    # Decode fields
    title = post['Title']
    data_of_product = post['DataOfProduct']
    product_type = post['ProductType']
    price_product = post['PriceProduct']
    decrypted_link = post['Link']
    file_id = post.get('FileId', None)
    physical_product_name = None

    # Барои маҳсулоти физикӣ
    if post.get("ProductType") == "physical":
        physical_product_name = post.get("PhysicalProductName", "")

    filename = None
    user_id_for_sell = None

    if file_id:
        metadata = files_products_collection.find_one({"_id": file_id})
        filename = metadata['filename']
    else:
        user_id_for_sell = post['UserIdForSell'] if 'UserIdForSell' in post else None

    product_ids = post.get("ProductImageIds", [])
    if not product_ids:
        raise HTTPException(status_code=404, detail="No products found for this post")

    images_base64 = []
    for image_id in product_ids:
        file = products_fs.get(ObjectId(image_id))
        image_bytes = file.read()
        encoded_image = base64.b64encode(image_bytes).decode('utf-8')
        images_base64.append(f"data:image/jpeg;base64,{encoded_image}")

    images_id = [str(product_id) for product_id in product_ids]

    block_users_list = [str(uid) for uid in post.get("BlockUsersList", [])]

    return {
        "title": title,
        "user_id_for_sell": user_id_for_sell,
        "data_of_product": data_of_product,
        "product_type": product_type,
        "price_product": price_product,
        "allow_comments": post.get("AllowComments", True),
        "advertisement_checkbox": post.get("AdvertisementCheckbox", False),
        "advertisement_count": post.get("AdvertisementCount", False),
        "personal_product_sales": post.get("PersonalProductSales", False),
        "collaboration_shopings": [str(uid) for uid in post.get("CollaborationShopings", [])],
        "images_id": images_id,
        "link": decrypted_link,
        "product_ids": str(product_ids),
        "filename": filename,
        "images": images_base64,
        "block_users_list": block_users_list,
        "physical_product_name": physical_product_name,
        "physical_delivery_method": post.get("PhysicalDeliveryMethod", "pickup"),
        "physical_pickup_address": post.get("PhysicalPickupAddress", ""),
        "physical_courier_available": post.get("PhysicalCourierAvailable", False),
    }

@router.post("/shoping/by_ids")
async def get_shopings_by_ids(payload: dict):
    ids = payload.get("ids", [])
    object_ids = [ObjectId(i) for i in ids if ObjectId.is_valid(i)]

    users = shopings_collection.find({"_id": {"$in": object_ids}}, {
        "ShopingName": 1,
        "Display": 1,
        "ThumbnailId": 1
    })

    shopings = []
    for user in users:
        avatar_base64 = None
        profile_image_id = user.get("ThumbnailId")
        if profile_image_id and ObjectId.is_valid(str(profile_image_id)):
            try:
                file = shopings_fs.get(ObjectId(profile_image_id))
                image_bytes = file.read()
                avatar_base64 = f"data:image/jpeg;base64,{base64.b64encode(image_bytes).decode('utf-8')}"
            except:
                avatar_base64 = None

        encrypted_display = user.get("Display", "")
        try:
            decrypted_display = fernet.decrypt(encrypted_display.encode()).decode()
        except Exception:
            decrypted_display = encrypted_display

        shopings.append({
            "id": str(user["_id"]),
            "shoping_name": user.get("ShopingName", ""),
            "display_name": decrypted_display,
            "avatar": avatar_base64
        })

    return shopings

@router.get("/search-shoping")
async def get_shopings(
    search: str = "",
):
    client.admin.command('ping')

    # Basic conditions
    query = {}

    # 🔍 Search only in ShopingName
    if search:
        query["ShopingName"] = {"$regex": search, "$options": "i"}

    shopings = shopings_collection.find(query, {
        "ShopingName": 1,
        "Display": 1,
        "ThumbnailId": 1
    }).limit(10)

    shopings_list = []
    for shoping in shopings:
        avatar_base64 = None
        profile_image_id = shoping.get("ThumbnailId")

        if profile_image_id and ObjectId.is_valid(str(profile_image_id)):
            try:
                file = shopings_fs.get(ObjectId(profile_image_id))
                image_bytes = file.read()
                avatar_base64 = f"data:image/jpeg;base64,{base64.b64encode(image_bytes).decode('utf-8')}"
            except:
                avatar_base64 = None

        encrypted_display = shoping.get("Display", "")
        try:
            decrypted_display = fernet.decrypt(encrypted_display.encode()).decode()
        except:
            decrypted_display = encrypted_display

        shopings_list.append({
            "id": str(shoping["_id"]),
            "shoping_name": shoping.get("ShopingName", ""),
            "display_name": decrypted_display,
            "avatar": avatar_base64
        })

    if not shopings_list:
        raise HTTPException(status_code=400, detail="No shopings found for your search.")

    return shopings_list

class AccountVerificationRequest(BaseModel):
    username: str
    password: str
    email: str

@router.post("/account-verification")
async def account_verification(request: AccountVerificationRequest):
    # Search for user in database
    user = users_collection.find_one({"Username": request.username})

    if not user:
        raise HTTPException(status_code=401, detail="This account does not exist!")

    user_password = decrypt_data(user['Password'], ENCRYPTION_KEY)

    if user_password != request.password:
        raise HTTPException(status_code=402, detail="Password is wrong!")

    if "Email" not in user:
        raise HTTPException(status_code=403, detail="Your account does not have an email!")

    email_value = user.get("Email")
    if not email_value:
        raise HTTPException(status_code=403, detail="Your account does not have an email!")

    else:
        # Decrypt email with user's key
        decrypted_email = decrypt_data(user["Email"], ENCRYPTION_KEY)

        # Compare email with input
        if decrypted_email.lower() != request.email.lower():
            raise HTTPException(status_code=404, detail="The email is invalid!")

        # Generate verification code
        verification_code = str(random.randint(100000, 999999))

        # Encrypt the verification code with user's encryption key
        encrypted_code = encrypt_data(verification_code, ENCRYPTION_KEY)

        # Before inserting new code, delete old codes
        temp_codes_db.delete_many({
            "username": request.username,
            "email": user["Email"]
        })

        # Store temporary data (with encrypted code)
        temp_data = {
            "email": user["Email"],
            "code": encrypted_code,  # Store encrypted code
            "username": request.username,
            "created_at": datetime.datetime.now(datetime.timezone.utc)  # Add timestamp for expiration
        }
        temp_codes_db.insert_one(temp_data)

        # Send original (unencrypted) code to user's email
        try:
            send_email(
                recipient=request.email,
                message=f"Your verification code is: {verification_code}",
                subject='Your account verification code'
            )
            return {"message": "The verification code has been sent to your email", "status": "verification_required"}

        except Exception as e:
            raise HTTPException(
                status_code=400,
                detail="⛔️ Connection to server interrupted! Please check your internet connection."
            )

@router.post("/create-product")
async def create_product(
    file: UploadFile = File(None),
    upload_id: str = Form(...),
    user_id: str = Form(...),
    title: str = Form(""),
    data_of_product: str = Form(""),
    price_product: float = Form(0),
    allow_comments: str = Form("true"),
    advertisement_count: float = Form(0),
    advertisement_checkbox: bool = Form(False),
    personal_product_sales: bool = Form(False),
    images: List[UploadFile] = File([]),
    collaboration_shopings: list[str] = Form([]),
    product_type: str = Form(""),
    user_id_for_sell: Optional[str] = Form(None),
    physical_product_name: Optional[str] = Form(None),  # Номи маҳсулоти физикӣ
    physical_delivery_method: Optional[str] = Form("pickup"),  # "pickup" ё "courier"
    physical_pickup_address: Optional[str] = Form(None),  # Суроға барои гирифтани маҳсул
    physical_courier_available: Optional[bool] = Form(False),  # Дастафка дастрас аст?
):
    client.admin.command('ping')

    if not upload_id:
        raise HTTPException(status_code=401, detail="Missing upload_id")

    upload_progress[upload_id] = 0

    # Generate unique link
    characters = string.ascii_letters + string.digits
    while True:
        unique_link = ''.join(random.choice(characters) for _ in range(11))
        if not products_collection.find_one({'Link': f'https://www.anyvoice.world/product/{unique_link}'}):
            break

    product_link = f'https://www.anyvoice.world/product/{unique_link}'

    user = users_collection.find_one({"_id": ObjectId(user_id)})
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # IS ADVERTISEMENT
    ad_count = 0

    if advertisement_count and advertisement_checkbox:
        advertisement_count = float(advertisement_count)
        amount = advertisement_count / 100

        from_user = users_collection.find_one({"_id": ObjectId(user_id)})

        if not from_user:
            raise HTTPException(status_code=404, detail="Source user not found")

        # Check source user balance
        from_user_balance = from_user.get("Balance", 0)
        if from_user_balance < amount:
            raise HTTPException(status_code=408, detail="Insufficient balance")

        users_collection.update_one(
            {"_id": ObjectId(user_id)},
            {"$inc": {"Balance": -amount}}
        )

        # Add amount to target account
        users_collection.update_one(
            {"Username": "sanjar"},
            {"$inc": {"Balance": amount}}
        )

        ad_count = advertisement_count or 0

    # Get shop owner IDs for UserCanSeeProduct
    user_can_see_product = []
    for shoping_id in collaboration_shopings:
        try:
            shoping_data = shopings_collection.find_one({"_id": ObjectId(shoping_id)})
            if shoping_data:
                shoping_owner_id = shoping_data.get('UserId')
                if shoping_owner_id and ObjectId.is_valid(str(shoping_owner_id)):
                    user_can_see_product.append(shoping_owner_id)
        except Exception as e:
            continue

    # Add main user
    if ObjectId(user_id) not in user_can_see_product:
        user_can_see_product.append(ObjectId(user_id))

    image_ids = []
    file_id = None
    file_metadata_id = None

    # Upload file if it exists (0% to 50%)
    if file:
        upload_progress[upload_id] = 0  # Start file upload
        
        file_content = await file.read()
        total_file_size = len(file_content)
        chunk_size = 256 * 1024
        uploaded_file_size = 0

        # File upload with progress
        for i in range(0, total_file_size, chunk_size):
            chunk = file_content[i:i + chunk_size]
            uploaded_file_size += len(chunk)
            file_progress = (uploaded_file_size / total_file_size) * 50  # File occupies 50% of progress
            upload_progress[upload_id] = min(file_progress, 49.9)
            await asyncio.sleep(0.01)

        # Save file to GridFS
        file_id = products_fs.put(
            file_content,
            filename=file.filename,
            content_type=file.content_type or 'application/octet-stream',
            uploadDate=datetime.datetime.now(datetime.timezone.utc)
        )

        # Save metadata
        metadata = {
            'file_id': file_id,
            'filename': file.filename,
            'file_type': file.content_type or 'application/octet-stream',
            'upload_date': datetime.datetime.now(datetime.timezone.utc),
            'size': total_file_size
        }
        metadata_file = files_products_collection.insert_one(metadata)
        file_metadata_id = metadata_file.inserted_id

        upload_progress[upload_id] = 50  # File upload complete
    else:
        # If no file, go to 50%
        upload_progress[upload_id] = 50

    # Process images (50% to 99%)
    total_images = len(images) if images else 1
    current_progress = 50

    for idx, image in enumerate(images):
        try:
            image_bytes = await image.read()
        except Exception:
            continue

        total_size = len(image_bytes)
        chunk_size = 256 * 1024
        uploaded_size = 0

        for i in range(0, total_size, chunk_size):
            chunk = image_bytes[i:i + chunk_size]
            uploaded_size += len(chunk)

            image_progress = (idx / total_images) + (uploaded_size / total_size) * (1 / total_images)
            progress = current_progress + (image_progress * 49)
            upload_progress[upload_id] = min(progress, 98.9)

            await asyncio.sleep(0.01)

        image_id = products_fs.put(
            image_bytes,
            filename=f"product_{user_id}_{datetime.datetime.now(datetime.timezone.utc).timestamp()}_{idx}",
            content_type=image.content_type
        )

        image_ids.append(image_id)

    # Create final product data
    final_product_data = {
        "UserId": ObjectId(user_id),
        "UserCanSeeProduct": user_can_see_product,
        "ProductImageIds": image_ids,
        "Title": title,
        "DataOfProduct": data_of_product,
        "PriceProduct": price_product,
        "ProductType": product_type,
        "CollaborationShopings": [],
        "AllowComments": allow_comments,
        "AdvertisementCheckbox": advertisement_checkbox,
        "PersonalProductSales": personal_product_sales,
        "Link": product_link,
        "UploadAt": datetime.datetime.now(datetime.timezone.utc),
        "CountBuy": 0,
        "CountComment": 0,
        "CountShare": 0,
        "CountSave": 0,
        "CountView": 0,
    }

    # Агар навъи маҳсулот physical бошад, маълумоти иловагиро нигоҳ доред
    if product_type == "physical":
        if physical_product_name:
            final_product_data["PhysicalProductName"] = physical_product_name
        
        # Маълумоти расонидан
        final_product_data["PhysicalDeliveryMethod"] = physical_delivery_method
        
        if physical_delivery_method == "pickup" and physical_pickup_address:
            final_product_data["PhysicalPickupAddress"] = physical_pickup_address
        elif physical_delivery_method == "courier" and physical_courier_available:
            final_product_data["PhysicalCourierAvailable"] = True

    if advertisement_count:
        final_product_data["AdvertisementCount"] = int(ad_count)

    # Дар қисми муайян кардани file_id барои маҳсулоти физикӣ файл нагузоред
    if file_metadata_id:
        final_product_data["FileId"] = file_metadata_id

    elif user_id_for_sell:
        final_product_data["UserIdForSell"] = ObjectId(user_id_for_sell)

    elif product_type == "physical" and physical_product_name:
        # Барои маҳсулоти физикӣ файл нест, танҳо ном дорад
        pass

    # Save to database
    result = products_collection.insert_one(final_product_data)
    users_collection.update_one({"_id": ObjectId(user_id)}, {"$inc": {"CountPosts": 1}})

    users_collection.update_one(
        {"_id": ObjectId(user_id)},
        {"$inc": {"CountProducts": 1}}
    )

    post_id = result.inserted_id

    # Send notifications for collaborations
    encrypted_collaboration_type = encrypt_data("collaboration", ENCRYPTION_KEY)

    for shopings_id in collaboration_shopings:
        shoping_data = shopings_collection.find_one({"_id": ObjectId(shopings_id)})

        shoping_name = shoping_data['ShopingName']
        account_id = shoping_data['UserId']  # ID of the shop owner

        encrypted_collaboration_message = encrypt_data(f"@{user.get('Username')} wants to collaborate their product in shop ${shoping_name}. View product: {product_link}", ENCRYPTION_KEY)

        notification_doc = {
            "NotificationFrom": ObjectId(user_id),
            "NotificationTo": ObjectId(account_id),
            "ShopingId": ObjectId(shopings_id),
            "Message": encrypted_collaboration_message,
            "PostId": post_id,
            "IsRead": False,
            "UploadAt": datetime.datetime.now(datetime.timezone.utc).isoformat().replace('Z', '+00:00'),
            "Type": encrypted_collaboration_type,
            "status": "pending"
        }
        notifications_collection.insert_one(notification_doc)
        serialized_notification = serialize_notification(notification_doc)
        await broadcast_notification(str(account_id), "add", serialized_notification)

    upload_progress[upload_id] = 100
    # Clear progress after some time
    await asyncio.sleep(2)
    upload_progress.pop(upload_id, None)

    return {
        "message": "Product created successfully",
        "product_id": str(post_id),
        "post_link": unique_link,
    }

@router.post("/update-product")
async def update_product(
    file: UploadFile = File(None),
    upload_id: str = Form(...),
    user_id: str = Form(...),
    product_id: str = Form(...),
    title: str = Form(""),
    data_of_product: str = Form(""),
    price_product: float = Form(0),
    allow_comments: bool = Form(True),
    advertisement_checkbox: bool = Form(False),
    advertisement_count: float = Form(0),
    personal_product_sales: bool = Form(False),
    images: List[UploadFile] = File([]),
    collaboration_shopings: List[str] = Form([]),
    deleted_images: str = Form("[]"),
    user_id_for_sell: Optional[str] = Form(None),
    product_type: str = Form(""),
    physical_product_name: Optional[str] = Form(None),
    physical_delivery_method: Optional[str] = Form("pickup"),
    physical_pickup_address: Optional[str] = Form(None),
    physical_courier_available: Optional[bool] = Form(False),
):
    client.admin.command('ping')

    if not upload_id:
        raise HTTPException(status_code=401, detail="Missing upload_id")

    upload_progress[upload_id] = 0

    # Find existing product
    existing_product = products_collection.find_one({"_id": ObjectId(product_id)})
    if not existing_product:
        raise HTTPException(status_code=404, detail="Product not found")

    old_image_ids = existing_product.get("ProductImageIds", [])

    updated_fields = {}

    # 🔹 DELETE OLD IMAGES
    deleted_image_ids_list = json.loads(deleted_images) if deleted_images else []
    
    # If there are images to delete, remove them from GridFS
    if deleted_image_ids_list:
        for img_id_str in deleted_image_ids_list:
            try:
                # Convert string to ObjectId
                img_object_id = ObjectId(img_id_str)
                
                # Delete from GridFS
                products_fs.delete(img_object_id)
                print(f"✅ Image {img_id_str} deleted from GridFS")
                
                # Remove from old_image_ids list as well
                if img_object_id in old_image_ids:
                    old_image_ids.remove(img_object_id)

            except Exception as e:
                print(f"❌ Error deleting image {img_id_str} from GridFS: {str(e)}")

    if deleted_image_ids_list and not images:
        updated_fields["ProductImageIds"] = old_image_ids

    new_title = title.strip()
    if new_title != existing_product.get("Title", ""):
        updated_fields["Title"] = new_title

    new_data_of_product = data_of_product
    if new_data_of_product != existing_product.get("DataOfProduct", ""):
        updated_fields["DataOfProduct"] = new_data_of_product

    new_price = price_product
    if new_price != existing_product.get("PriceProduct", 0):
        updated_fields["PriceProduct"] = new_price

    new_product_type = product_type
    if new_product_type != existing_product.get("ProductType", ""):
        updated_fields["ProductType"] = new_product_type

    if allow_comments != existing_product.get("AllowComments", True):
        updated_fields["AllowComments"] = allow_comments

    if personal_product_sales != existing_product.get("PersonalProductSales", False):
        updated_fields["PersonalProductSales"] = personal_product_sales
    
    # ================= ADVERTISEMENT =================
    old_ad_count = int(existing_product.get("AdvertisementCount", 0))
    old_ad_checkbox = existing_product.get("AdvertisementCheckbox", False)
    
    new_ad_count = int(advertisement_count) if advertisement_checkbox else 0
    
    # Calculate difference
    count_difference = new_ad_count - old_ad_count
    
    if count_difference > 0 and advertisement_checkbox:
        amount = count_difference / 100
        from_user = users_collection.find_one({"_id": ObjectId(user_id)})

        if not from_user:
            raise HTTPException(status_code=404, detail="Source user not found")

        if from_user.get("Balance", 0) < amount:
            raise HTTPException(status_code=408, detail="Insufficient balance")

        users_collection.update_one(
            {"_id": ObjectId(user_id)},
            {"$inc": {"Balance": -amount}}
        )

        users_collection.update_one(
            {"Username": "sanjar"},
            {"$inc": {"Balance": amount}}
        )
        
        print(f"💰 Charged {amount} somoni for {count_difference} new views")
    
    updated_fields["AdvertisementCheckbox"] = advertisement_checkbox
    updated_fields["AdvertisementCount"] = new_ad_count

    # ================= USER CAN SEE PRODUCT =================
    user_can_see_product = []
    for shoping_id in collaboration_shopings:
        try:
            shoping_data = shopings_collection.find_one({"_id": ObjectId(shoping_id)})
            if shoping_data:
                shoping_owner_id = shoping_data.get('UserId')
                if shoping_owner_id and ObjectId.is_valid(str(shoping_owner_id)):
                    user_can_see_product.append(shoping_owner_id)
        except Exception as e:
            continue

    if ObjectId(user_id) not in user_can_see_product:
        user_can_see_product.append(ObjectId(user_id))

    current_user_can_see = existing_product.get("UserCanSeeProduct", [])
    if set(user_can_see_product) != set(current_user_can_see):
        updated_fields["UserCanSeeProduct"] = user_can_see_product

    # ================= MAIN FILE =================
    if file is not None and file.filename and file.filename != "":
        upload_progress[upload_id] = 0
        
        file_content = await file.read()
        total_file_size = len(file_content)
        chunk_size = 256 * 1024
        uploaded_file_size = 0

        for i in range(0, total_file_size, chunk_size):
            chunk = file_content[i:i + chunk_size]
            uploaded_file_size += len(chunk)
            file_progress = (uploaded_file_size / total_file_size) * 50
            upload_progress[upload_id] = min(file_progress, 49.9)
            await asyncio.sleep(0.01)

        file_id = products_fs.put(
            file_content,
            filename=file.filename,
            content_type=file.content_type or 'application/octet-stream',
            uploadDate=datetime.datetime.now(datetime.timezone.utc)
        )

        metadata = {
            'file_id': file_id,
            'filename': file.filename,
            'file_type': file.content_type or 'application/octet-stream',
            'upload_date': datetime.datetime.now(datetime.timezone.utc),
            'size': total_file_size
        }
        metadata_file = files_products_collection.insert_one(metadata)
        file_metadata_id = metadata_file.inserted_id

        if existing_product.get("FileId"):
            old_file_metadata = files_products_collection.find_one({"_id": existing_product["FileId"]})
            if old_file_metadata:
                try:
                    products_fs.delete(old_file_metadata["file_id"])
                    files_products_collection.delete_one({"_id": existing_product["FileId"]})
                except Exception as e:
                    print(f"Error deleting old file: {str(e)}")

        updated_fields["FileId"] = file_metadata_id
        upload_progress[upload_id] = 50
    else:
        upload_progress[upload_id] = 50

    # Барои маҳсулоти физикӣ
    if product_type == "physical":
        # Агар маҳсулоти физикӣ бошад ва ном тағйир ёфта бошад
        if physical_product_name and physical_product_name != existing_product.get("PhysicalProductName", ""):
            updated_fields["PhysicalProductName"] = physical_product_name
        
        # Маълумоти расонидан
        if physical_delivery_method != existing_product.get("PhysicalDeliveryMethod", "pickup"):
            updated_fields["PhysicalDeliveryMethod"] = physical_delivery_method
        
        if physical_pickup_address and physical_pickup_address != existing_product.get("PhysicalPickupAddress", ""):
            updated_fields["PhysicalPickupAddress"] = physical_pickup_address
        
        if physical_courier_available != existing_product.get("PhysicalCourierAvailable", False):
            updated_fields["PhysicalCourierAvailable"] = physical_courier_available

        # Агар қаблан файл дошт ва ҳоло маҳсулоти физикӣ аст, файлро тоза кунем
        if existing_product.get("FileId"):
            # Тоза кардани файли кӯҳна
            old_file_metadata = files_products_collection.find_one({"_id": existing_product["FileId"]})
            if old_file_metadata:
                try:
                    products_fs.delete(old_file_metadata["file_id"])
                    files_products_collection.delete_one({"_id": existing_product["FileId"]})
                except Exception as e:
                    print(f"Error deleting old file: {str(e)}")
            updated_fields["FileId"] = None

    elif product_type != 'physical':
        updated_fields["PhysicalProductName"] = None

    # ================= NEW IMAGES =================
    new_image_ids = []
    
    if images:
        total_images = len(images)
        current_progress = 50

        for idx, image in enumerate(images):
            try:
                # Read file in 1MB chunks
                chunks = []
                total_size = 0
                
                while True:
                    chunk = await image.read(1024 * 1024)  # 1MB chunks
                    if not chunk:
                        break
                    chunks.append(chunk)
                    total_size += len(chunk)
                
                image_bytes = b''.join(chunks)
                
                # Progress simulation
                for i in range(0, total_size, 256 * 1024):
                    uploaded_size = min(i + 256 * 1024, total_size)
                    image_progress = (idx / total_images) + (uploaded_size / total_size) * (1 / total_images)
                    progress = current_progress + (image_progress * 49)
                    upload_progress[upload_id] = min(progress, 98.9)
                    await asyncio.sleep(0.01)

                # Save image
                image_id = products_fs.put(
                    image_bytes,
                    filename=f"product_{user_id}_{datetime.datetime.now(datetime.timezone.utc).timestamp()}_{idx}",
                    content_type=image.content_type or "image/jpeg",
                    uploadDate=datetime.datetime.now(datetime.timezone.utc)
                )
                new_image_ids.append(image_id)
                print(f"✅ New image {idx} uploaded with ID: {image_id}")
                    
            except Exception as e:
                print(f"❌ Error processing image {idx}: {str(e)}")
                continue

        # Combine remaining old images and new images
        combined_image_ids = old_image_ids + new_image_ids
        updated_fields["ProductImageIds"] = combined_image_ids
        print(f"📸 Final image IDs: {combined_image_ids}")

    # ================= COLLABORATION =================
    current_collaborators = [
        str(x) for x in existing_product.get("CollaborationShopings", [])
    ]

    valid_collaborators = [
        shop_id for shop_id in collaboration_shopings
        if ObjectId.is_valid(shop_id)
    ]

    new_collaborators = [
        shop_id for shop_id in valid_collaborators
        if shop_id not in current_collaborators
    ]

    user = users_collection.find_one({"_id": ObjectId(user_id)})
    encrypted_collaboration_type = encrypt_data("collaboration", ENCRYPTION_KEY)

    for shop_id in new_collaborators:
        shoping_data = shopings_collection.find_one({"_id": ObjectId(shop_id)})

        shoping_name = shoping_data['ShopingName']
        account_id = shoping_data['UserId']  # ID of the shop owner

        encrypted_collaboration_message = encrypt_data(f"@{user.get('Username')} wants to collaborate their product in shop ${shoping_name}. View product: {existing_product['Link']}", ENCRYPTION_KEY)

        notification_doc = {
            "NotificationFrom": ObjectId(user_id),
            "NotificationTo": ObjectId(account_id),
            "ShopingId": ObjectId(shop_id),
            "Message": encrypted_collaboration_message,
            "PostId": product_id,
            "IsRead": False,
            "UploadAt": datetime.datetime.now(datetime.timezone.utc).isoformat().replace('Z', '+00:00'),
            "Type": encrypted_collaboration_type,
            "status": "pending"
        }
        notifications_collection.insert_one(notification_doc)
        serialized_notification = serialize_notification(notification_doc)
        await broadcast_notification(str(account_id), "add", serialized_notification)

    # For account
    if user_id_for_sell:
        updated_fields["UserIdForSell"] = ObjectId(user_id_for_sell)

    # UPDATE TIME
    updated_fields["UpdateAt"] = datetime.datetime.now(datetime.timezone.utc).isoformat().replace('Z', '+00:00')

    # ================= UPDATE =================
    if updated_fields:
        products_collection.update_one(
            {"_id": ObjectId(product_id)},
            {"$set": updated_fields}
        )
        print(f"✅ Product updated with fields: {list(updated_fields.keys())}")

    upload_progress[upload_id] = 100
    await asyncio.sleep(2)
    upload_progress.pop(upload_id, None)

    return {
        "message": "Product updated successfully", 
        "product_id": product_id,
        "advertisement": {
            "old_count": old_ad_count,
            "new_count": new_ad_count,
            "difference": count_difference,
            "charged_for": max(0, count_difference)
        }
    }

class EmailVerification(BaseModel):
    email: str
    code: str
    username: str

@router.post("/verify-email-for-account-sale")
async def verify_email(verification: EmailVerification):
    user = users_collection.find_one({"Username": verification.username})
    # Find the temporary data
    temp_data = temp_codes_db.find_one({
        "email": user["Email"], 
        'username': verification.username
    })

    if not temp_data:
        raise HTTPException(
            status_code=400,
            detail="No verification request found or invalid code."
        )

    # Get user's encryption key
    user = users_collection.find_one({"Username": verification.username})
    if not user:
        raise HTTPException(status_code=402, detail="User not found")

    # Decrypt the stored code
    decrypted_code = decrypt_data(temp_data["code"], ENCRYPTION_KEY)

    # Compare with user input
    if decrypted_code != verification.code:
        raise HTTPException(
            status_code=400,
            detail="No verification request found or invalid code."
        )

    # In verify_email function, add this check:
    elif temp_data["created_at"] < datetime.datetime.now(datetime.timezone.utc) - timedelta(minutes=10):
        temp_codes_db.delete_many({"username": verification.username})
        raise HTTPException(status_code=401, detail="Verification code has expired")

    # Clean up temporary data
    temp_codes_db.delete_many({"username": verification.username})

    return {
        "message": "Verification successful", 
        "user_id": str(user['_id'])  # Convert to string
    }
