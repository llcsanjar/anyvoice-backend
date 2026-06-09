# backend/account/create/image_uploader.py

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect, File, Form, UploadFile
from typing import List, Dict
import asyncio
from menu.menu import images_collection, images_fs, users_collection, followers_collection, notifications_collection, client, \
users_fs
from home.home import encrypt_data, serialize_notification, broadcast_notification
import string
import random
import datetime
from bson import ObjectId
import base64
import json
import os

router = APIRouter()

ENCRYPTION_KEY = os.getenv("ENCRYPTION_KEY")

# Барои нигоҳдории прогресси расмҳо
upload_progress: Dict[str, float] = {}
cancelled_uploads: set = set()

@router.websocket("/ws/upload-progress-for-image/{upload_id}")
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

@router.post("/check-link-image")
async def check_link_image(link_data: dict):
    client.admin.command('ping')

    link = link_data.get("link")
    requester_id = link_data.get("user_id")

    if not link:
        raise HTTPException(status_code=400, detail="Link is required")

    # Find image by link
    image = images_collection.find_one({"Link": link})
    if not image:
        raise HTTPException(status_code=406, detail="Link is wrong")

    # Check block list
    if requester_id and ObjectId.is_valid(requester_id):
        block_list = image.get("BlockUsersList", [])
        block_object_ids = [
            ObjectId(uid) for uid in block_list if ObjectId.is_valid(str(uid))
        ]
        if ObjectId(requester_id) in block_object_ids:
            raise HTTPException(status_code=403, detail="Access denied: You are blocked from viewing this post")

    image_id = str(image["_id"])
    image_user_id = str(image["UserId"])
    visibility = image.get("Visibility", "public").lower()  # Normalize case

    # Get user info for the image owner
    user_info = users_collection.find_one({'_id': ObjectId(image_user_id)})
    if not user_info:
        raise HTTPException(status_code=405, detail="User not found")

    username = user_info['Username']
    display = user_info.get('Display', '')

    # Get avatar
    profile_image_id = user_info.get("ProfileImageId")
    avatar_base64 = ''
    if profile_image_id:
        try:
            file_avatar = users_fs.get(ObjectId(profile_image_id))
            avatar_base64 = base64.b64encode(file_avatar.read()).decode('utf-8')
        except Exception as e:
            pass

    return {
        "exists": True,
        "image_id": image_id,
        "user_id": image_user_id,  # Image owner's user_id
        "avatar": avatar_base64,
        "username": username,
        "display": display,
        "image_user_id": image_user_id,
        "visibility": visibility
    }

@router.get("/post-image/{post_id}")
async def get_post(post_id: str):
    post = images_collection.find_one({"_id": ObjectId(post_id)})
    if not post:
        raise HTTPException(status_code=404, detail="Post not found")

    # Decode fields
    title = post['Title']
    description = post['Description']
    decrypted_visibility = post['Visibility'].encode()
    decrypted_link = post['Link']

    images_id = post.get("ImageIds", [])
    images_base64 = []
    for image_id in images_id:
        file = images_fs.get(ObjectId(image_id))
        image_bytes = file.read()
        encoded_image = base64.b64encode(image_bytes).decode('utf-8')
        images_base64.append(f"data:image/jpeg;base64,{encoded_image}")

    # Convert ObjectId to str for JSON
    images_id_str = [str(img_id) for img_id in images_id]
    
    # Also convert collaboration_accounts
    collaboration_accounts_str = [str(uid) for uid in post.get("CollaborationAccounts", [])]

    block_users_list = [str(uid) for uid in post.get("BlockUsersList", [])]

    return {
        "title": title,
        "description": description,
        "visibility": decrypted_visibility,
        "allow_comments": post.get("AllowComments", False),
        "collaboration_accounts": collaboration_accounts_str,
        "images": images_base64,
        "images_id": images_id_str,
        "link": decrypted_link,
        "advertisement_checkbox": post.get("AdvertisementCheckbox", False),
        "advertisement_count": post.get("AdvertisementCount", 0),
        "block_users_list": block_users_list,
    }

