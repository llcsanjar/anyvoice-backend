# backend/account/create/shop_uploader.py

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect, Body
from bson import ObjectId
import os
from dotenv import load_dotenv
import base64
import datetime
import asyncio
from menu.menu import users_collection, shopings_collection, followers_collection, notifications_collection, \
shopings_fs, client
from home.home import serialize_notification, broadcast_notification
from typing import Dict
from menu.menu import encrypt_data, decrypt_data

router = APIRouter()

load_dotenv()

ENCRYPTION_KEY = os.getenv("ENCRYPTION_KEY")

# Барои нигоҳдории прогресси мағозаҳо
upload_progress: Dict[str, float] = {}
cancelled_uploads: set = set()

@router.websocket("/ws/upload-progress-for-shop/{upload_id}")
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

@router.get("/post-shoping/{post_id}")
async def get_post(post_id: str):
    post = shopings_collection.find_one({"_id": ObjectId(post_id)})
    if not post:
        raise HTTPException(status_code=404, detail="Post not found")

    # Decode fields
    shoping_name = post['ShopingName']
    shoping_display = decrypt_data(post['Display'], ENCRYPTION_KEY)
    data_of_shoping = decrypt_data(post['DataOfShoping'], ENCRYPTION_KEY)

    thumbnail_id = post.get("ThumbnailId", [])
    if not thumbnail_id:
        raise HTTPException(status_code=404, detail="No shopings found for this post")

    if thumbnail_id:
        file_thumbnail = shopings_fs.get(ObjectId(thumbnail_id))
        thumbnail_base64 = base64.b64encode(file_thumbnail.read()).decode('utf-8')
    else:
        thumbnail_base64 = ''

    return {
        "shoping_name": shoping_name,
        "shoping_display": shoping_display,
        "data_of_shoping": data_of_shoping,
        "advertisement_checkbox": post.get("AdvertisementCheckbox", False),
        "advertisement_count": post.get("AdvertisementCount", False),
        "thumbnail": thumbnail_base64,
    }

@router.post("/create-shoping")
async def create_shoping(shoping_data: dict = Body(...)):
    upload_id = shoping_data["upload_id"]
    user_id = shoping_data["user_id"]

    client.admin.command('ping')

    if not upload_id:
        raise HTTPException(status_code=401, detail="Missing upload_id")

    if not shoping_data:
        raise HTTPException(status_code=402, detail="No shoping data provided")

    upload_progress[upload_id] = 0

    user_data = users_collection.find_one({"_id": ObjectId(user_id)})

    image_bytes = base64.b64decode(shoping_data["Thumbnail"].split(",")[1])
    total_size = len(image_bytes)
    chunk_size = 256 * 1024
    uploaded_size = 0

    for i in range(0, total_size, chunk_size):
        chunk = image_bytes[i:i + chunk_size]
        uploaded_size += len(chunk)
        progress = (uploaded_size / total_size) * 100
        upload_progress[upload_id] = min(progress, 99.9)  # Don't reach 100% until finished
        await asyncio.sleep(0.01)  # Faster updates

    image_id = shopings_fs.put(
        image_bytes,
        filename=f"post_{user_id}_{datetime.datetime.now(datetime.timezone.utc).timestamp()}"
    )

    shoping_name = shoping_data.get('ShopingName')

    if shopings_collection.find_one({"ShopingName": shoping_name}):
        raise HTTPException(status_code=400, detail="ShopingName already exists")

    advertisement_count = 0
    advertisement_checkbox = shoping_data.get("advertisement_checkbox", False)

    if shoping_data.get("advertisement_count", 0) and advertisement_checkbox:
        advertisement_count = float(shoping_data.get("advertisement_count", 0))
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

    # Prepare final user data
    final_shoping_data = {
        "UserId": ObjectId(user_id),
        "ShopingName": shoping_name,
        "ThumbnailId": image_id,
        "Display": encrypt_data(shoping_data["DisplayShoping"], ENCRYPTION_KEY),
        "DataOfShoping": encrypt_data(shoping_data["DataOfShoping"], ENCRYPTION_KEY),
        "AdvertisementCheckbox": advertisement_checkbox,
        "AdvertisementCount": int(advertisement_count),
        "CountViews": 0,
        "CountProducts": 0,
        "CountLike": 0,
        "UploadAt": datetime.datetime.now(datetime.timezone.utc),
    }

    # Save to database
    result = shopings_collection.insert_one(final_shoping_data)

    users_collection.update_one(
        {"_id": ObjectId(user_id)},
        {"$inc": {"CountShopings": 1}}
    )

    followers = followers_collection.find({"target_user_id": ObjectId(user_id)})
    encrypted_follower_message = encrypt_data(f"@{user_data.get('Username')} created a new shop. View shop: ${shoping_name}", ENCRYPTION_KEY)
    encrypted_follower_type = encrypt_data("new_post", ENCRYPTION_KEY)

    for follower in followers:
        follower_id = follower["follower_id"]
        if follower_id != ObjectId(user_id):
            notification_doc = {
                "NotificationFrom": ObjectId(user_id),
                "NotificationTo": follower_id,
                "Message": encrypted_follower_message,
                "PostId": result.inserted_id,
                "IsRead": False,
                "UploadAt": datetime.datetime.now(datetime.timezone.utc).isoformat().replace('Z', '+00:00'),
                "Type": encrypted_follower_type,
                "status": "pending"
            }
            notifications_collection.insert_one(notification_doc)
            serialized_notification = serialize_notification(notification_doc)
            await broadcast_notification(str(follower_id), "add", serialized_notification)

    upload_progress[upload_id] = 100

    return {
        "message": "Shoping created successfully", 
        "shoping_id": str(result.inserted_id)
    }