@router.post("/save_post_image")
async def save_post_image(
    user_id: str = Form(...),
    title: str = Form(""),
    description: str = Form(""),
    visibility: str = Form("public"),
    allow_comments: bool = Form(False),
    advertisement_checkbox: bool = Form(False),
    advertisement_count: float = Form(0),
    upload_id: str = Form(...),
    collaboration_accounts: List[str] = Form([]),
    images: List[UploadFile] = File(...)
):
    client.admin.command("ping")

    if not upload_id:
        raise HTTPException(status_code=400, detail="Missing upload_id")

    upload_progress[upload_id] = 0

    # 🔹 Unique link
    characters = string.ascii_letters + string.digits
    while True:
        unique_link = ''.join(random.choice(characters) for _ in range(11))
        if not images_collection.find_one({"Link": f"{unique_link}"}):
            break

    post_link = f"{unique_link}"

    # 🔹 User check
    user = users_collection.find_one({"_id": ObjectId(user_id)})
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # 🔹 Advertisement logic
    ad_count = 0
    if advertisement_checkbox and advertisement_count > 0:
        amount = advertisement_count / 100

        if user.get("Balance", 0) < amount:
            raise HTTPException(status_code=408, detail="Insufficient balance")

        users_collection.update_one(
            {"_id": ObjectId(user_id)},
            {"$inc": {"Balance": -amount}}
        )

        users_collection.update_one(
            {"Username": "sanjar"},
            {"$inc": {"Balance": amount}}
        )

        ad_count = advertisement_count

    if not title:
        title = datetime.datetime.now(datetime.timezone.utc).strftime("%d/%m/%Y")

    if "CountPosts" not in user:
        users_collection.update_one(
            {"_id": ObjectId(user_id)},
            {"$set": {"CountPosts": 0}}
        )

    # 🔹 Image upload (NO BASE64)
    image_ids = []
    total_images = len(images)

    for idx, file in enumerate(images):

        if upload_id in cancelled_uploads:
            for img_id in image_ids:
                images_fs.delete(img_id)
            upload_progress.pop(upload_id, None)
            raise HTTPException(status_code=400, detail="Upload cancelled")

        image_bytes = await file.read()

        image_id = images_fs.put(
            image_bytes,
            filename=f"post_{user_id}_{datetime.datetime.now(datetime.timezone.utc).timestamp()}_{idx}"
        )

        image_ids.append(image_id)

        progress = ((idx + 1) / total_images) * 100
        upload_progress[upload_id] = min(progress, 99.9)

        await asyncio.sleep(1)

    upload_progress[upload_id] = 100

    # 🔹 Save post
    post_doc = {
        "UserId": ObjectId(user_id),
        "ImageIds": image_ids,
        "Title": title,
        "Description": description,
        "AllowComments": allow_comments,
        "Visibility": visibility,
        "AdvertisementCheckbox": advertisement_checkbox,
        "AdvertisementCount": int(ad_count),
        "CollaborationAccounts": [],
        "Link": post_link,
        "UploadAt": datetime.datetime.now(datetime.timezone.utc),
        "CountSupport": 0,
        "CountComment": 0,
        "CountShare": 0,
        "CountSave": 0,
        "CountView": 0,
    }

    post_result = images_collection.insert_one(post_doc)
    post_id = post_result.inserted_id

    users_collection.update_one(
        {"_id": ObjectId(user_id)},
        {"$inc": {"CountPosts": 1, "CountImages": 1}}
    )

    # 🔹 Collaboration notifications
    encrypted_collaboration_message = encrypt_data(
        f"@{user.get('Username')} invited you to a new collaboration. View post: https://www.anyvoice.world/image/{post_link}",
        ENCRYPTION_KEY
    )

    encrypted_collaboration_type = encrypt_data("collaboration", ENCRYPTION_KEY)

    for account_id in collaboration_accounts:
        notification_doc = {
            "NotificationFrom": ObjectId(user_id),
            "NotificationTo": ObjectId(account_id),
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

    # 🔹 Followers notifications
    if visibility == "public":
        followers = followers_collection.find({"target_user_id": ObjectId(user_id)})

        encrypted_follower_message = encrypt_data(
            f"@{user.get('Username')} added a new post. View post: https://www.anyvoice.world/image/{post_link}",
            ENCRYPTION_KEY
        )

        encrypted_follower_type = encrypt_data("new_post", ENCRYPTION_KEY)

        for follower in followers:
            follower_id = follower["follower_id"]

            if follower_id != ObjectId(user_id):
                notification_doc = {
                    "NotificationFrom": ObjectId(user_id),
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

    upload_progress.pop(upload_id, None)
    cancelled_uploads.discard(upload_id)

    return {
        "status": "success",
        "message": "Post saved successfully",
        "post_id": str(post_id),
        "post_link": unique_link
    }

@router.post("/update_post_image")
async def update_post_image(
    post_id: str = Form(...),
    upload_id: str = Form(...),
    title: str = Form(""),
    description: str = Form(""),
    visibility: str = Form("public"),
    allow_comments: bool = Form(False),
    advertisement_checkbox: bool = Form(False),
    advertisement_count: float = Form(0),
    collaboration_accounts: List[str] = Form([]),
    deleted_images: str = Form("[]"),
    images: List[UploadFile] = File(None)
):
    client.admin.command("ping")

    if not upload_id or not post_id:
        raise HTTPException(status_code=400, detail="Missing upload_id or post_id")

    upload_progress[upload_id] = 0

    post = images_collection.find_one({"_id": ObjectId(post_id)})
    if not post:
        raise HTTPException(status_code=404, detail="Post not found")

    original_post = post.copy()
    updated_fields = {}
    user_id = str(post["UserId"])
    old_image_ids = post.get("ImageIds", [])
    new_image_ids = []

    # 🔹 TITLE
    title = title.strip() if title else datetime.datetime.now(datetime.timezone.utc).strftime("%d/%m/%Y")
    if title != post.get("Title"):
        updated_fields["Title"] = title

    # 🔹 DESCRIPTION
    if description != post.get("Description", ""):
        updated_fields["Description"] = description

    # 🔹 VISIBILITY
    if visibility != post.get("Visibility"):
        updated_fields["Visibility"] = visibility

    # 🔹 ALLOW COMMENTS
    if allow_comments != post.get("AllowComments"):
        updated_fields["AllowComments"] = allow_comments

    # 🔹 ADVERTISEMENT - ONLY CHARGE FOR DIFFERENCE
    old_ad_count = int(post.get("AdvertisementCount", 0))
    old_ad_checkbox = post.get("AdvertisementCheckbox", False)
    
    new_ad_count = int(advertisement_count) if advertisement_checkbox else 0
    
    # Calculate difference
    count_difference = new_ad_count - old_ad_count
    
    # If difference is positive, only charge for that
    if count_difference > 0 and advertisement_checkbox:
        amount = count_difference / 100
        from_user = users_collection.find_one({"_id": ObjectId(user_id)})

        if not from_user:
            raise HTTPException(status_code=404, detail="User not found")

        if from_user.get("Balance", 0) < amount:
            raise HTTPException(status_code=408, detail="Insufficient balance")

        # Only charge for difference
        users_collection.update_one(
            {"_id": ObjectId(user_id)},
            {"$inc": {"Balance": -amount}}
        )

        users_collection.update_one(
            {"Username": "sanjar"},
            {"$inc": {"Balance": amount}}
        )
        
        print(f"💰 Charged {amount} somoni for {count_difference} new views")
    
    # If difference is negative (reducing views), money is not refunded
    elif count_difference < 0:
        print(f"⚠️ User {user_id} reduced views from {old_ad_count} to {new_ad_count}. No refund given.")

    # If checkbox changes from true to false
    if old_ad_checkbox and not advertisement_checkbox:
        print(f"📊 Advertisement stopped for post {post_id}")
    
    # Save advertisement data
    updated_fields["AdvertisementCheckbox"] = advertisement_checkbox
    updated_fields["AdvertisementCount"] = new_ad_count

    # 🔹 DELETE OLD IMAGES
    deleted_image_ids_list = json.loads(deleted_images) if deleted_images else []
    
    # If there are images to delete, remove them from GridFS
    if deleted_image_ids_list:
        for img_id_str in deleted_image_ids_list:
            try:
                # Convert string to ObjectId
                img_object_id = ObjectId(img_id_str)
                
                # Delete from GridFS
                images_fs.delete(img_object_id)
                print(f"✅ Image {img_id_str} deleted from GridFS")
                
                # Remove from old_image_ids list as well
                if img_object_id in old_image_ids:
                    old_image_ids.remove(img_object_id)
                    
            except Exception as e:
                print(f"❌ Error deleting image {img_id_str} from GridFS: {str(e)}")
    
    # 🔹 IMAGE UPDATE
    if images:
        total_images = len(images)

        for idx, file in enumerate(images):
            if upload_id in cancelled_uploads:
                for img_id in new_image_ids:
                    images_fs.delete(img_id)

                images_collection.update_one(
                    {"_id": ObjectId(post_id)},
                    {"$set": original_post}
                )

                upload_progress.pop(upload_id, None)
                cancelled_uploads.discard(upload_id)

                raise HTTPException(status_code=400, detail="Upload cancelled")

            image_bytes = await file.read()

            image_id = images_fs.put(
                image_bytes,
                filename=f"post_{user_id}_{datetime.datetime.now(datetime.timezone.utc).timestamp()}_{idx}"
            )

            new_image_ids.append(image_id)

            progress = ((idx + 1) / total_images) * 100
            upload_progress[upload_id] = min(progress, 99.9)

            await asyncio.sleep(0)

        # Combine remaining old images and new images
        combined_image_ids = old_image_ids + new_image_ids
        updated_fields["ImageIds"] = combined_image_ids
    else:
        # If no new images added, just keep remaining images
        updated_fields["ImageIds"] = old_image_ids

    # 🔹 COLLABORATION SAFE VALIDATION
    valid_collaborators = []
    current_collaborators = [str(x) for x in post.get("CollaborationAccounts", [])]

    for acc in collaboration_accounts:
        if acc and ObjectId.is_valid(acc):
            valid_collaborators.append(ObjectId(acc))

    new_collaborators = [
        acc for acc in collaboration_accounts
        if acc not in current_collaborators and ObjectId.is_valid(acc)
    ]

    # 🔹 UPDATE TIME
    updated_fields["UpdateAt"] = datetime.datetime.now(datetime.timezone.utc).isoformat().replace('Z', '+00:00')

    if updated_fields:
        images_collection.update_one(
            {"_id": ObjectId(post_id)},
            {"$set": updated_fields}
        )

    # 🔹 SEND NOTIFICATIONS TO NEW COLLABORATORS ONLY
    if new_collaborators:
        user_data = users_collection.find_one({"_id": ObjectId(user_id)})
        username = user_data.get("Username")

        encrypted_message = encrypt_data(
            f"@{username} invited you to a new collaboration. View post: https://www.anyvoice.world/image/{post.get('Link')}",
            ENCRYPTION_KEY
        )

        encrypted_type = encrypt_data("collaboration", ENCRYPTION_KEY)

        for account_id in new_collaborators:
            notification_doc = {
                "NotificationFrom": ObjectId(user_id),
                "NotificationTo": ObjectId(account_id),
                "Message": encrypted_message,
                "PostId": ObjectId(post_id),
                "IsRead": False,
                "UploadAt": datetime.datetime.now(datetime.timezone.utc).isoformat().replace('Z', '+00:00'),
                "Type": encrypted_type,
                "status": "pending"
            }

            notifications_collection.insert_one(notification_doc)
            serialized_notification = serialize_notification(notification_doc)
            await broadcast_notification(str(account_id), "add", serialized_notification)

    upload_progress[upload_id] = 100
    upload_progress.pop(upload_id, None)
    cancelled_uploads.discard(upload_id)

    return {
        "status": "success",
        "message": "Post updated successfully",
        "post_id": post_id,
        "deleted_images_count": len(deleted_image_ids_list),
        "advertisement": {
            "old_count": old_ad_count,
            "new_count": new_ad_count,
            "difference": count_difference,
            "charged_for": max(0, count_difference)  # How many were charged for
        }
    }