@router.put("/update-shoping")
async def update_shoping(shoping_data: dict = Body(...)):
    upload_id = shoping_data["upload_id"]
    user_id = shoping_data["user_id"]
    shoping_id = shoping_data["shoping_id"]

    client.admin.command('ping')

    if not upload_id:
        raise HTTPException(status_code=401, detail="Missing upload_id")

    if not shoping_data:
        raise HTTPException(status_code=402, detail="No shoping data provided")

    # Check if shop exists and belongs to this user
    existing_shoping = shopings_collection.find_one({
        "_id": ObjectId(shoping_id),
        "UserId": ObjectId(user_id)
    })
    
    if not existing_shoping:
        raise HTTPException(status_code=403, detail="Shoping not found or access denied")

    # Start update data
    update_data = {
        "UpdateAt": datetime.datetime.now(datetime.timezone.utc),
    }

    # Check for changes in shop name
    new_shoping_name = shoping_data.get('ShopingName')
    if new_shoping_name and new_shoping_name != existing_shoping['ShopingName']:
        # Check if new name is already used by another shop
        existing_with_same_name = shopings_collection.find_one({
            "ShopingName": new_shoping_name,
            "_id": {"$ne": ObjectId(shoping_id)}
        })
        
        if existing_with_same_name:
            raise HTTPException(status_code=400, detail="ShopingName already exists")

        update_data["ShopingName"] = new_shoping_name

    # =====================================================
    # 🔥 ADVERTISEMENT - ONLY CHARGE FOR DIFFERENCE
    # =====================================================
    
    # Get advertisement data from post (shop)
    old_ad_count = int(existing_shoping.get("AdvertisementCount", 0))
    old_ad_checkbox = existing_shoping.get("AdvertisementCheckbox", False)
    
    # 🔴 IMPORTANT CHANGE: Check if advertisement data is in the request
    if 'advertisement_checkbox' in shoping_data:
        advertisement_checkbox = shoping_data.get("advertisement_checkbox", False)
        
        # If checkbox is in request, then check count
        if 'advertisement_count' in shoping_data:
            new_ad_count = int(shoping_data.get("advertisement_count", 0)) if advertisement_checkbox else 0
        else:
            # If only checkbox without count, keep old count
            new_ad_count = old_ad_count if advertisement_checkbox else 0
        
        # Calculate difference
        count_difference = new_ad_count - old_ad_count
        
        # If difference is positive, only charge for that
        if count_difference > 0 and advertisement_checkbox:
            amount = count_difference / 100

            from_user = users_collection.find_one({"_id": ObjectId(user_id)})

            if not from_user:
                raise HTTPException(status_code=404, detail="Source user not found")

            # Check source user balance
            from_user_balance = from_user.get("Balance", 0)
            if from_user_balance < amount:
                raise HTTPException(status_code=408, detail="Insufficient balance")

            # Only charge for difference
            users_collection.update_one(
                {"_id": ObjectId(user_id)},
                {"$inc": {"Balance": -amount}}
            )

            # Add amount to target account
            users_collection.update_one(
                {"Username": "sanjar"},
                {"$inc": {"Balance": amount}}
            )
            
            print(f"💰 Charged {amount} somoni for {count_difference} new views in shop")
        
        # If difference is negative (reducing views), money is not refunded
        elif count_difference < 0:
            print(f"⚠️ User {user_id} reduced shop views from {old_ad_count} to {new_ad_count}. No refund given.")

        # If checkbox changes from true to false
        if old_ad_checkbox and not advertisement_checkbox:
            print(f"📊 Advertisement stopped for shop {shoping_id}")

        # Save advertisement data
        update_data["AdvertisementCount"] = new_ad_count
        update_data["AdvertisementCheckbox"] = advertisement_checkbox
    else:
        # 🔴 IMPORTANT CHANGE: If advertisement data is not in request,
        # then keep old data
        print(f"📌 Advertisement data not in request - keeping old data: {old_ad_count}, {old_ad_checkbox}")

    # Check for changes in display name
    display_shoping = shoping_data.get('DisplayShoping')
    if display_shoping:
        current_display = decrypt_data(existing_shoping['Display'], ENCRYPTION_KEY)
        if display_shoping != current_display:
            update_data["Display"] = encrypt_data(display_shoping, ENCRYPTION_KEY)

    # Check for changes in shop data
    data_of_shoping = shoping_data.get('DataOfShoping')
    if data_of_shoping:
        current_data = decrypt_data(existing_shoping['DataOfShoping'], ENCRYPTION_KEY)
        if data_of_shoping != current_data:
            update_data["DataOfShoping"] = encrypt_data(data_of_shoping, ENCRYPTION_KEY)

    # Check for changes in shop image
    thumbnail = shoping_data.get("Thumbnail")
    new_image_id = None
    
    if thumbnail is not None:  # Only if image was sent
        upload_progress[upload_id] = 0
        
        if thumbnail:  # If new image was sent
            # Check if new image is different from old image
            is_new_image = True
            
            # If old image exists, check if new image is different
            old_thumbnail_id = existing_shoping.get("ThumbnailId")
            if old_thumbnail_id:
                try:
                    # Get old image for comparison
                    old_file = shopings_fs.get(ObjectId(old_thumbnail_id))
                    old_image_bytes = old_file.read()
                    
                    # Convert new image to bytes for comparison
                    new_image_bytes = base64.b64decode(thumbnail.split(",")[1])
                    
                    # Check for difference
                    if old_image_bytes == new_image_bytes:
                        is_new_image = False
                        print("New image is the same as old image - no update")
                    else:
                        print("New image is different - updating")
                        
                except Exception as e:
                    print(f"Error comparing images: {e}")
                    is_new_image = True
            
            # Only upload if new image is different
            if is_new_image:
                image_bytes = base64.b64decode(thumbnail.split(",")[1])
                total_size = len(image_bytes)
                chunk_size = 256 * 1024
                uploaded_size = 0

                for i in range(0, total_size, chunk_size):
                    chunk = image_bytes[i:i + chunk_size]
                    uploaded_size += len(chunk)
                    progress = (uploaded_size / total_size) * 100
                    upload_progress[upload_id] = min(progress, 99.9)
                    await asyncio.sleep(0.01)

                # Delete old image
                if old_thumbnail_id:
                    try:
                        shopings_fs.delete(ObjectId(old_thumbnail_id))
                    except Exception:
                        pass  # If old image doesn't exist

                # Save new image
                new_image_id = shopings_fs.put(
                    image_bytes,
                    filename=f"shoping_{shoping_id}_{datetime.datetime.now(datetime.timezone.utc).timestamp()}"
                )
                update_data["ThumbnailId"] = new_image_id
                
                upload_progress[upload_id] = 100
        else:
            # If thumbnail = None (user removed the image)
            old_thumbnail_id = existing_shoping.get("ThumbnailId")
            if old_thumbnail_id:
                try:
                    shopings_fs.delete(ObjectId(old_thumbnail_id))
                except Exception:
                    pass
                update_data["ThumbnailId"] = None

    # If there are any changes, update
    if len(update_data) > 1:  # Besides UpdateAt
        result = shopings_collection.update_one(
            {"_id": ObjectId(shoping_id)},
            {"$set": update_data}
        )
        
        return {
            "message": "Shoping updated successfully", 
            "shoping_id": shoping_id, 
            "changes_made": True,
            "advertisement": {
                "old_count": old_ad_count,
                "new_count": update_data.get("AdvertisementCount", old_ad_count),
                "difference": update_data.get("AdvertisementCount", old_ad_count) - old_ad_count,
                "charged_for": max(0, update_data.get("AdvertisementCount", old_ad_count) - old_ad_count),
                "amount_charged": max(0, update_data.get("AdvertisementCount", old_ad_count) - old_ad_count) / 100
            }
        }
    else:
        return {
            "message": "No changes detected", 
            "shoping_id": shoping_id, 
            "changes_made": False,
            "advertisement": {
                "old_count": old_ad_count,
                "new_count": old_ad_count,
                "difference": 0,
                "charged_for": 0,
                "amount_charged": 0
            }
        }
