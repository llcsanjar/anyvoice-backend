# backend/explore/comment.py

from fastapi import APIRouter, HTTPException, Query
import os
import base64
from bson import ObjectId
import datetime
from pydantic import BaseModel
from typing import Optional
import json
import re
from account.account import manager_account
from menu.menu import videos_collection, users_collection, users_fs, \
videos_comment_collection, images_comment_collection, products_comment_collection, notifications_collection, \
videos_comment_collection, videos_comment_likes, theories_comment_collection, article_comment_likes, theories_comment_likes, \
images_comment_likes, product_comment_likes, articles_collection, article_comment_collection, theory_collection, \
images_collection, products_collection, products_db
from home.home import serialize_notification, broadcast_notification
from explore.video_loader import manager_video
from explore.image_loader import manager_image
from dispute.theory.theory_loader import manager_theory
from dispute.article.article_item import manager_article
from shoping.product_loader import manager_product
from menu.menu import encrypt_data, decrypt_data

ENCRYPTION_KEY = os.getenv("ENCRYPTION_KEY")

router = APIRouter()

@router.get("/get-video-comment-like-status/{comment_id}/{user_id}")
def get_comment_like_status(comment_id: str, user_id: str):
    like = videos_comment_likes.find_one({
        "user_id": ObjectId(user_id),
        "comment_id": ObjectId(comment_id)
    })
    return {"liked": like is not None}

@router.get("/get-article-comment-like-status/{comment_id}/{user_id}")
def get_article_comment_like_status(comment_id: str, user_id: str):
    like = article_comment_likes.find_one({
        "user_id": ObjectId(user_id),
        "comment_id": ObjectId(comment_id)
    })
    return {"liked": like is not None}

@router.get("/get-theory-comment-like-status/{comment_id}/{user_id}")
def get_comment_like_status(comment_id: str, user_id: str):
    like = theories_comment_likes.find_one({
        "user_id": ObjectId(user_id),
        "comment_id": ObjectId(comment_id)
    })
    return {"liked": like is not None}

@router.get("/get-image-comment-like-status/{comment_id}/{user_id}")
def get_comment_like_status(comment_id: str, user_id: str):
    like = images_comment_likes.find_one({
        "user_id": ObjectId(user_id),
        "comment_id": ObjectId(comment_id)
    })
    return {"liked": like is not None}

@router.get("/get-product-comment-like-status/{comment_id}/{user_id}")
def get_comment_like_status(comment_id: str, user_id: str):
    like = product_comment_likes.find_one({
        "user_id": ObjectId(user_id),
        "comment_id": ObjectId(comment_id)
    })
    return {"liked": like is not None}

@router.get("/get-video-comment-by-id")
def get_video_comments(
    comment_id: str,
):
    if not ObjectId.is_valid(comment_id):
        raise HTTPException(status_code=400, detail="Invalid video ID format")

    comment = videos_comment_collection.find_one({"_id": ObjectId(comment_id)})
    if not comment:
        raise HTTPException(status_code=404, detail='Comment not found')

    user_info = users_collection.find_one({"_id": comment["user_id"]})
    if not user_info:
        raise HTTPException(status_code=402, detail='User not found')

    # Fetch updated comment data
    updated_comment = videos_comment_collection.find_one({"_id": ObjectId(comment_id)})
    if not updated_comment:
        raise HTTPException(status_code=404)

    video_user_data = videos_collection.find_one({"_id": comment["video_id"]})
    if not video_user_data:
        raise HTTPException(status_code=404)

    # Prepare comment data for broadcast
    user_info = users_collection.find_one({"_id": updated_comment["user_id"]})
    if not user_info:
        raise HTTPException(status_code=404, detail="User not found")

    decrypted_text = decrypt_data(updated_comment["text"], ENCRYPTION_KEY)

    comment_data = {
        "id": str(comment["_id"]),
        "text": decrypted_text,
        "created_at": comment["created_at"].isoformat() + "Z",
        "user_id": str(comment["user_id"]),
        "video_user_id": str(video_user_data["UserId"]),
        "username": user_info["Username"],
        "display": decrypt_data(user_info["Display"], ENCRYPTION_KEY) if user_info.get("Display") else None,
        "parent_comment_id": str(comment['parent_comment_id']) if comment['parent_comment_id'] else str(None),
        "CountReplays": comment.get('CountReplays', 0),
        "CountLike": comment.get('CountLike', 0),
        "pinned": comment.get('pinned', False),
        "is_edited": comment.get('is_edited', False),
        "edited_at": comment["edited_at"].isoformat() + "Z" if comment.get("edited_at") else None,
        "post_type": "video",
        "post_id": str(comment["video_id"]),
    }

    return {
        "comment_data": comment_data
    }

@router.get("/get-article-comment-by-id")
def get_article_comment_by_id(
    comment_id: str,
):
    if not ObjectId.is_valid(comment_id):
        raise HTTPException(status_code=400, detail="Invalid comment ID format")

    comment = article_comment_collection.find_one({"_id": ObjectId(comment_id)})
    if not comment:
        raise HTTPException(status_code=404, detail='Comment not found')

    user_info = users_collection.find_one({"_id": comment["user_id"]})
    if not user_info:
        raise HTTPException(status_code=402, detail='User not found')

    updated_comment = article_comment_collection.find_one({"_id": ObjectId(comment_id)})
    if not updated_comment:
        raise HTTPException(status_code=404)

    article_data = articles_collection.find_one({"_id": comment["article_id"]})
    if not article_data:
        raise HTTPException(status_code=404)

    # Get avatar
    avatar_base64 = ''
    if user_info.get("ProfileImageId"):
        try:
            file_avatar = users_fs.get(ObjectId(user_info["ProfileImageId"]))
            avatar_base64 = base64.b64encode(file_avatar.read()).decode('utf-8')
        except:
            pass

    decrypted_text = decrypt_data(updated_comment["text"], ENCRYPTION_KEY)

    comment_data = {
        "id": str(comment["_id"]),
        "text": decrypted_text,
        "created_at": comment["created_at"].isoformat() + "Z",
        "user_id": str(comment["user_id"]),
        "article_user_id": str(article_data["user_id"]),
        "username": user_info["Username"],
        "display": decrypt_data(user_info["Display"], ENCRYPTION_KEY) if user_info.get("Display") else None,
        "avatar": avatar_base64,
        "parent_comment_id": str(comment['parent_comment_id']) if comment['parent_comment_id'] else None,
        "CountReplays": comment.get('CountReplays', 0),
        "CountLike": comment.get('CountLike', 0),
        "pinned": comment.get('pinned', False),
        "is_edited": comment.get('is_edited', False),
        "edited_at": comment["edited_at"].isoformat() + "Z" if comment.get("edited_at") else None,
        "post_type": "article",
        "post_id": str(comment["article_id"]),
        "post_link": article_data.get('link', ''),
    }

    return {
        "comment_data": comment_data
    }

@router.get("/get-theory-comment-by-id")
def get_theory_comments(
    comment_id: str,
):
    if not ObjectId.is_valid(comment_id):
        raise HTTPException(status_code=400, detail="Invalid theory ID format")

    comment = theories_comment_collection.find_one({"_id": ObjectId(comment_id)})
    if not comment:
        raise HTTPException(status_code=404, detail='Comment not found')

    user_info = users_collection.find_one({"_id": comment["user_id"]})
    if not user_info:
        raise HTTPException(status_code=402, detail='User not found')

    # Fetch updated comment data
    updated_comment = theories_comment_collection.find_one({"_id": ObjectId(comment_id)})
    if not updated_comment:
        raise HTTPException(status_code=404)

    theory_user_data = theory_collection.find_one({"_id": comment["theory_id"]})
    if not theory_user_data:
        raise HTTPException(status_code=404)

    # Prepare comment data for broadcast
    user_info = users_collection.find_one({"_id": updated_comment["user_id"]})
    if not user_info:
        raise HTTPException(status_code=404, detail="User not found")

    decrypted_text = decrypt_data(updated_comment["text"], ENCRYPTION_KEY)

    comment_data = {
        "id": str(comment["_id"]),
        "text": decrypted_text,
        "created_at": comment["created_at"].isoformat() + "Z",
        "user_id": str(comment["user_id"]),
        "theory_user_id": str(theory_user_data["user_id"]),
        "username": user_info["Username"],
        "display": decrypt_data(user_info["Display"], ENCRYPTION_KEY) if user_info.get("Display") else None,
        "parent_comment_id": str(comment['parent_comment_id']) if comment['parent_comment_id'] else str(None),
        "CountReplays": comment.get('CountReplays', 0),
        "CountLike": comment.get('CountLike', 0),
        "pinned": comment.get('pinned', False),
        "is_edited": comment.get('is_edited', False),
        "edited_at": comment["edited_at"].isoformat() + "Z" if comment.get("edited_at") else None,
        "post_type": "theory",
        "post_id": str(comment["theory_id"]),
        "post_link": theory_user_data.get('link', ''),
    }

    return {
        "comment_data": comment_data
    }

@router.get("/get-image-comment-by-id")
def get_image_comments(
    comment_id: str,
):
    if not ObjectId.is_valid(comment_id):
        raise HTTPException(status_code=400, detail="Invalid image ID format")

    comment = images_comment_collection.find_one({"_id": ObjectId(comment_id)})
    if not comment:
        raise HTTPException(status_code=404, detail='Comment not found')

    user_info = users_collection.find_one({"_id": comment["user_id"]})
    if not user_info:
        raise HTTPException(status_code=402, detail='User not found')

    # Fetch updated comment data
    updated_comment = images_comment_collection.find_one({"_id": ObjectId(comment_id)})
    if not updated_comment:
        raise HTTPException(status_code=404)

    image_user_data = images_collection.find_one({"_id": comment["image_id"]})
    if not image_user_data:
        raise HTTPException(status_code=404)

    # Prepare comment data for broadcast
    user_info = users_collection.find_one({"_id": updated_comment["user_id"]})
    if not user_info:
        raise HTTPException(status_code=404, detail="User not found")

    decrypted_text = decrypt_data(updated_comment["text"], ENCRYPTION_KEY)

    comment_data = {
        "id": str(comment["_id"]),
        "text": decrypted_text,
        "created_at": comment["created_at"].isoformat() + "Z",
        "user_id": str(comment["user_id"]),
        "image_user_id": str(image_user_data["UserId"]),
        "username": user_info["Username"],
        "display": decrypt_data(user_info["Display"], ENCRYPTION_KEY) if user_info.get("Display") else None,
        "parent_comment_id": str(comment['parent_comment_id']) if comment['parent_comment_id'] else str(None),
        "CountReplays": comment.get('CountReplays', 0),
        "CountLike": comment.get('CountLike', 0),
        "pinned": comment.get('pinned', False),
        "is_edited": comment.get('is_edited', False),
        "edited_at": comment["edited_at"].isoformat() + "Z" if comment.get("edited_at") else None,
        "post_type": "image",
        "post_id": str(comment["image_id"]),
    }

    return {
        "comment_data": comment_data
    }

@router.get("/get-product-comment-by-id")
def get_product_comments(
    comment_id: str,
):
    if not ObjectId.is_valid(comment_id):
        raise HTTPException(status_code=400, detail="Invalid product ID format")

    comment = products_comment_collection.find_one({"_id": ObjectId(comment_id)})
    if not comment:
        raise HTTPException(status_code=404, detail='Comment not found')

    user_info = users_collection.find_one({"_id": comment["user_id"]})
    if not user_info:
        raise HTTPException(status_code=402, detail='User not found')

    # Fetch updated comment data
    updated_comment = products_comment_collection.find_one({"_id": ObjectId(comment_id)})
    if not updated_comment:
        raise HTTPException(status_code=404)

    product_user_data = products_collection.find_one({"_id": comment["product_id"]})
    if not product_user_data:
        raise HTTPException(status_code=404)

    # Prepare comment data for broadcast
    user_info = users_collection.find_one({"_id": updated_comment["user_id"]})
    if not user_info:
        raise HTTPException(status_code=404, detail="User not found")

    decrypted_text = decrypt_data(updated_comment["text"], ENCRYPTION_KEY)

    comment_data = {
        "id": str(comment["_id"]),
        "text": decrypted_text,
        "created_at": comment["created_at"].isoformat() + "Z",
        "user_id": str(comment["user_id"]),
        "product_user_id": str(product_user_data["UserId"]),
        "username": user_info["Username"],
        "display": decrypt_data(user_info["Display"], ENCRYPTION_KEY) if user_info.get("Display") else None,
        "parent_comment_id": str(comment['parent_comment_id']) if comment['parent_comment_id'] else str(None),
        "CountReplays": comment.get('CountReplays', 0),
        "CountLike": comment.get('CountLike', 0),
        "pinned": comment.get('pinned', False),
        "is_edited": comment.get('is_edited', False),
        "edited_at": comment["edited_at"].isoformat() + "Z" if comment.get("edited_at") else None,
        "post_type": "product",
        "post_id": str(comment["product_id"]),
    }

    return {
        "comment_data": comment_data
    }

@router.get("/get-video-comments/{video_id}")
def get_comments(
    video_id: str,
    offset: int = Query(0, ge=0, description="Number of comments to skip"),
    limit: int = Query(10, ge=1, le=100, description="Number of comments to return")
):
    if not ObjectId.is_valid(video_id):
        raise HTTPException(status_code=400, detail="Invalid video ID format")

    total_count = videos_comment_collection.count_documents({
        "video_id": ObjectId(video_id),
        "parent_comment_id": None
    })

    comments = list(videos_comment_collection.find({
        "video_id": ObjectId(video_id),
        "parent_comment_id": None
    }).sort([
        ("pinned", -1),
        ("created_at", -1)
    ]).skip(offset).limit(limit))

    result = []
    for comment in comments:
        user = users_collection.find_one({"_id": comment["user_id"]})
        if not user:
            continue

        comment_text = decrypt_data(comment["text"], ENCRYPTION_KEY)

        comment_data = {
            "id": str(comment["_id"]),
            "text": comment_text,
            "created_at": comment["created_at"].isoformat() + "Z",
            "user_id": str(comment["user_id"]),
            "username": user["Username"],
            "display": decrypt_data(user["Display"], ENCRYPTION_KEY) if user.get("Display") else None,
            "parent_comment_id": str(comment['parent_comment_id']) if comment['parent_comment_id'] else str(None),
            "CountReplays": comment.get('CountReplays', 0),
            "CountLike": comment.get('CountLike', 0),
            "pinned": comment.get('pinned', False),
            "is_edited": comment.get('is_edited', False),
            "edited_at": comment["edited_at"].isoformat() + "Z" if comment.get("edited_at") else None
        }

        result.append(comment_data)

    has_more = offset + len(comments) < total_count

    return {
        "comments": result,
        "total_count": total_count,
        "has_more": has_more,
        "offset": offset,
        "limit": limit
    }

@router.get("/get-article-comments/{article_id}")
def get_article_comments(
    article_id: str,
    offset: int = Query(0, ge=0, description="Number of comments to skip"),
    limit: int = Query(10, ge=1, le=100, description="Number of comments to return")
):
    if not ObjectId.is_valid(article_id):
        raise HTTPException(status_code=400, detail="Invalid article ID format")

    total_count = article_comment_collection.count_documents({
        "article_id": ObjectId(article_id),
        "parent_comment_id": None
    })

    comments = list(article_comment_collection.find({
        "article_id": ObjectId(article_id),
        "parent_comment_id": None
    }).sort([
        ("pinned", -1),
        ("created_at", -1)
    ]).skip(offset).limit(limit))

    result = []
    for comment in comments:
        user = users_collection.find_one({"_id": comment["user_id"]})
        if not user:
            continue

        comment_text = decrypt_data(comment["text"], ENCRYPTION_KEY)

        # Get avatar
        avatar_base64 = ''
        if user.get("ProfileImageId"):
            try:
                file_avatar = users_fs.get(ObjectId(user["ProfileImageId"]))
                avatar_base64 = base64.b64encode(file_avatar.read()).decode('utf-8')
            except:
                pass

        comment_data = {
            "id": str(comment["_id"]),
            "text": comment_text,
            "created_at": comment["created_at"].isoformat() + "Z",
            "user_id": str(comment["user_id"]),
            "username": user["Username"],
            "display": decrypt_data(user["Display"], ENCRYPTION_KEY) if user.get("Display") else None,
            "avatar": avatar_base64,
            "parent_comment_id": str(comment['parent_comment_id']) if comment['parent_comment_id'] else None,
            "CountReplays": comment.get('CountReplays', 0),
            "CountLike": comment.get('CountLike', 0),
            "pinned": comment.get('pinned', False),
            "is_edited": comment.get('is_edited', False),
            "edited_at": comment["edited_at"].isoformat() + "Z" if comment.get("edited_at") else None
        }

        result.append(comment_data)

    has_more = offset + len(comments) < total_count

    return {
        "comments": result,
        "total_count": total_count,
        "has_more": has_more,
        "offset": offset,
        "limit": limit
    }

@router.get("/get-theory-comments/{theory_id}")
def get_comments(
    theory_id: str,
    offset: int = Query(0, ge=0, description="Number of comments to skip"),
    limit: int = Query(10, ge=1, le=100, description="Number of comments to return")
):
    if not ObjectId.is_valid(theory_id):
        raise HTTPException(status_code=400, detail="Invalid theory ID format")

    total_count = theories_comment_collection.count_documents({
        "theory_id": ObjectId(theory_id),
        "parent_comment_id": None
    })

    comments = list(theories_comment_collection.find({
        "theory_id": ObjectId(theory_id),
        "parent_comment_id": None
    }).sort([
        ("pinned", -1),
        ("created_at", -1)
    ]).skip(offset).limit(limit))

    result = []
    for comment in comments:
        user = users_collection.find_one({"_id": comment["user_id"]})
        if not user:
            continue

        comment_text = decrypt_data(comment["text"], ENCRYPTION_KEY)

        comment_data = {
            "id": str(comment["_id"]),
            "text": comment_text,
            "created_at": comment["created_at"].isoformat() + "Z",
            "user_id": str(comment["user_id"]),
            "username": user["Username"],
            "display": decrypt_data(user["Display"], ENCRYPTION_KEY) if user.get("Display") else None,
            "parent_comment_id": str(comment['parent_comment_id']) if comment['parent_comment_id'] else str(None),
            "CountReplays": comment.get('CountReplays', 0),
            "CountLike": comment.get('CountLike', 0),
            "pinned": comment.get('pinned', False),
            "is_edited": comment.get('is_edited', False),
            "edited_at": comment["edited_at"].isoformat() + "Z" if comment.get("edited_at") else None
        }

        result.append(comment_data)

    has_more = offset + len(comments) < total_count

    return {
        "comments": result,
        "total_count": total_count,
        "has_more": has_more,
        "offset": offset,
        "limit": limit
    }

@router.get("/get-image-comments/{image_id}")
def get_comments(
    image_id: str,
    offset: int = Query(0, ge=0, description="Number of comments to skip"),
    limit: int = Query(10, ge=1, le=100, description="Number of comments to return")
):
    if not ObjectId.is_valid(image_id):
        raise HTTPException(status_code=400, detail="Invalid image ID format")

    total_count = images_comment_collection.count_documents({
        "image_id": ObjectId(image_id),
        "parent_comment_id": None
    })

    comments = list(images_comment_collection.find({
        "image_id": ObjectId(image_id),
        "parent_comment_id": None
    }).sort([
        ("pinned", -1),
        ("created_at", -1)
    ]).skip(offset).limit(limit))

    result = []
    for comment in comments:
        user = users_collection.find_one({"_id": comment["user_id"]})
        if not user:
            continue

        comment_text = decrypt_data(comment["text"], ENCRYPTION_KEY)

        comment_data = {
            "id": str(comment["_id"]),
            "text": comment_text,
            "created_at": comment["created_at"].isoformat() + "Z",
            "user_id": str(comment["user_id"]),
            "username": user["Username"],
            "display": decrypt_data(user["Display"], ENCRYPTION_KEY) if user.get("Display") else None,
            "parent_comment_id": str(comment['parent_comment_id']) if comment['parent_comment_id'] else str(None),
            "CountReplays": comment.get('CountReplays', 0),
            "CountLike": comment.get('CountLike', 0),
            "pinned": comment.get('pinned', False),
            "is_edited": comment.get('is_edited', False),
            "edited_at": comment["edited_at"].isoformat() + "Z" if comment.get("edited_at") else None
        }

        result.append(comment_data)

    has_more = offset + len(comments) < total_count

    return {
        "comments": result,
        "total_count": total_count,
        "has_more": has_more,
        "offset": offset,
        "limit": limit
    }

@router.get("/get-product-comments/{product_id}")
def get_comments(
    product_id: str,
    offset: int = Query(0, ge=0, description="Number of comments to skip"),
    limit: int = Query(10, ge=1, le=100, description="Number of comments to return")
):
    if not ObjectId.is_valid(product_id):
        raise HTTPException(status_code=400, detail="Invalid product ID format")

    total_count = products_comment_collection.count_documents({
        "product_id": ObjectId(product_id),
        "parent_comment_id": None
    })

    comments = list(products_comment_collection.find({
        "product_id": ObjectId(product_id),
        "parent_comment_id": None
    }).sort([
        ("pinned", -1),
        ("created_at", -1)
    ]).skip(offset).limit(limit))

    result = []
    for comment in comments:
        user = users_collection.find_one({"_id": comment["user_id"]})
        if not user:
            continue

        comment_text = decrypt_data(comment["text"], ENCRYPTION_KEY)

        comment_data = {
            "id": str(comment["_id"]),
            "text": comment_text,
            "created_at": comment["created_at"].isoformat() + "Z",
            "user_id": str(comment["user_id"]),
            "username": user["Username"],
            "display": decrypt_data(user["Display"], ENCRYPTION_KEY) if user.get("Display") else None,
            "parent_comment_id": str(comment['parent_comment_id']) if comment['parent_comment_id'] else str(None),
            "CountReplays": comment.get('CountReplays', 0),
            "CountLike": comment.get('CountLike', 0),
            "pinned": comment.get('pinned', False),
            "is_edited": comment.get('is_edited', False),
            "edited_at": comment["edited_at"].isoformat() + "Z" if comment.get("edited_at") else None
        }

        result.append(comment_data)

    has_more = offset + len(comments) < total_count

    return {
        "comments": result,
        "total_count": total_count,
        "has_more": has_more,
        "offset": offset,
        "limit": limit
    }

class VideoPinCommentRequest(BaseModel):
    user_id: str
    comment_id: str
    video_id: str

@router.post("/pin-video-comment")
async def pin_comment(request: VideoPinCommentRequest):
    # Validate ObjectIds
    try:
        comment_id = ObjectId(request.comment_id)
        video_id = ObjectId(request.video_id)
        user_id = ObjectId(request.user_id)
    except Exception as e:
        raise HTTPException(status_code=400, detail="Invalid ObjectId format")

    # Find the comment
    comment = videos_comment_collection.find_one({"_id": comment_id, "video_id": video_id})
    if not comment:
        raise HTTPException(status_code=404, detail="Comment not found")

    # Check if the comment is a top-level comment
    if comment.get("parent_comment_id") is not None:
        raise HTTPException(status_code=400, detail="Only top-level comments can be pinned")

    # Find the video
    video = videos_collection.find_one({"_id": video_id})
    if not video:
        raise HTTPException(status_code=404, detail="video not found")

    # Authorization check
    is_owner = str(video.get("UserId")) == str(user_id)

    collaborator_ids = []
    # Handle CollaborationAccounts field
    collaboration_accounts = video.get("CollaborationAccounts", "")

    if collaboration_accounts:
        try:
            # Handle different formats of CollaborationAccounts
            if isinstance(collaboration_accounts, str):
                if collaboration_accounts.startswith("[") and collaboration_accounts.endswith("]"):
                    try:
                        collaborator_ids = json.loads(collaboration_accounts)
                        collaborator_ids = [str(cid) for cid in collaborator_ids if ObjectId.is_valid(str(cid))]
                    except json.JSONDecodeError:
                        collaborator_ids = re.findall(r"[0-9a-fA-F]{24}", collaboration_accounts)
                else:
                    collaborator_ids = re.findall(r"[0-9a-fA-F]{24}", collaboration_accounts)
            elif isinstance(collaboration_accounts, list):
                collaborator_ids = [str(cid) for cid in collaboration_accounts if ObjectId.is_valid(str(cid))]
        except Exception as e:
            collaborator_ids = []

    is_collaborator = str(user_id) in collaborator_ids

    if not (is_owner or is_collaborator):
        raise HTTPException(status_code=403, detail="Not authorized to pin comments")

    # Check pinned comments limit
    if not comment.get("pinned", False):  # Only check limit if comment is not already pinned
        pinned_count = videos_comment_collection.count_documents({
            "video_id": video_id,
            "parent_comment_id": None,
            "pinned": True
        })
        if pinned_count >= 5:
            raise HTTPException(status_code=400, detail="Cannot pin more than 5 comments")

    # Toggle pinned status
    new_pinned_status = not comment.get("pinned", False)
    videos_comment_collection.update_one(
        {"_id": comment_id},
        {"$set": {"pinned": new_pinned_status}}
    )

    # Fetch updated comment data
    updated_comment = videos_comment_collection.find_one({"_id": comment_id})
    if not updated_comment:
        raise HTTPException(status_code=404, detail="Comment not found after update")

    # Prepare comment data for broadcast
    user_info = users_collection.find_one({"_id": updated_comment["user_id"]})
    if not user_info:
        raise HTTPException(status_code=404, detail="User not found")

    decrypted_text = decrypt_data(updated_comment["text"], ENCRYPTION_KEY)
    decrypted_display = decrypt_data(user_info.get("Display", ""), ENCRYPTION_KEY) if user_info.get("Display") else ""

    comment_data = {
        "id": str(updated_comment["_id"]),
        "text": decrypted_text,
        "created_at": updated_comment["created_at"].isoformat() + "Z",
        "user_id": str(updated_comment["user_id"]),
        "username": user_info["Username"],
        "display": decrypted_display,
        "parent_comment_id": str(updated_comment["parent_comment_id"]) if updated_comment.get("parent_comment_id") else str(None),
        "CountReplays": updated_comment.get("CountReplays", 0),
        "CountLike": updated_comment.get("CountLike", 0),
        "pinned": new_pinned_status,
        "is_edited": False,
        "replays": []
    }

    # Fetch replays if any
    for replay_id in updated_comment.get("replays", []):
        replay = videos_comment_collection.find_one({"_id": replay_id})
        if replay:
            replay_user = users_collection.find_one({"_id": replay["user_id"]})
            replay_text = decrypt_data(replay["text"], ENCRYPTION_KEY)
            replay_data = {
                "id": str(replay["_id"]),
                "text": replay_text,
                "created_at": replay["created_at"].isoformat() + "Z",
                "user_id": str(replay["user_id"]),
                "username": replay_user["Username"] if replay_user else "",
                "display": decrypt_data(replay_user.get("Display", ""), ENCRYPTION_KEY) if replay_user and replay_user.get("Display") else "",
                "parent_comment_id": str(replay["parent_comment_id"]),
                "CountReplays": replay.get("CountReplays", 0),
                "CountLike": replay.get("CountLike", 0),
                "pinned": replay.get("pinned", False),
                "is_edited": False,
            }
            comment_data["replays"].append(replay_data)

    # Broadcast the update via WebSocket
    message = {
        "type": "pin_comment",
        "comment_id": str(comment_id),
        "pinned": new_pinned_status,
        "comment_data": comment_data
    }
    await manager_video.broadcast(str(video_id), message)

    return {"status": "success", "pinned": new_pinned_status}

class ArticlePinCommentRequest(BaseModel):
    user_id: str
    comment_id: str
    article_id: str

@router.post("/pin-article-comment")
async def pin_article_comment(request: ArticlePinCommentRequest):
    try:
        comment_id = ObjectId(request.comment_id)
        article_id = ObjectId(request.article_id)
        user_id = ObjectId(request.user_id)
    except Exception as e:
        raise HTTPException(status_code=400, detail="Invalid ObjectId format")

    comment = article_comment_collection.find_one({"_id": comment_id, "article_id": article_id})
    if not comment:
        raise HTTPException(status_code=404, detail="Comment not found")

    if comment.get("parent_comment_id") is not None:
        raise HTTPException(status_code=400, detail="Only top-level comments can be pinned")

    article = articles_collection.find_one({"_id": article_id})
    if not article:
        raise HTTPException(status_code=404, detail="Article not found")

    if not comment.get("pinned", False):
        pinned_count = article_comment_collection.count_documents({
            "article_id": article_id,
            "parent_comment_id": None,
            "pinned": True
        })
        if pinned_count >= 5:
            raise HTTPException(status_code=400, detail="Cannot pin more than 5 comments")

    new_pinned_status = not comment.get("pinned", False)
    article_comment_collection.update_one(
        {"_id": comment_id},
        {"$set": {"pinned": new_pinned_status}}
    )

    updated_comment = article_comment_collection.find_one({"_id": comment_id})
    if not updated_comment:
        raise HTTPException(status_code=404, detail="Comment not found after update")

    user_info = users_collection.find_one({"_id": updated_comment["user_id"]})
    if not user_info:
        raise HTTPException(status_code=404, detail="User not found")

    decrypted_text = decrypt_data(updated_comment["text"], ENCRYPTION_KEY)
    decrypted_display = decrypt_data(user_info.get("Display", ""), ENCRYPTION_KEY) if user_info.get("Display") else ""

    # Get avatar
    avatar_base64 = ''
    if user_info.get("ProfileImageId"):
        try:
            file_avatar = users_fs.get(ObjectId(user_info["ProfileImageId"]))
            avatar_base64 = base64.b64encode(file_avatar.read()).decode('utf-8')
        except:
            pass

    comment_data = {
        "id": str(updated_comment["_id"]),
        "text": decrypted_text,
        "created_at": updated_comment["created_at"].isoformat() + "Z",
        "user_id": str(updated_comment["user_id"]),
        "username": user_info["Username"],
        "display": decrypted_display,
        "avatar": avatar_base64,
        "parent_comment_id": str(updated_comment["parent_comment_id"]) if updated_comment.get("parent_comment_id") else None,
        "CountReplays": updated_comment.get("CountReplays", 0),
        "CountLike": updated_comment.get("CountLike", 0),
        "pinned": new_pinned_status,
        "is_edited": False,
        "replays": []
    }

    for replay_id in updated_comment.get("replays", []):
        replay = article_comment_collection.find_one({"_id": replay_id})
        if replay:
            replay_user = users_collection.find_one({"_id": replay["user_id"]})
            replay_text = decrypt_data(replay["text"], ENCRYPTION_KEY)
            replay_avatar = ''
            if replay_user and replay_user.get("ProfileImageId"):
                try:
                    file_avatar = users_fs.get(ObjectId(replay_user["ProfileImageId"]))
                    replay_avatar = base64.b64encode(file_avatar.read()).decode('utf-8')
                except:
                    pass
            replay_data = {
                "id": str(replay["_id"]),
                "text": replay_text,
                "created_at": replay["created_at"].isoformat() + "Z",
                "user_id": str(replay["user_id"]),
                "username": replay_user["Username"] if replay_user else "",
                "display": decrypt_data(replay_user.get("Display", ""), ENCRYPTION_KEY) if replay_user and replay_user.get("Display") else "",
                "avatar": replay_avatar,
                "parent_comment_id": str(replay["parent_comment_id"]),
                "CountReplays": replay.get("CountReplays", 0),
                "CountLike": replay.get("CountLike", 0),
                "pinned": replay.get("pinned", False),
                "is_edited": False,
            }
            comment_data["replays"].append(replay_data)

    message = {
        "type": "pin_comment",
        "comment_id": str(comment_id),
        "pinned": new_pinned_status,
        "comment_data": comment_data
    }
    await manager_article.broadcast(str(article_id), message)

    return {"status": "success", "pinned": new_pinned_status}

class TheoryPinCommentRequest(BaseModel):
    user_id: str
    comment_id: str
    theory_id: str

@router.post("/pin-theory-comment")
async def pin_comment(request: TheoryPinCommentRequest):
    # Validate ObjectIds
    try:
        comment_id = ObjectId(request.comment_id)
        theory_id = ObjectId(request.theory_id)
        user_id = ObjectId(request.user_id)
    except Exception as e:
        raise HTTPException(status_code=400, detail="Invalid ObjectId format")

    # Find the comment
    comment = theories_comment_collection.find_one({"_id": comment_id, "theory_id": theory_id})
    if not comment:
        raise HTTPException(status_code=404, detail="Comment not found")

    # Check if the comment is a top-level comment
    if comment.get("parent_comment_id") is not None:
        raise HTTPException(status_code=400, detail="Only top-level comments can be pinned")

    # Find the theory
    theory = theory_collection.find_one({"_id": theory_id})
    if not theory:
        raise HTTPException(status_code=404, detail="theory not found")

    # Check pinned comments limit
    if not comment.get("pinned", False):  # Only check limit if comment is not already pinned
        pinned_count = theories_comment_collection.count_documents({
            "theory_id": theory_id,
            "parent_comment_id": None,
            "pinned": True
        })
        if pinned_count >= 5:
            raise HTTPException(status_code=400, detail="Cannot pin more than 5 comments")

    # Toggle pinned status
    new_pinned_status = not comment.get("pinned", False)
    theories_comment_collection.update_one(
        {"_id": comment_id},
        {"$set": {"pinned": new_pinned_status}}
    )

    # Fetch updated comment data
    updated_comment = theories_comment_collection.find_one({"_id": comment_id})
    if not updated_comment:
        raise HTTPException(status_code=404, detail="Comment not found after update")

    # Prepare comment data for broadcast
    user_info = users_collection.find_one({"_id": updated_comment["user_id"]})
    if not user_info:
        raise HTTPException(status_code=404, detail="User not found")

    decrypted_text = decrypt_data(updated_comment["text"], ENCRYPTION_KEY)
    decrypted_display = decrypt_data(user_info.get("Display", ""), ENCRYPTION_KEY) if user_info.get("Display") else ""

    comment_data = {
        "id": str(updated_comment["_id"]),
        "text": decrypted_text,
        "created_at": updated_comment["created_at"].isoformat() + "Z",
        "user_id": str(updated_comment["user_id"]),
        "username": user_info["Username"],
        "display": decrypted_display,
        "parent_comment_id": str(updated_comment["parent_comment_id"]) if updated_comment.get("parent_comment_id") else str(None),
        "CountReplays": updated_comment.get("CountReplays", 0),
        "CountLike": updated_comment.get("CountLike", 0),
        "pinned": new_pinned_status,
        "is_edited": False,
        "replays": []
    }

    # Fetch replays if any
    for replay_id in updated_comment.get("replays", []):
        replay = theories_comment_collection.find_one({"_id": replay_id})
        if replay:
            replay_user = users_collection.find_one({"_id": replay["user_id"]})
            replay_text = decrypt_data(replay["text"], ENCRYPTION_KEY)
            replay_data = {
                "id": str(replay["_id"]),
                "text": replay_text,
                "created_at": replay["created_at"].isoformat() + "Z",
                "user_id": str(replay["user_id"]),
                "username": replay_user["Username"] if replay_user else "",
                "display": decrypt_data(replay_user.get("Display", ""), ENCRYPTION_KEY) if replay_user and replay_user.get("Display") else "",
                "parent_comment_id": str(replay["parent_comment_id"]),
                "CountReplays": replay.get("CountReplays", 0),
                "CountLike": replay.get("CountLike", 0),
                "pinned": replay.get("pinned", False),
                "is_edited": False,
            }
            comment_data["replays"].append(replay_data)

    # Broadcast the update via WebSocket
    message = {
        "type": "pin_comment",
        "comment_id": str(comment_id),
        "pinned": new_pinned_status,
        "comment_data": comment_data
    }
    await manager_theory.broadcast(str(theory_id), message)

    return {"status": "success", "pinned": new_pinned_status}

class ImagePinCommentRequest(BaseModel):
    user_id: str
    comment_id: str
    image_id: str

@router.post("/pin-image-comment")
async def pin_comment(request: ImagePinCommentRequest):
    # Validate ObjectIds
    try:
        comment_id = ObjectId(request.comment_id)
        image_id = ObjectId(request.image_id)
        user_id = ObjectId(request.user_id)
    except Exception as e:
        raise HTTPException(status_code=400, detail="Invalid ObjectId format")

    # Find the comment
    comment = images_comment_collection.find_one({"_id": comment_id, "image_id": image_id})
    if not comment:
        raise HTTPException(status_code=404, detail="Comment not found")

    # Check if the comment is a top-level comment
    if comment.get("parent_comment_id") is not None:
        raise HTTPException(status_code=400, detail="Only top-level comments can be pinned")

    # Find the image
    image = images_collection.find_one({"_id": image_id})
    if not image:
        raise HTTPException(status_code=404, detail="Image not found")

    # Authorization check
    is_owner = str(image.get("UserId")) == str(user_id)

    collaborator_ids = []
    # Handle CollaborationAccounts field
    collaboration_accounts = image.get("CollaborationAccounts", "")

    if collaboration_accounts:
        try:
            # Handle different formats of CollaborationAccounts
            if isinstance(collaboration_accounts, str):
                if collaboration_accounts.startswith("[") and collaboration_accounts.endswith("]"):
                    try:
                        collaborator_ids = json.loads(collaboration_accounts)
                        collaborator_ids = [str(cid) for cid in collaborator_ids if ObjectId.is_valid(str(cid))]
                    except json.JSONDecodeError:
                        collaborator_ids = re.findall(r"[0-9a-fA-F]{24}", collaboration_accounts)
                else:
                    collaborator_ids = re.findall(r"[0-9a-fA-F]{24}", collaboration_accounts)
            elif isinstance(collaboration_accounts, list):
                collaborator_ids = [str(cid) for cid in collaboration_accounts if ObjectId.is_valid(str(cid))]
        except Exception as e:
            collaborator_ids = []

    is_collaborator = str(user_id) in collaborator_ids

    if not (is_owner or is_collaborator):
        raise HTTPException(status_code=403, detail="Not authorized to pin comments")

    # Check pinned comments limit
    if not comment.get("pinned", False):  # Only check limit if comment is not already pinned
        pinned_count = images_comment_collection.count_documents({
            "image_id": image_id,
            "parent_comment_id": None,
            "pinned": True
        })
        if pinned_count >= 5:
            raise HTTPException(status_code=400, detail="Cannot pin more than 5 comments")

    # Toggle pinned status
    new_pinned_status = not comment.get("pinned", False)
    images_comment_collection.update_one(
        {"_id": comment_id},
        {"$set": {"pinned": new_pinned_status}}
    )

    # Fetch updated comment data
    updated_comment = images_comment_collection.find_one({"_id": comment_id})
    if not updated_comment:
        raise HTTPException(status_code=404, detail="Comment not found after update")

    # Prepare comment data for broadcast
    user_info = users_collection.find_one({"_id": updated_comment["user_id"]})
    if not user_info:
        raise HTTPException(status_code=404, detail="User not found")

    decrypted_text = decrypt_data(updated_comment["text"], ENCRYPTION_KEY)
    decrypted_display = decrypt_data(user_info.get("Display", ""), ENCRYPTION_KEY) if user_info.get("Display") else ""

    comment_data = {
        "id": str(updated_comment["_id"]),
        "text": decrypted_text,
        "created_at": updated_comment["created_at"].isoformat() + "Z",
        "user_id": str(updated_comment["user_id"]),
        "username": user_info["Username"],
        "display": decrypted_display,
        "parent_comment_id": str(updated_comment["parent_comment_id"]) if updated_comment.get("parent_comment_id") else str(None),
        "CountReplays": updated_comment.get("CountReplays", 0),
        "CountLike": updated_comment.get("CountLike", 0),
        "pinned": new_pinned_status,
        "is_edited": False,
        "replays": []
    }

    # Fetch replays if any
    for replay_id in updated_comment.get("replays", []):
        replay = images_comment_collection.find_one({"_id": replay_id})
        if replay:
            replay_user = users_collection.find_one({"_id": replay["user_id"]})
            replay_text = decrypt_data(replay["text"], ENCRYPTION_KEY)
            replay_data = {
                "id": str(replay["_id"]),
                "text": replay_text,
                "created_at": replay["created_at"].isoformat() + "Z",
                "user_id": str(replay["user_id"]),
                "username": replay_user["Username"] if replay_user else "",
                "display": decrypt_data(replay_user.get("Display", ""), ENCRYPTION_KEY) if replay_user and replay_user.get("Display") else "",
                "parent_comment_id": str(replay["parent_comment_id"]),
                "CountReplays": replay.get("CountReplays", 0),
                "CountLike": replay.get("CountLike", 0),
                "pinned": replay.get("pinned", False),
                "is_edited": False,
            }
            comment_data["replays"].append(replay_data)

    # Broadcast the update via WebSocket
    message = {
        "type": "pin_comment",
        "comment_id": str(comment_id),
        "pinned": new_pinned_status,
        "comment_data": comment_data
    }
    await manager_image.broadcast(str(image_id), message)

    return {"status": "success", "pinned": new_pinned_status}

class ProductPinCommentRequest(BaseModel):
    user_id: str
    comment_id: str
    product_id: str

@router.post("/pin-product-comment")
async def pin_comment(request: ProductPinCommentRequest):
    # Validate ObjectIds
    try:
        comment_id = ObjectId(request.comment_id)
        product_id = ObjectId(request.product_id)
        user_id = ObjectId(request.user_id)
    except Exception as e:
        raise HTTPException(status_code=400, detail="Invalid ObjectId format")

    # Find the comment
    comment = products_comment_collection.find_one({"_id": comment_id, "product_id": product_id})
    if not comment:
        raise HTTPException(status_code=404, detail="Comment not found")

    # Check if the comment is a top-level comment
    if comment.get("parent_comment_id") is not None:
        raise HTTPException(status_code=400, detail="Only top-level comments can be pinned")

    # Find the product
    product = products_collection.find_one({"_id": product_id})
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    # Authorization check
    is_owner = str(product.get("UserId")) == str(user_id)

    collaborator_ids = []
    # Handle CollaborationShopings field
    collaboration_accounts = product.get("CollaborationShopings", "")

    if collaboration_accounts:
        try:
            # Handle different formats of CollaborationShopings
            if isinstance(collaboration_accounts, str):
                if collaboration_accounts.startswith("[") and collaboration_accounts.endswith("]"):
                    try:
                        collaborator_ids = json.loads(collaboration_accounts)
                        collaborator_ids = [str(cid) for cid in collaborator_ids if ObjectId.is_valid(str(cid))]
                    except json.JSONDecodeError:
                        collaborator_ids = re.findall(r"[0-9a-fA-F]{24}", collaboration_accounts)
                else:
                    collaborator_ids = re.findall(r"[0-9a-fA-F]{24}", collaboration_accounts)
            elif isinstance(collaboration_accounts, list):
                collaborator_ids = [str(cid) for cid in collaboration_accounts if ObjectId.is_valid(str(cid))]
        except Exception as e:
            collaborator_ids = []

    is_collaborator = str(user_id) in collaborator_ids

    if not (is_owner or is_collaborator):
        raise HTTPException(status_code=403, detail="Not authorized to pin comments")

    # Check pinned comments limit
    if not comment.get("pinned", False):  # Only check limit if comment is not already pinned
        pinned_count = products_comment_collection.count_documents({
            "product_id": product_id,
            "parent_comment_id": None,
            "pinned": True
        })
        if pinned_count >= 5:
            raise HTTPException(status_code=400, detail="Cannot pin more than 5 comments")

    # Toggle pinned status
    new_pinned_status = not comment.get("pinned", False)
    products_comment_collection.update_one(
        {"_id": comment_id},
        {"$set": {"pinned": new_pinned_status}}
    )

    # Fetch updated comment data
    updated_comment = products_comment_collection.find_one({"_id": comment_id})
    if not updated_comment:
        raise HTTPException(status_code=404, detail="Comment not found after update")

    # Prepare comment data for broadcast
    user_info = users_collection.find_one({"_id": updated_comment["user_id"]})
    if not user_info:
        raise HTTPException(status_code=404, detail="User not found")

    decrypted_text = decrypt_data(updated_comment["text"], ENCRYPTION_KEY)
    decrypted_display = decrypt_data(user_info.get("Display", ""), ENCRYPTION_KEY) if user_info.get("Display") else ""

    comment_data = {
        "id": str(updated_comment["_id"]),
        "text": decrypted_text,
        "created_at": updated_comment["created_at"].isoformat() + "Z",
        "user_id": str(updated_comment["user_id"]),
        "username": user_info["Username"],
        "display": decrypted_display,
        "parent_comment_id": str(updated_comment["parent_comment_id"]) if updated_comment.get("parent_comment_id") else str(None),
        "CountReplays": updated_comment.get("CountReplays", 0),
        "CountLike": updated_comment.get("CountLike", 0),
        "pinned": new_pinned_status,
        "is_edited": False,
        "replays": []
    }

    # Fetch replays if any
    for replay_id in updated_comment.get("replays", []):
        replay = products_comment_collection.find_one({"_id": replay_id})
        if replay:
            replay_user = users_collection.find_one({"_id": replay["user_id"]})
            replay_text = decrypt_data(replay["text"], ENCRYPTION_KEY)
            replay_data = {
                "id": str(replay["_id"]),
                "text": replay_text,
                "created_at": replay["created_at"].isoformat() + "Z",
                "user_id": str(replay["user_id"]),
                "username": replay_user["Username"] if replay_user else "",
                "display": decrypt_data(replay_user.get("Display", ""), ENCRYPTION_KEY) if replay_user and replay_user.get("Display") else "",
                "parent_comment_id": str(replay["parent_comment_id"]),
                "CountReplays": replay.get("CountReplays", 0),
                "CountLike": replay.get("CountLike", 0),
                "pinned": replay.get("pinned", False),
                "is_edited": False,
            }
            comment_data["replays"].append(replay_data)

    # Broadcast the update via WebSocket
    message = {
        "type": "pin_comment",
        "comment_id": str(comment_id),
        "pinned": new_pinned_status,
        "comment_data": comment_data
    }
    await manager_product.broadcast(str(product_id), message)

    return {"status": "success", "pinned": new_pinned_status}

@router.get("/get-video-replays/{comment_id}")
def get_replays(
    comment_id: str,
    offset: int = Query(0, ge=0, description="Number of replays to skip"),
    limit: int = Query(10, ge=1, le=100, description="Number of replays to return")
):
    if not ObjectId.is_valid(comment_id):
        raise HTTPException(status_code=400, detail="Invalid comment ID format")

    comment = videos_comment_collection.find_one({"_id": ObjectId(comment_id)})
    if not comment:
        raise HTTPException(status_code=404, detail="Comment not found")

    total_count = videos_comment_collection.count_documents({
        "parent_comment_id": ObjectId(comment_id)
    })

    replays = list(videos_comment_collection.find({
        "parent_comment_id": ObjectId(comment_id)
    }).sort([
        ("created_at", -1)
    ]).skip(offset).limit(limit))

    result = []
    for replay in replays:
        user = users_collection.find_one({"_id": replay["user_id"]})
        if not user:
            continue

        replay_text = decrypt_data(replay["text"], ENCRYPTION_KEY)
        replay_data = {
            "id": str(replay["_id"]),
            "text": replay_text,
            "created_at": replay["created_at"].isoformat() + "Z",
            "user_id": str(replay["user_id"]),
            "username": user["Username"],
            "display": decrypt_data(user["Display"], ENCRYPTION_KEY) if user.get("Display") else None,
            "parent_comment_id": str(replay["parent_comment_id"]),
            "CountReplays": replay.get("CountReplays", 0),
            "CountLike": replay.get("CountLike", 0),
            "pinned": replay.get("pinned", False),
            "replays": [],
            "is_edited": replay.get('is_edited', False),
            "edited_at": replay["edited_at"].isoformat() + "Z" if replay.get("edited_at") else None
        }
        result.append(replay_data)

    has_more = offset + len(replays) < total_count

    return {
        "replays": result,
        "total_count": total_count,
        "has_more": has_more,
        "offset": offset,
        "limit": limit
    }

@router.get("/get-article-replays/{comment_id}")
def get_article_replays(
    comment_id: str,
    offset: int = Query(0, ge=0, description="Number of replays to skip"),
    limit: int = Query(10, ge=1, le=100, description="Number of replays to return")
):
    if not ObjectId.is_valid(comment_id):
        raise HTTPException(status_code=400, detail="Invalid comment ID format")

    comment = article_comment_collection.find_one({"_id": ObjectId(comment_id)})
    if not comment:
        raise HTTPException(status_code=404, detail="Comment not found")

    total_count = article_comment_collection.count_documents({
        "parent_comment_id": ObjectId(comment_id)
    })

    replays = list(article_comment_collection.find({
        "parent_comment_id": ObjectId(comment_id)
    }).sort([
        ("created_at", -1)
    ]).skip(offset).limit(limit))

    result = []
    for replay in replays:
        user = users_collection.find_one({"_id": replay["user_id"]})
        if not user:
            continue

        replay_text = decrypt_data(replay["text"], ENCRYPTION_KEY)
        
        # Get avatar
        avatar_base64 = ''
        if user.get("ProfileImageId"):
            try:
                file_avatar = users_fs.get(ObjectId(user["ProfileImageId"]))
                avatar_base64 = base64.b64encode(file_avatar.read()).decode('utf-8')
            except:
                pass
                
        replay_data = {
            "id": str(replay["_id"]),
            "text": replay_text,
            "created_at": replay["created_at"].isoformat() + "Z",
            "user_id": str(replay["user_id"]),
            "username": user["Username"],
            "display": decrypt_data(user["Display"], ENCRYPTION_KEY) if user.get("Display") else None,
            "avatar": avatar_base64,
            "parent_comment_id": str(replay["parent_comment_id"]),
            "CountReplays": replay.get("CountReplays", 0),
            "CountLike": replay.get("CountLike", 0),
            "pinned": replay.get("pinned", False),
            "replays": [],
            "is_edited": replay.get('is_edited', False),
            "edited_at": replay["edited_at"].isoformat() + "Z" if replay.get("edited_at") else None
        }
        result.append(replay_data)

    has_more = offset + len(replays) < total_count

    return {
        "replays": result,
        "total_count": total_count,
        "has_more": has_more,
        "offset": offset,
        "limit": limit
    }

@router.get("/get-theory-replays/{comment_id}")
def get_replays(
    comment_id: str,
    offset: int = Query(0, ge=0, description="Number of replays to skip"),
    limit: int = Query(10, ge=1, le=100, description="Number of replays to return")
):
    if not ObjectId.is_valid(comment_id):
        raise HTTPException(status_code=400, detail="Invalid comment ID format")

    comment = theories_comment_collection.find_one({"_id": ObjectId(comment_id)})
    if not comment:
        raise HTTPException(status_code=404, detail="Comment not found")

    total_count = theories_comment_collection.count_documents({
        "parent_comment_id": ObjectId(comment_id)
    })

    replays = list(theories_comment_collection.find({
        "parent_comment_id": ObjectId(comment_id)
    }).sort([
        ("created_at", -1)
    ]).skip(offset).limit(limit))

    result = []
    for replay in replays:
        user = users_collection.find_one({"_id": replay["user_id"]})
        if not user:
            continue

        replay_text = decrypt_data(replay["text"], ENCRYPTION_KEY)
        replay_data = {
            "id": str(replay["_id"]),
            "text": replay_text,
            "created_at": replay["created_at"].isoformat() + "Z",
            "user_id": str(replay["user_id"]),
            "username": user["Username"],
            "display": decrypt_data(user["Display"], ENCRYPTION_KEY) if user.get("Display") else None,
            "parent_comment_id": str(replay["parent_comment_id"]),
            "CountReplays": replay.get("CountReplays", 0),
            "CountLike": replay.get("CountLike", 0),
            "pinned": replay.get("pinned", False),
            "replays": [],
            "is_edited": replay.get('is_edited', False),
            "edited_at": replay["edited_at"].isoformat() + "Z" if replay.get("edited_at") else None
        }
        result.append(replay_data)

    has_more = offset + len(replays) < total_count

    return {
        "replays": result,
        "total_count": total_count,
        "has_more": has_more,
        "offset": offset,
        "limit": limit
    }

@router.get("/get-image-replays/{comment_id}")
def get_replays(
    comment_id: str,
    offset: int = Query(0, ge=0, description="Number of replays to skip"),
    limit: int = Query(10, ge=1, le=100, description="Number of replays to return")
):
    if not ObjectId.is_valid(comment_id):
        raise HTTPException(status_code=400, detail="Invalid comment ID format")

    comment = images_comment_collection.find_one({"_id": ObjectId(comment_id)})
    if not comment:
        raise HTTPException(status_code=404, detail="Comment not found")

    total_count = images_comment_collection.count_documents({
        "parent_comment_id": ObjectId(comment_id)
    })

    replays = list(images_comment_collection.find({
        "parent_comment_id": ObjectId(comment_id)
    }).sort([
        ("created_at", -1)
    ]).skip(offset).limit(limit))

    result = []
    for replay in replays:
        user = users_collection.find_one({"_id": replay["user_id"]})
        if not user:
            continue

        replay_text = decrypt_data(replay["text"], ENCRYPTION_KEY)
        replay_data = {
            "id": str(replay["_id"]),
            "text": replay_text,
            "created_at": replay["created_at"].isoformat() + "Z",
            "user_id": str(replay["user_id"]),
            "username": user["Username"],
            "display": decrypt_data(user["Display"], ENCRYPTION_KEY) if user.get("Display") else None,
            "parent_comment_id": str(replay["parent_comment_id"]),
            "CountReplays": replay.get("CountReplays", 0),
            "CountLike": replay.get("CountLike", 0),
            "pinned": replay.get("pinned", False),
            "replays": [],
            "is_edited": replay.get('is_edited', False),
            "edited_at": replay["edited_at"].isoformat() + "Z" if replay.get("edited_at") else None
        }
        result.append(replay_data)

    has_more = offset + len(replays) < total_count

    return {
        "replays": result,
        "total_count": total_count,
        "has_more": has_more,
        "offset": offset,
        "limit": limit
    }

@router.get("/get-product-replays/{comment_id}")
def get_replays(
    comment_id: str,
    offset: int = Query(0, ge=0, description="Number of replays to skip"),
    limit: int = Query(10, ge=1, le=100, description="Number of replays to return")
):
    if not ObjectId.is_valid(comment_id):
        raise HTTPException(status_code=400, detail="Invalid comment ID format")

    comment = products_comment_collection.find_one({"_id": ObjectId(comment_id)})
    if not comment:
        raise HTTPException(status_code=404, detail="Comment not found")

    total_count = products_comment_collection.count_documents({
        "parent_comment_id": ObjectId(comment_id)
    })

    replays = list(products_comment_collection.find({
        "parent_comment_id": ObjectId(comment_id)
    }).sort([
        ("created_at", -1)
    ]).skip(offset).limit(limit))

    result = []
    for replay in replays:
        user = users_collection.find_one({"_id": replay["user_id"]})
        if not user:
            continue

        replay_text = decrypt_data(replay["text"], ENCRYPTION_KEY)
        replay_data = {
            "id": str(replay["_id"]),
            "text": replay_text,
            "created_at": replay["created_at"].isoformat() + "Z",
            "user_id": str(replay["user_id"]),
            "username": user["Username"],
            "display": decrypt_data(user["Display"], ENCRYPTION_KEY) if user.get("Display") else None,
            "parent_comment_id": str(replay["parent_comment_id"]),
            "CountReplays": replay.get("CountReplays", 0),
            "CountLike": replay.get("CountLike", 0),
            "pinned": replay.get("pinned", False),
            "replays": [],
            "is_edited": replay.get('is_edited', False),
            "edited_at": replay["edited_at"].isoformat() + "Z" if replay.get("edited_at") else None
        }
        result.append(replay_data)

    has_more = offset + len(replays) < total_count

    return {
        "replays": result,
        "total_count": total_count,
        "has_more": has_more,
        "offset": offset,
        "limit": limit
    }

class VideoCommentCreate(BaseModel):
    user_id: str
    video_id: str
    text: str
    parent_comment_id: Optional[str]
    user_id_from_me: str

@router.post("/add-comment-in-video")
async def add_comment(comment: VideoCommentCreate):
    comment_text = encrypt_data(comment.text, ENCRYPTION_KEY)

    comment_data = {
        "user_id": ObjectId(comment.user_id),
        "video_id": ObjectId(comment.video_id),
        "text": comment_text,
        "created_at": datetime.datetime.now(datetime.timezone.utc),
        "parent_comment_id": ObjectId(comment.parent_comment_id) if comment.parent_comment_id else None,
        "replays": [],
        "CountReplays": 0,
        "CountLike": 0,
        "pinned": False,
    }

    comment_id = videos_comment_collection.insert_one(comment_data).inserted_id

    if comment.parent_comment_id:
        videos_comment_collection.update_one(
            {"_id": ObjectId(comment.parent_comment_id)},
            {
                "$push": {"replays": comment_id},
                "$inc": {"CountReplays": 1}
            }
        )
        # Broadcast updated replay count
        parent_comment = videos_comment_collection.find_one({"_id": ObjectId(comment.parent_comment_id)})
        await manager_video.broadcast(comment.video_id, {
            "type": "replay_count",
            "comment_id": str(comment.parent_comment_id),
            "value": parent_comment.get('CountReplays', 0)
        })

    videos_collection.update_one(
        {"_id": ObjectId(comment.video_id)},
        {"$inc": {"CountComment": 1}}
    )

    # Broadcast updated comment count
    video_data = videos_collection.find_one({'_id': ObjectId(comment.video_id)})
    await manager_video.broadcast(comment.video_id, {
        "type": "comment_count",
        "value": video_data.get('CountComment', 0)
    })

    # User information for the comment
    user_info = users_collection.find_one({"_id": ObjectId(comment.user_id)})
    if not user_info:
        raise HTTPException(status_code=404, detail="User not found")

    username = user_info.get("Username", "UnknownUser")
    decrypted_display = decrypt_data(user_info.get('Display', ''), ENCRYPTION_KEY) if user_info.get('Display') else ''

    # Broadcast new comment
    await manager_video.broadcast(comment.video_id, {
        "type": "new_comment",
        "comment": {
            "id": str(comment_id),
            "text": comment.text,
            "created_at": comment_data["created_at"].isoformat(),
            "user_id": str(comment.user_id),
            "username": username,
            "display": decrypted_display,
            "parent_comment_id": str(comment.parent_comment_id) if comment.parent_comment_id else None,
            "CountReplays": 0,
            "CountLike": 0,
            "is_edited": False,
        }
    })

    # --- Create message for notification ---
    raw_comment = comment.text.strip()
    trimmed_text = raw_comment[:500] + ("..." if len(raw_comment) > 500 else "")
    full_message = f"@{username} : {trimmed_text}"
    encrypted_message = encrypt_data(full_message, ENCRYPTION_KEY)

    # comment
    encrypted_collaboration_type = encrypt_data("new_comment", ENCRYPTION_KEY)
    notification_doc = {
        "NotificationFrom": ObjectId(comment.user_id),
        "NotificationTo": ObjectId(comment.user_id_from_me),
        "Message": encrypted_message,
        "PostId": comment_id,
        "IsRead": False,
        "UploadAt": datetime.datetime.now(datetime.timezone.utc).isoformat().replace('Z', '+00:00'),
        "Type": encrypted_collaboration_type,
        "status": "video"
    }
    notifications_collection.insert_one(notification_doc)
    serialized_notification = serialize_notification(notification_doc)
    await broadcast_notification(str(comment.user_id_from_me), "add", serialized_notification)

    # Get collaborator_ids from post and send notification to each (except owner)
    if video_data:
        collaborators_value = video_data.get('CollaborationAccounts', '')
        collaborators_str = str(collaborators_value)  # Explicitly convert to string to avoid TypeError
        collaborator_ids = re.findall(r"[0-9a-fA-F]{24}", collaborators_str)
        collaborator_object_ids = [ObjectId(cid) for cid in collaborator_ids]

        for collab_id in collaborator_object_ids:
            if str(collab_id) != comment.user_id_from_me:
                collab_notification_doc = {
                    "NotificationFrom": ObjectId(comment.user_id),
                    "NotificationTo": collab_id,
                    "Message": encrypted_message,
                    "PostId": comment_id,
                    "IsRead": False,
                    "UploadAt": datetime.datetime.now(datetime.timezone.utc).isoformat().replace('Z', '+00:00'),
                    "Type": encrypted_collaboration_type,
                    "status": "video"
                }
                notifications_collection.insert_one(collab_notification_doc)
                serialized_collab_notification = serialize_notification(collab_notification_doc)
                await broadcast_notification(str(collab_id), "add", serialized_collab_notification)

    # replay
    if comment.parent_comment_id:
        parent_comment_data = videos_comment_collection.find_one({"_id": ObjectId(comment.parent_comment_id)})
        encrypted_collaboration_type_replay = encrypt_data("new_replay", ENCRYPTION_KEY)

        parent_user_id = parent_comment_data['user_id']
        replay_message = f"@{username} : {trimmed_text}"
        encrypted_message_replay = encrypt_data(replay_message, ENCRYPTION_KEY)

        notification_doc_replay = {
            "NotificationFrom": ObjectId(comment.user_id),
            "NotificationTo": ObjectId(parent_user_id),
            "Message": encrypted_message_replay,
            "PostId": comment_id,
            "IsRead": False,
            "UploadAt": datetime.datetime.now(datetime.timezone.utc).isoformat().replace('Z', '+00:00'),
            "Type": encrypted_collaboration_type_replay,
            "status": "video"
        }
        notifications_collection.insert_one(notification_doc_replay)
        serialized_notification_replay = serialize_notification(notification_doc_replay)
        await broadcast_notification(str(parent_user_id), "add", serialized_notification_replay)

    return {
        "success": True,
        "comment_id": str(comment_id),
        "parent_comment_id": comment.parent_comment_id,
        "text": comment.text,
        "CountReplays": 0,
        "CountLike": 0,
        "created_at": comment_data["created_at"].isoformat() + "Z",
        "is_edited": False,
    }

class ArticleCommentCreate(BaseModel):
    user_id: str
    article_id: str
    text: str
    parent_comment_id: Optional[str] = None
    user_id_from_me: str

@router.post("/add-comment-in-article")
async def add_comment_in_article(comment: ArticleCommentCreate):
    comment_text = encrypt_data(comment.text, ENCRYPTION_KEY)

    comment_data = {
        "user_id": ObjectId(comment.user_id),
        "article_id": ObjectId(comment.article_id),
        "text": comment_text,
        "created_at": datetime.datetime.now(datetime.timezone.utc),
        "parent_comment_id": ObjectId(comment.parent_comment_id) if comment.parent_comment_id else None,
        "replays": [],
        "CountReplays": 0,
        "CountLike": 0,
        "pinned": False,
    }

    comment_id = article_comment_collection.insert_one(comment_data).inserted_id

    if comment.parent_comment_id:
        article_comment_collection.update_one(
            {"_id": ObjectId(comment.parent_comment_id)},
            {
                "$push": {"replays": comment_id},
                "$inc": {"CountReplays": 1}
            }
        )
        parent_comment = article_comment_collection.find_one({"_id": ObjectId(comment.parent_comment_id)})
        await manager_article.broadcast(comment.article_id, {
            "type": "replay_count",
            "comment_id": str(comment.parent_comment_id),
            "value": parent_comment.get('CountReplays', 0)
        })

    articles_collection.update_one(
        {"_id": ObjectId(comment.article_id)},
        {"$inc": {"CountComment": 1}}
    )

    article_data = articles_collection.find_one({'_id': ObjectId(comment.article_id)})
    await manager_article.broadcast(comment.article_id, {
        "type": "comment_count",
        "value": article_data.get('CountComment', 0)
    })

    user_info = users_collection.find_one({"_id": ObjectId(comment.user_id)})
    if not user_info:
        raise HTTPException(status_code=404, detail="User not found")

    # Get avatar
    avatar_base64 = ''
    if user_info.get("ProfileImageId"):
        try:
            file_avatar = users_fs.get(ObjectId(user_info["ProfileImageId"]))
            avatar_base64 = base64.b64encode(file_avatar.read()).decode('utf-8')
        except:
            pass

    username = user_info.get("Username", "UnknownUser")
    decrypted_display = decrypt_data(user_info.get('Display', ''), ENCRYPTION_KEY) if user_info.get('Display') else ''

    await manager_article.broadcast(comment.article_id, {
        "type": "new_comment",
        "comment": {
            "id": str(comment_id),
            "text": comment.text,
            "created_at": comment_data["created_at"].isoformat(),
            "user_id": str(comment.user_id),
            "username": username,
            "display": decrypted_display,
            "avatar": avatar_base64,
            "parent_comment_id": str(comment.parent_comment_id) if comment.parent_comment_id else None,
            "CountReplays": 0,
            "CountLike": 0,
            "is_edited": False,
        }
    })

    raw_comment = comment.text.strip()
    trimmed_text = raw_comment[:500] + ("..." if len(raw_comment) > 500 else "")
    full_message = f"@{username} : {trimmed_text}"
    encrypted_message = encrypt_data(full_message, ENCRYPTION_KEY)

    encrypted_collaboration_type = encrypt_data("new_comment", ENCRYPTION_KEY)
    notification_doc = {
        "NotificationFrom": ObjectId(comment.user_id),
        "NotificationTo": ObjectId(comment.user_id_from_me),
        "Message": encrypted_message,
        "PostId": comment_id,
        "IsRead": False,
        "UploadAt": datetime.datetime.now(datetime.timezone.utc).isoformat().replace('Z', '+00:00'),
        "Type": encrypted_collaboration_type,
        "status": "article"
    }
    notifications_collection.insert_one(notification_doc)
    serialized_notification = serialize_notification(notification_doc)
    await broadcast_notification(str(comment.user_id_from_me), "add", serialized_notification)

    if comment.parent_comment_id:
        parent_comment_data = article_comment_collection.find_one({"_id": ObjectId(comment.parent_comment_id)})
        encrypted_collaboration_type_replay = encrypt_data("new_replay", ENCRYPTION_KEY)

        parent_user_id = parent_comment_data['user_id']
        replay_message = f"@{username} : {trimmed_text}"
        encrypted_message_replay = encrypt_data(replay_message, ENCRYPTION_KEY)

        notification_doc_replay = {
            "NotificationFrom": ObjectId(comment.user_id),
            "NotificationTo": ObjectId(parent_user_id),
            "Message": encrypted_message_replay,
            "PostId": comment_id,
            "IsRead": False,
            "UploadAt": datetime.datetime.now(datetime.timezone.utc).isoformat().replace('Z', '+00:00'),
            "Type": encrypted_collaboration_type_replay,
            "status": "article"
        }
        notifications_collection.insert_one(notification_doc_replay)
        serialized_notification_replay = serialize_notification(notification_doc_replay)
        await broadcast_notification(str(parent_user_id), "add", serialized_notification_replay)

    return {
        "success": True,
        "comment_id": str(comment_id),
        "parent_comment_id": comment.parent_comment_id,
        "text": comment.text,
        "CountReplays": 0,
        "CountLike": 0,
        "created_at": comment_data["created_at"].isoformat() + "Z",
        "is_edited": False,
    }

class TheoryCommentCreate(BaseModel):
    user_id: str
    theory_id: str
    text: str
    parent_comment_id: Optional[str]
    user_id_from_me: str

@router.post("/add-comment-in-theory")
async def add_comment(comment: TheoryCommentCreate):
    comment_text = encrypt_data(comment.text, ENCRYPTION_KEY)

    comment_data = {
        "user_id": ObjectId(comment.user_id),
        "theory_id": ObjectId(comment.theory_id),
        "text": comment_text,
        "created_at": datetime.datetime.now(datetime.timezone.utc),
        "parent_comment_id": ObjectId(comment.parent_comment_id) if comment.parent_comment_id else None,
        "replays": [],
        "CountReplays": 0,
        "CountLike": 0,
        "pinned": False,
    }

    comment_id = theories_comment_collection.insert_one(comment_data).inserted_id

    if comment.parent_comment_id:
        theories_comment_collection.update_one(
            {"_id": ObjectId(comment.parent_comment_id)},
            {
                "$push": {"replays": comment_id},
                "$inc": {"CountReplays": 1}
            }
        )
        # Broadcast updated replay count
        parent_comment = theories_comment_collection.find_one({"_id": ObjectId(comment.parent_comment_id)})
        await manager_theory.broadcast(comment.theory_id, {
            "type": "replay_count",
            "comment_id": str(comment.parent_comment_id),
            "value": parent_comment.get('CountReplays', 0)
        })

    theory_collection.update_one(
        {"_id": ObjectId(comment.theory_id)},
        {"$inc": {"CountComment": 1}}
    )

    # Broadcast updated comment count
    theory_data = theory_collection.find_one({'_id': ObjectId(comment.theory_id)})
    await manager_theory.broadcast(comment.theory_id, {
        "type": "comment_count",
        "value": theory_data.get('CountComment', 0)
    })

    # User information for the comment
    user_info = users_collection.find_one({"_id": ObjectId(comment.user_id)})
    if not user_info:
        raise HTTPException(status_code=404, detail="User not found")

    username = user_info.get("Username", "UnknownUser")
    decrypted_display = decrypt_data(user_info.get('Display', ''), ENCRYPTION_KEY) if user_info.get('Display') else ''

    # Broadcast new comment
    await manager_theory.broadcast(comment.theory_id, {
        "type": "new_comment",
        "comment": {
            "id": str(comment_id),
            "text": comment.text,
            "created_at": comment_data["created_at"].isoformat(),
            "user_id": str(comment.user_id),
            "username": username,
            "display": decrypted_display,
            "parent_comment_id": str(comment.parent_comment_id) if comment.parent_comment_id else None,
            "CountReplays": 0,
            "CountLike": 0,
            "is_edited": False,
        }
    })

    # --- Create message for notification ---
    raw_comment = comment.text.strip()
    trimmed_text = raw_comment[:500] + ("..." if len(raw_comment) > 500 else "")
    full_message = f"@{username} : {trimmed_text}"
    encrypted_message = encrypt_data(full_message, ENCRYPTION_KEY)

    # comment
    encrypted_collaboration_type = encrypt_data("new_comment", ENCRYPTION_KEY)
    notification_doc = {
        "NotificationFrom": ObjectId(comment.user_id),
        "NotificationTo": ObjectId(comment.user_id_from_me),
        "Message": encrypted_message,
        "PostId": comment_id,
        "IsRead": False,
        "UploadAt": datetime.datetime.now(datetime.timezone.utc).isoformat().replace('Z', '+00:00'),
        "Type": encrypted_collaboration_type,
        "status": "theory"
    }
    notifications_collection.insert_one(notification_doc)
    serialized_notification = serialize_notification(notification_doc)
    await broadcast_notification(str(comment.user_id_from_me), "add", serialized_notification)

    # Get collaborator_ids from post and send notification to each (except owner)
    if theory_data:
        collaborators_value = theory_data.get('CollaborationAccounts', '')
        collaborators_str = str(collaborators_value)  # Explicitly convert to string to avoid TypeError
        collaborator_ids = re.findall(r"[0-9a-fA-F]{24}", collaborators_str)
        collaborator_object_ids = [ObjectId(cid) for cid in collaborator_ids]

        for collab_id in collaborator_object_ids:
            if str(collab_id) != comment.user_id_from_me:
                collab_notification_doc = {
                    "NotificationFrom": ObjectId(comment.user_id),
                    "NotificationTo": collab_id,
                    "Message": encrypted_message,
                    "PostId": comment_id,
                    "IsRead": False,
                    "UploadAt": datetime.datetime.now(datetime.timezone.utc).isoformat().replace('Z', '+00:00'),
                    "Type": encrypted_collaboration_type,
                    "status": "theory"
                }
                notifications_collection.insert_one(collab_notification_doc)
                serialized_collab_notification = serialize_notification(collab_notification_doc)
                await broadcast_notification(str(collab_id), "add", serialized_collab_notification)

    # replay
    if comment.parent_comment_id:
        parent_comment_data = theories_comment_collection.find_one({"_id": ObjectId(comment.parent_comment_id)})
        encrypted_collaboration_type_replay = encrypt_data("new_replay", ENCRYPTION_KEY)

        parent_user_id = parent_comment_data['user_id']
        replay_message = f"@{username} : {trimmed_text}"
        encrypted_message_replay = encrypt_data(replay_message, ENCRYPTION_KEY)

        notification_doc_replay = {
            "NotificationFrom": ObjectId(comment.user_id),
            "NotificationTo": ObjectId(parent_user_id),
            "Message": encrypted_message_replay,
            "PostId": comment_id,
            "IsRead": False,
            "UploadAt": datetime.datetime.now(datetime.timezone.utc).isoformat().replace('Z', '+00:00'),
            "Type": encrypted_collaboration_type_replay,
            "status": "theory"
        }
        notifications_collection.insert_one(notification_doc_replay)
        serialized_notification_replay = serialize_notification(notification_doc_replay)
        await broadcast_notification(str(parent_user_id), "add", serialized_notification_replay)

    return {
        "success": True,
        "comment_id": str(comment_id),
        "parent_comment_id": comment.parent_comment_id,
        "text": comment.text,
        "CountReplays": 0,
        "CountLike": 0,
        "created_at": comment_data["created_at"].isoformat() + "Z",
        "is_edited": False,
    }

class ImageCommentCreate(BaseModel):
    user_id: str
    image_id: str
    text: str
    parent_comment_id: Optional[str]
    user_id_from_me: str

@router.post("/add-comment-in-image")
async def add_comment(comment: ImageCommentCreate):
    comment_text = encrypt_data(comment.text, ENCRYPTION_KEY)

    comment_data = {
        "user_id": ObjectId(comment.user_id),
        "image_id": ObjectId(comment.image_id),
        "text": comment_text,
        "created_at": datetime.datetime.now(datetime.timezone.utc),
        "parent_comment_id": ObjectId(comment.parent_comment_id) if comment.parent_comment_id else None,
        "replays": [],
        "CountReplays": 0,
        "CountLike": 0,
        "pinned": False,
    }

    comment_id = images_comment_collection.insert_one(comment_data).inserted_id

    if comment.parent_comment_id:
        images_comment_collection.update_one(
            {"_id": ObjectId(comment.parent_comment_id)},
            {
                "$push": {"replays": comment_id},
                "$inc": {"CountReplays": 1}
            }
        )
        # Broadcast updated replay count
        parent_comment = images_comment_collection.find_one({"_id": ObjectId(comment.parent_comment_id)})
        await manager_image.broadcast(comment.image_id, {
            "type": "replay_count",
            "comment_id": str(comment.parent_comment_id),
            "value": parent_comment.get('CountReplays', 0)
        })

    images_collection.update_one(
        {"_id": ObjectId(comment.image_id)},
        {"$inc": {"CountComment": 1}}
    )

    # Broadcast updated comment count
    image_data = images_collection.find_one({'_id': ObjectId(comment.image_id)})
    await manager_image.broadcast(comment.image_id, {
        "type": "comment_count",
        "value": image_data.get('CountComment', 0)
    })

    # User information for the comment
    user_info = users_collection.find_one({"_id": ObjectId(comment.user_id)})
    if not user_info:
        raise HTTPException(status_code=404, detail="User not found")

    username = user_info.get("Username", "UnknownUser")
    decrypted_display = decrypt_data(user_info.get('Display', ''), ENCRYPTION_KEY) if user_info.get('Display') else ''

    # Broadcast new comment
    await manager_image.broadcast(comment.image_id, {
        "type": "new_comment",
        "comment": {
            "id": str(comment_id),
            "text": comment.text,
            "created_at": comment_data["created_at"].isoformat(),
            "user_id": str(comment.user_id),
            "username": username,
            "display": decrypted_display,
            "parent_comment_id": str(comment.parent_comment_id) if comment.parent_comment_id else None,
            "CountReplays": 0,
            "CountLike": 0,
            "is_edited": False,
        }
    })

    # --- Create message for notification ---
    raw_comment = comment.text.strip()
    trimmed_text = raw_comment[:500] + ("..." if len(raw_comment) > 500 else "")
    full_message = f"@{username} : {trimmed_text}"
    encrypted_message = encrypt_data(full_message, ENCRYPTION_KEY)

    # comment
    encrypted_collaboration_type = encrypt_data("new_comment", ENCRYPTION_KEY)
    notification_doc = {
        "NotificationFrom": ObjectId(comment.user_id),
        "NotificationTo": ObjectId(comment.user_id_from_me),
        "Message": encrypted_message,
        "PostId": comment_id,
        "IsRead": False,
        "UploadAt": datetime.datetime.now(datetime.timezone.utc).isoformat().replace('Z', '+00:00'),
        "Type": encrypted_collaboration_type,
        "status": "image"
    }
    notifications_collection.insert_one(notification_doc)
    serialized_notification = serialize_notification(notification_doc)
    await broadcast_notification(str(comment.user_id_from_me), "add", serialized_notification)

    # Get collaborator_ids from post and send notification to each (except owner)
    if image_data:
        collaborators_value = image_data.get('CollaborationAccounts', '')
        collaborators_str = str(collaborators_value)  # Explicitly convert to string to avoid TypeError
        collaborator_ids = re.findall(r"[0-9a-fA-F]{24}", collaborators_str)
        collaborator_object_ids = [ObjectId(cid) for cid in collaborator_ids]

        for collab_id in collaborator_object_ids:
            if str(collab_id) != comment.user_id_from_me:
                collab_notification_doc = {
                    "NotificationFrom": ObjectId(comment.user_id),
                    "NotificationTo": collab_id,
                    "Message": encrypted_message,
                    "PostId": comment_id,
                    "IsRead": False,
                    "UploadAt": datetime.datetime.now(datetime.timezone.utc).isoformat().replace('Z', '+00:00'),
                    "Type": encrypted_collaboration_type,
                    "status": "image"
                }
                notifications_collection.insert_one(collab_notification_doc)
                serialized_collab_notification = serialize_notification(collab_notification_doc)
                await broadcast_notification(str(collab_id), "add", serialized_collab_notification)

    # replay
    if comment.parent_comment_id:
        parent_comment_data = images_comment_collection.find_one({"_id": ObjectId(comment.parent_comment_id)})
        encrypted_collaboration_type_replay = encrypt_data("new_replay", ENCRYPTION_KEY)

        parent_user_id = parent_comment_data['user_id']
        replay_message = f"@{username} : {trimmed_text}"
        encrypted_message_replay = encrypt_data(replay_message, ENCRYPTION_KEY)

        notification_doc_replay = {
            "NotificationFrom": ObjectId(comment.user_id),
            "NotificationTo": ObjectId(parent_user_id),
            "Message": encrypted_message_replay,
            "PostId": comment_id,
            "IsRead": False,
            "UploadAt": datetime.datetime.now(datetime.timezone.utc).isoformat().replace('Z', '+00:00'),
            "Type": encrypted_collaboration_type_replay,
            "status": "image"
        }
        notifications_collection.insert_one(notification_doc_replay)
        serialized_notification_replay = serialize_notification(notification_doc_replay)
        await broadcast_notification(str(parent_user_id), "add", serialized_notification_replay)

    return {
        "success": True,
        "comment_id": str(comment_id),
        "parent_comment_id": comment.parent_comment_id,
        "text": comment.text,
        "CountReplays": 0,
        "CountLike": 0,
        "created_at": comment_data["created_at"].isoformat() + "Z",
        "is_edited": False,
    }

class ProductCommentCreate(BaseModel):
    user_id: str
    product_id: str
    text: str
    parent_comment_id: Optional[str]
    user_id_from_me: str

@router.post("/add-comment-in-product")
async def add_comment(comment: ProductCommentCreate):
    comment_text = encrypt_data(comment.text, ENCRYPTION_KEY)

    comment_data = {
        "user_id": ObjectId(comment.user_id),
        "product_id": ObjectId(comment.product_id),
        "text": comment_text,
        "created_at": datetime.datetime.now(datetime.timezone.utc),
        "parent_comment_id": ObjectId(comment.parent_comment_id) if comment.parent_comment_id else None,
        "replays": [],
        "CountReplays": 0,
        "CountLike": 0,
        "pinned": False,
    }

    comment_id = products_comment_collection.insert_one(comment_data).inserted_id

    if comment.parent_comment_id:
        products_comment_collection.update_one(
            {"_id": ObjectId(comment.parent_comment_id)},
            {
                "$push": {"replays": comment_id},
                "$inc": {"CountReplays": 1}
            }
        )
        # Broadcast updated replay count
        parent_comment = products_comment_collection.find_one({"_id": ObjectId(comment.parent_comment_id)})
        await manager_product.broadcast(comment.product_id, {
            "type": "replay_count",
            "comment_id": str(comment.parent_comment_id),
            "value": parent_comment.get('CountReplays', 0)
        })

    products_collection.update_one(
        {"_id": ObjectId(comment.product_id)},
        {"$inc": {"CountComment": 1}}
    )

    # Broadcast updated comment count
    product_data = products_collection.find_one({'_id': ObjectId(comment.product_id)})
    await manager_product.broadcast(comment.product_id, {
        "type": "comment_count",
        "value": product_data.get('CountComment', 0)
    })

    # User information for the comment
    user_info = users_collection.find_one({"_id": ObjectId(comment.user_id)})
    if not user_info:
        raise HTTPException(status_code=404, detail="User not found")

    username = user_info.get("Username", "UnknownUser")
    decrypted_display = decrypt_data(user_info.get('Display', ''), ENCRYPTION_KEY) if user_info.get('Display') else ''

    # Broadcast new comment
    await manager_product.broadcast(comment.product_id, {
        "type": "new_comment",
        "comment": {
            "id": str(comment_id),
            "text": comment.text,
            "created_at": comment_data["created_at"].isoformat(),
            "user_id": str(comment.user_id),
            "username": username,
            "display": decrypted_display,
            "parent_comment_id": str(comment.parent_comment_id) if comment.parent_comment_id else None,
            "CountReplays": 0,
            "CountLike": 0,
            "is_edited": False,
        }
    })

    # --- Create message for notification ---
    raw_comment = comment.text.strip()
    trimmed_text = raw_comment[:500] + ("..." if len(raw_comment) > 500 else "")
    full_message = f"@{username} : {trimmed_text}"
    encrypted_message = encrypt_data(full_message, ENCRYPTION_KEY)

    # comment
    encrypted_collaboration_type = encrypt_data("new_comment", ENCRYPTION_KEY)
    notification_doc = {
        "NotificationFrom": ObjectId(comment.user_id),
        "NotificationTo": ObjectId(comment.user_id_from_me),
        "Message": encrypted_message,
        "PostId": comment_id,
        "IsRead": False,
        "UploadAt": datetime.datetime.now(datetime.timezone.utc).isoformat().replace('Z', '+00:00'),
        "Type": encrypted_collaboration_type,
        "status": "product"
    }
    notifications_collection.insert_one(notification_doc)
    serialized_notification = serialize_notification(notification_doc)
    await broadcast_notification(str(comment.user_id_from_me), "add", serialized_notification)

    # Get collaborator_ids from post and send notification to each (except owner)
    if product_data:
        collaborators_value = product_data.get('CollaborationAccounts', '')
        collaborators_str = str(collaborators_value)  # Explicitly convert to string to avoid TypeError
        collaborator_ids = re.findall(r"[0-9a-fA-F]{24}", collaborators_str)
        collaborator_object_ids = [ObjectId(cid) for cid in collaborator_ids]

        for collab_id in collaborator_object_ids:
            if str(collab_id) != comment.user_id_from_me:
                collab_notification_doc = {
                    "NotificationFrom": ObjectId(comment.user_id),
                    "NotificationTo": collab_id,
                    "Message": encrypted_message,
                    "PostId": comment_id,
                    "IsRead": False,
                    "UploadAt": datetime.datetime.now(datetime.timezone.utc).isoformat().replace('Z', '+00:00'),
                    "Type": encrypted_collaboration_type,
                    "status": "product"
                }
                notifications_collection.insert_one(collab_notification_doc)
                serialized_collab_notification = serialize_notification(collab_notification_doc)
                await broadcast_notification(str(collab_id), "add", serialized_collab_notification)

    # replay
    if comment.parent_comment_id:
        parent_comment_data = products_comment_collection.find_one({"_id": ObjectId(comment.parent_comment_id)})
        encrypted_collaboration_type_replay = encrypt_data("new_replay", ENCRYPTION_KEY)

        parent_user_id = parent_comment_data['user_id']
        replay_message = f"@{username} : {trimmed_text}"
        encrypted_message_replay = encrypt_data(replay_message, ENCRYPTION_KEY)

        notification_doc_replay = {
            "NotificationFrom": ObjectId(comment.user_id),
            "NotificationTo": ObjectId(parent_user_id),
            "Message": encrypted_message_replay,
            "PostId": comment_id,
            "IsRead": False,
            "UploadAt": datetime.datetime.now(datetime.timezone.utc).isoformat().replace('Z', '+00:00'),
            "Type": encrypted_collaboration_type_replay,
            "status": "product"
        }
        notifications_collection.insert_one(notification_doc_replay)
        serialized_notification_replay = serialize_notification(notification_doc_replay)
        await broadcast_notification(str(parent_user_id), "add", serialized_notification_replay)

    return {
        "success": True,
        "comment_id": str(comment_id),
        "parent_comment_id": comment.parent_comment_id,
        "text": comment.text,
        "CountReplays": 0,
        "CountLike": 0,
        "created_at": comment_data["created_at"].isoformat() + "Z",
        "is_edited": False,
    }

class VideoDeleteCommentRequest(BaseModel):
    user_id: str
    comment_id: str

@router.post("/delete-video-comment")
async def delete_comment(request: VideoDeleteCommentRequest):
    # Validate ObjectId for user_id and comment_id
    if not ObjectId.is_valid(request.user_id) or not ObjectId.is_valid(request.comment_id):
        raise HTTPException(status_code=400, detail="Invalid user_id or comment_id format")

    # Get comment from database
    comment = videos_comment_collection.find_one({"_id": ObjectId(request.comment_id)})
    if not comment:
        raise HTTPException(status_code=404, detail="Comment not found")

    # Check comment owner
    # if str(comment["user_id"]) != request.user_id:
    #     raise HTTPException(status_code=403, detail="You are not authorized to delete this comment")

    # Collect all comment and replay IDs for deletion
    comment_ids_to_delete = [ObjectId(request.comment_id)]
    replay_ids = comment.get("replays", [])

    # If tree structure is possible in the future, collect all sub-replays
    def collect_replay_ids(comment_id):
        comment = videos_comment_collection.find_one({"_id": comment_id})
        if not comment:
            return
        for replay_id in comment.get("replays", []):
            comment_ids_to_delete.append(replay_id)
            collect_replay_ids(replay_id)

    for replay_id in replay_ids:
        comment_ids_to_delete.append(replay_id)
        collect_replay_ids(replay_id)

    # If comment is a replay, remove from parent
    if comment["parent_comment_id"]:
        videos_comment_collection.update_one(
            {"_id": ObjectId(comment["parent_comment_id"])},
            {
                "$pull": {"replays": ObjectId(request.comment_id)},
                "$inc": {"CountReplays": -1}
            }
        )
        # Broadcast replay count update
        parent_comment = videos_comment_collection.find_one({"_id": ObjectId(comment["parent_comment_id"])})
        await manager_video.broadcast(str(comment["video_id"]), {
            "type": "replay_count",
            "comment_id": str(comment["parent_comment_id"]),
            "value": parent_comment.get('CountReplays', 0)
        })

    # Delete comments and replays
    if comment_ids_to_delete:
        videos_comment_collection.delete_many({"_id": {"$in": comment_ids_to_delete}})
        # Delete related likes from CommentLikes
        videos_comment_likes.delete_many({"comment_id": {"$in": comment_ids_to_delete}})
        # Delete comment messages
        notifications_collection.delete_many({"PostId": {"$in": comment_ids_to_delete}})

    # Update comment count in VideosData
    videos_collection.update_one(
        {"_id": ObjectId(comment["video_id"])},
        {"$inc": {"CountComment": -len(comment_ids_to_delete)}}  # Considering all deleted comments
    )

    # Broadcast comment count update
    video_data = videos_collection.find_one({'_id': ObjectId(comment["video_id"])})
    await manager_video.broadcast(str(comment["video_id"]), {
        "type": "comment_count",
        "value": video_data.get('CountComment', 0)
    })

    # Broadcast delete_comment message for main comment
    await manager_video.broadcast(str(comment["video_id"]), {
        "type": "delete_comment",
        "comment_id": str(request.comment_id),
        "parent_comment_id": str(comment["parent_comment_id"]) if comment["parent_comment_id"] else str(None)
    })

    return {"success": True}

class ArticleDeleteCommentRequest(BaseModel):
    user_id: str
    comment_id: str

@router.post("/delete-article-comment")
async def delete_article_comment(request: ArticleDeleteCommentRequest):
    if not ObjectId.is_valid(request.user_id) or not ObjectId.is_valid(request.comment_id):
        raise HTTPException(status_code=400, detail="Invalid user_id or comment_id format")

    comment = article_comment_collection.find_one({"_id": ObjectId(request.comment_id)})

    if not comment:
        raise HTTPException(status_code=404, detail="Comment not found")

    if str(comment["user_id"]) != request.user_id:
        raise HTTPException(status_code=403, detail="You are not authorized to delete this comment")

    comment_ids_to_delete = [ObjectId(request.comment_id)]

    replay_ids = comment.get("replays", [])

    def collect_replay_ids(comment_id):
        comment_obj = article_comment_collection.find_one({"_id": comment_id})
        if not comment_obj:
            return
        for replay_id in comment_obj.get("replays", []):
            comment_ids_to_delete.append(replay_id)
            collect_replay_ids(replay_id)

    for replay_id in replay_ids:
        comment_ids_to_delete.append(replay_id)
        collect_replay_ids(replay_id)

    if comment.get("parent_comment_id"):
        article_comment_collection.update_one(
            {"_id": ObjectId(comment["parent_comment_id"])},
            {
                "$pull": {"replays": ObjectId(request.comment_id)},
                "$inc": {"CountReplays": -1}
            }
        )
        parent_comment = article_comment_collection.find_one({"_id": ObjectId(comment["parent_comment_id"])})
        post_id = str(comment.get("article_id"))

        await manager_article.broadcast(post_id, {
            "type": "replay_count",
            "comment_id": str(comment["parent_comment_id"]),
            "value": parent_comment.get("CountReplays", 0)
        })

    article_comment_collection.delete_many({"_id": {"$in": comment_ids_to_delete}})
    article_comment_likes.delete_many({"comment_id": {"$in": comment_ids_to_delete}})

    notifications_collection.delete_many({"PostId": {"$in": comment_ids_to_delete}})

    post_id = comment.get("article_id")
    articles_collection.update_one(
        {"_id": ObjectId(post_id)},
        {"$inc": {"CountComment": -len(comment_ids_to_delete)}}
    )
    post_data = articles_collection.find_one({"_id": ObjectId(post_id)})

    await manager_article.broadcast(str(post_id), {
        "type": "comment_count",
        "value": post_data.get("CountComment", 0)
    })

    await manager_article.broadcast(str(post_id), {
        "type": "delete_comment",
        "comment_id": str(request.comment_id),
        "parent_comment_id": str(comment.get("parent_comment_id")) if comment.get("parent_comment_id") else None
    })

    return {"success": True}

class TheoryDeleteCommentRequest(BaseModel): 
    user_id: str
    comment_id: str

@router.post("/delete-theory-comment")
async def delete_comment(request: TheoryDeleteCommentRequest):
    if not ObjectId.is_valid(request.user_id) or not ObjectId.is_valid(request.comment_id):
        raise HTTPException(status_code=400, detail="Invalid user_id or comment_id format")

    # Search for comment in both collections: image and video
    comment = theories_comment_collection.find_one({"_id": ObjectId(request.comment_id)})

    if not comment:
        raise HTTPException(status_code=404, detail="Comment not found")

    if str(comment["user_id"]) != request.user_id:
        raise HTTPException(status_code=403, detail="You are not authorized to delete this comment")

    comment_ids_to_delete = [ObjectId(request.comment_id)]

    replay_ids = comment.get("replays", [])

    def collect_replay_ids(comment_id):
        comment = theories_comment_collection.find_one({"_id": comment_id})
        if not comment:
            return
        for replay_id in comment.get("replays", []):
            comment_ids_to_delete.append(replay_id)
            collect_replay_ids(replay_id)

    for replay_id in replay_ids:
        comment_ids_to_delete.append(replay_id)
        collect_replay_ids(replay_id)

    # If replay exists — remove from parent replays
    if comment.get("parent_comment_id"):
        theories_comment_collection.update_one(
            {"_id": ObjectId(comment["parent_comment_id"])},
            {
                "$pull": {"replays": ObjectId(request.comment_id)},
                "$inc": {"CountReplays": -1}
            }
        )
        # Broadcast CountReplays change
        parent_comment = theories_comment_collection.find_one({"_id": ObjectId(comment["parent_comment_id"])})
        post_id = str(comment.get("theory_id"))

        await manager_theory.broadcast(post_id, {
            "type": "replay_count",
            "comment_id": str(comment["parent_comment_id"]),
            "value": parent_comment.get("CountReplays", 0)
        })

    # Delete comment and replays
    theories_comment_collection.delete_many({"_id": {"$in": comment_ids_to_delete}})
    theories_comment_likes.delete_many({"comment_id": {"$in": comment_ids_to_delete}})
    notifications_collection.delete_many({"PostId": {"$in": comment_ids_to_delete}})

    # Update comment count in post (theory)
    post_id = comment.get("theory_id")
    theory_collection.update_one(
        {"_id": ObjectId(post_id)},
        {"$inc": {"CountComment": -len(comment_ids_to_delete)}}
    )
    post_data = theory_collection.find_one({"_id": ObjectId(post_id)})

    # Broadcast: comment count update
    await manager_theory.broadcast(str(post_id), {
        "type": "comment_count",
        "value": post_data.get("CountComment", 0)
    })

    # Broadcast: comment deletion
    await manager_theory.broadcast(str(post_id), {
        "type": "delete_comment",
        "comment_id": str(request.comment_id),
        "parent_comment_id": str(comment.get("parent_comment_id")) if comment.get("parent_comment_id") else str(None)
    })

    return {"success": True}

class ImageDeleteCommentRequest(BaseModel): 
    user_id: str
    comment_id: str

@router.post("/delete-image-comment")
async def delete_comment(request: ImageDeleteCommentRequest):
    if not ObjectId.is_valid(request.user_id) or not ObjectId.is_valid(request.comment_id):
        raise HTTPException(status_code=400, detail="Invalid user_id or comment_id format")

    # Search for comment in both collections: image and video
    comment = images_comment_collection.find_one({"_id": ObjectId(request.comment_id)})

    if not comment:
        raise HTTPException(status_code=404, detail="Comment not found")

    # if str(comment["user_id"]) != request.user_id:
    #     raise HTTPException(status_code=403, detail="You are not authorized to delete this comment")

    comment_ids_to_delete = [ObjectId(request.comment_id)]

    replay_ids = comment.get("replays", [])

    def collect_replay_ids(comment_id):
        comment = images_comment_collection.find_one({"_id": comment_id})
        if not comment:
            return
        for replay_id in comment.get("replays", []):
            comment_ids_to_delete.append(replay_id)
            collect_replay_ids(replay_id)

    for replay_id in replay_ids:
        comment_ids_to_delete.append(replay_id)
        collect_replay_ids(replay_id)

    # If replay exists — remove from parent replays
    if comment.get("parent_comment_id"):
        images_comment_collection.update_one(
            {"_id": ObjectId(comment["parent_comment_id"])},
            {
                "$pull": {"replays": ObjectId(request.comment_id)},
                "$inc": {"CountReplays": -1}
            }
        )
        # Broadcast CountReplays change
        parent_comment = images_comment_collection.find_one({"_id": ObjectId(comment["parent_comment_id"])})
        post_id = str(comment.get("image_id"))

        await manager_image.broadcast(post_id, {
            "type": "replay_count",
            "comment_id": str(comment["parent_comment_id"]),
            "value": parent_comment.get("CountReplays", 0)
        })

    # Delete comment and replays
    images_comment_collection.delete_many({"_id": {"$in": comment_ids_to_delete}})
    images_comment_likes.delete_many({"comment_id": {"$in": comment_ids_to_delete}})
    notifications_collection.delete_many({"PostId": {"$in": comment_ids_to_delete}})

    # Update comment count in post (image)
    post_id = comment.get("image_id")
    images_collection.update_one(
        {"_id": ObjectId(post_id)},
        {"$inc": {"CountComment": -len(comment_ids_to_delete)}}
    )
    post_data = images_collection.find_one({"_id": ObjectId(post_id)})

    # Broadcast: comment count update
    await manager_image.broadcast(str(post_id), {
        "type": "comment_count",
        "value": post_data.get("CountComment", 0)
    })

    # Broadcast: comment deletion
    await manager_image.broadcast(str(post_id), {
        "type": "delete_comment",
        "comment_id": str(request.comment_id),
        "parent_comment_id": str(comment.get("parent_comment_id")) if comment.get("parent_comment_id") else str(None)
    })

    return {"success": True}

class ProductDeleteCommentRequest(BaseModel): 
    user_id: str
    comment_id: str

@router.post("/delete-product-comment")
async def delete_comment(request: ProductDeleteCommentRequest):
    if not ObjectId.is_valid(request.user_id) or not ObjectId.is_valid(request.comment_id):
        raise HTTPException(status_code=400, detail="Invalid user_id or comment_id format")

    comment = products_comment_collection.find_one({"_id": ObjectId(request.comment_id)})
    db_target = products_db

    if not comment:
        raise HTTPException(status_code=404, detail="Comment not found")

    # if str(comment["user_id"]) != request.user_id:
    #     raise HTTPException(status_code=403, detail="You are not authorized to delete this comment")

    comment_ids_to_delete = [ObjectId(request.comment_id)]
    replay_ids = comment.get("replays", [])

    def collect_replay_ids(comment_id):
        comment = db_target["Comments"].find_one({"_id": comment_id})
        if not comment:
            return
        for replay_id in comment.get("replays", []):
            comment_ids_to_delete.append(replay_id)
            collect_replay_ids(replay_id)

    for replay_id in replay_ids:
        comment_ids_to_delete.append(replay_id)
        collect_replay_ids(replay_id)

    # If replay exists — remove from parent replays
    if comment.get("parent_comment_id"):
        db_target["Comments"].update_one(
            {"_id": ObjectId(comment["parent_comment_id"])},
            {
                "$pull": {"replays": ObjectId(request.comment_id)},
                "$inc": {"CountReplays": -1}
            }
        )
        # Broadcast CountReplays change
        parent_comment = db_target["Comments"].find_one({"_id": ObjectId(comment["parent_comment_id"])})
        product_id = str(comment.get("product_id"))

        await manager_product.broadcast(product_id, {
            "type": "replay_count",
            "comment_id": str(comment["parent_comment_id"]),
            "value": parent_comment.get("CountReplays", 0)
        })

    # Delete comment and replays
    db_target["Comments"].delete_many({"_id": {"$in": comment_ids_to_delete}})
    db_target["CommentLikes"].delete_many({"comment_id": {"$in": comment_ids_to_delete}})
    db_target["ProductCommentReports"].delete_many({"comment_id": {"$in": comment_ids_to_delete}})

    # Delete comment messages
    notifications_collection.delete_many({"PostId": {"$in": comment_ids_to_delete}})

    # Update comment count in post (product)
    product_id = comment.get("product_id")
    products_collection.update_one(
        {"_id": ObjectId(product_id)},
        {"$inc": {"CountComment": -len(comment_ids_to_delete)}}
    )
    post_data = products_collection.find_one({"_id": ObjectId(product_id)})

    # Broadcast: comment count update
    await manager_product.broadcast(str(product_id), {
        "type": "comment_count",
        "value": post_data.get("CountComment", 0)
    })

    # Broadcast: comment deletion
    await manager_product.broadcast(str(product_id), {
        "type": "delete_comment",
        "comment_id": str(request.comment_id),
        "parent_comment_id": str(comment.get("parent_comment_id")) if comment.get("parent_comment_id") else str(None)
    })

    # Broadcast for manager_account
    await manager_account.broadcast(str(product_id), {
        "type": "delete_comment",
        "comment_id": str(request.comment_id),
        "parent_comment_id": str(comment.get("parent_comment_id")) if comment.get("parent_comment_id") else str(None)
    })

    return {"success": True}

class VideoCommentLikeRequest(BaseModel):
    user_id: str
    comment_id: str
    video_id: str

@router.post("/unlike-video-comment")
async def unlike_comment(request: VideoCommentLikeRequest):
    # Check if the user has liked this comment
    existing_like = videos_comment_likes.find_one({
        "user_id": ObjectId(request.user_id),
        "comment_id": ObjectId(request.comment_id)
    })

    if not existing_like:
        raise HTTPException(
            status_code=400,
            detail="This user has not liked this comment or has already unliked it"
        )

    result = videos_comment_likes.delete_one({
        "user_id": ObjectId(request.user_id),
        "comment_id": ObjectId(request.comment_id),
        "video_id": ObjectId(request.video_id),
    })

    if result.deleted_count == 0:
        return {"success": True, "message": "Not previously liked"}

    videos_comment_collection.update_one(
        {"_id": ObjectId(request.comment_id)},
        {"$inc": {"CountLike": -1}}
    )

    # Broadcast updated like count
    comment_data = videos_comment_collection.find_one({"_id": ObjectId(request.comment_id)})
    await manager_video.broadcast(str(comment_data["video_id"]), {
        "type": "comment_like_status",
        "comment_id": str(request.comment_id),
        "user_id": request.user_id,  # ID of the user who unliked
        "liked": False,
        "value": comment_data.get('CountLike', 0)
    })

    # Add general message for count update (without status change)
    await manager_video.broadcast(str(comment_data["video_id"]), {
        "type": "comment_like_count",
        "comment_id": str(request.comment_id),
        "value": comment_data.get('CountLike', 0)
    })

    return {"success": True}

class ArticleCommentLikeRequest(BaseModel):
    user_id: str
    comment_id: str
    article_id: str

@router.post("/unlike-article-comment")
async def unlike_article_comment(request: ArticleCommentLikeRequest):
    existing_like = article_comment_likes.find_one({
        "user_id": ObjectId(request.user_id),
        "comment_id": ObjectId(request.comment_id)
    })

    if not existing_like:
        raise HTTPException(
            status_code=400,
            detail="This user has not liked this comment or has already unliked it"
        )

    result = article_comment_likes.delete_one({
        "user_id": ObjectId(request.user_id),
        "comment_id": ObjectId(request.comment_id),
        "article_id": ObjectId(request.article_id),
    })

    if result.deleted_count == 0:
        return {"success": True, "message": "Not previously liked"}

    article_comment_collection.update_one(
        {"_id": ObjectId(request.comment_id)},
        {"$inc": {"CountLike": -1}}
    )

    comment_data = article_comment_collection.find_one({"_id": ObjectId(request.comment_id)})
    await manager_article.broadcast(str(comment_data["article_id"]), {
        "type": "comment_like_status",
        "comment_id": str(request.comment_id),
        "user_id": request.user_id,
        "liked": False,
        "value": comment_data.get('CountLike', 0)
    })

    await manager_article.broadcast(str(comment_data["article_id"]), {
        "type": "comment_like_count",
        "comment_id": str(request.comment_id),
        "value": comment_data.get('CountLike', 0)
    })

    return {"success": True}

class TheoryCommentLikeRequest(BaseModel):
    user_id: str
    comment_id: str
    theory_id: str

@router.post("/unlike-theory-comment")
async def unlike_comment(request: TheoryCommentLikeRequest):
    # Check if the user has liked this comment
    existing_like = theories_comment_likes.find_one({
        "user_id": ObjectId(request.user_id),
        "comment_id": ObjectId(request.comment_id)
    })

    if not existing_like:
        raise HTTPException(
            status_code=400,
            detail="This user has not liked this comment or has already unliked it"
        )

    result = theories_comment_likes.delete_one({
        "user_id": ObjectId(request.user_id),
        "comment_id": ObjectId(request.comment_id),
        "theory_id": ObjectId(request.theory_id),
    })

    if result.deleted_count == 0:
        return {"success": True, "message": "Not previously liked"}

    theories_comment_collection.update_one(
        {"_id": ObjectId(request.comment_id)},
        {"$inc": {"CountLike": -1}}
    )

    # Broadcast updated like count
    comment_data = theories_comment_collection.find_one({"_id": ObjectId(request.comment_id)})
    await manager_theory.broadcast(str(comment_data["theory_id"]), {
        "type": "comment_like_status",
        "comment_id": str(request.comment_id),
        "user_id": request.user_id,  # ID of the user who unliked
        "liked": False,
        "value": comment_data.get('CountLike', 0)
    })

    # Add general message for count update (without status change)
    await manager_theory.broadcast(str(comment_data["theory_id"]), {
        "type": "comment_like_count",
        "comment_id": str(request.comment_id),
        "value": comment_data.get('CountLike', 0)
    })

    return {"success": True}

class ImageCommentLikeRequest(BaseModel):
    user_id: str
    comment_id: str
    image_id: str

@router.post("/unlike-image-comment")
async def unlike_comment(request: ImageCommentLikeRequest):
    # Check if the user has liked this comment
    existing_like = images_comment_likes.find_one({
        "user_id": ObjectId(request.user_id),
        "comment_id": ObjectId(request.comment_id)
    })

    if not existing_like:
        # Instead of exception, return message
        return {"success": True, "message": "Not previously liked"}

    result = images_comment_likes.delete_one({
        "user_id": ObjectId(request.user_id),
        "comment_id": ObjectId(request.comment_id),
        "image_id": ObjectId(request.image_id),
    })

    images_comment_collection.update_one(
        {"_id": ObjectId(request.comment_id)},
        {"$inc": {"CountLike": -1}}
    )

    # Broadcast updated like count
    comment_data = images_comment_collection.find_one({"_id": ObjectId(request.comment_id)})
    await manager_image.broadcast(str(comment_data["image_id"]), {
        "type": "comment_like_status",
        "comment_id": str(request.comment_id),
        "user_id": request.user_id,  # ID of the user who unliked
        "liked": False,
        "value": comment_data.get('CountLike', 0)
    })

    # Add general message for count update (without status change)
    await manager_image.broadcast(str(comment_data["image_id"]), {
        "type": "comment_like_count",
        "comment_id": str(request.comment_id),
        "value": comment_data.get('CountLike', 0)
    })

    return {"success": True}

class ProductCommentLikeRequest(BaseModel):
    user_id: str
    comment_id: str
    product_id: str

@router.post("/unlike-product-comment")
async def unlike_comment(request: ProductCommentLikeRequest):
    # Check if the user has liked this comment
    existing_like = product_comment_likes.find_one({
        "user_id": ObjectId(request.user_id),
        "comment_id": ObjectId(request.comment_id)
    })

    if not existing_like:
        raise HTTPException(
            status_code=400,
            detail="This user has not liked this comment or has already unliked it"
        )

    result = product_comment_likes.delete_one({
        "user_id": ObjectId(request.user_id),
        "comment_id": ObjectId(request.comment_id),
        "product_id": ObjectId(request.product_id),
    })

    if result.deleted_count == 0:
        return {"success": True, "message": "Not previously liked"}

    products_comment_collection.update_one(
        {"_id": ObjectId(request.comment_id)},
        {"$inc": {"CountLike": -1}}
    )

    # Broadcast updated like count
    comment_data = products_comment_collection.find_one({"_id": ObjectId(request.comment_id)})
    await manager_product.broadcast(str(comment_data["product_id"]), {
        "type": "comment_like_status",
        "comment_id": str(request.comment_id),
        "user_id": request.user_id,  # ID of the user who unliked
        "liked": False,
        "value": comment_data.get('CountLike', 0)
    })

    # Add general message for count update (without status change)
    await manager_product.broadcast(str(comment_data["product_id"]), {
        "type": "comment_like_count",
        "comment_id": str(request.comment_id),
        "value": comment_data.get('CountLike', 0)
    })

    return {"success": True}

@router.post("/like-video-comment")
async def like_comment(request: VideoCommentLikeRequest):
    # Check if the user has already liked this comment
    existing_like = videos_comment_likes.find_one({
        "user_id": ObjectId(request.user_id),
        "comment_id": ObjectId(request.comment_id)
    })

    if existing_like:
        raise HTTPException(
            status_code=400,
            detail="This user has already liked this comment"
        )

    existing_like = videos_comment_likes.find_one({
        "user_id": ObjectId(request.user_id),
        "comment_id": ObjectId(request.comment_id)
    })

    if existing_like:
        return {"success": True, "message": "Already liked"}

    videos_comment_likes.insert_one({
        "user_id": ObjectId(request.user_id),
        "comment_id": ObjectId(request.comment_id),
        "video_id": ObjectId(request.video_id),
        "created_at": datetime.datetime.now(datetime.timezone.utc)
    })

    videos_comment_collection.update_one(
        {"_id": ObjectId(request.comment_id)},
        {"$inc": {"CountLike": 1}}
    )

    # Broadcast updated like count
    comment_data = videos_comment_collection.find_one({"_id": ObjectId(request.comment_id)})
    await manager_video.broadcast(str(comment_data["video_id"]), {
        "type": "comment_like_status",
        "comment_id": str(request.comment_id),
        "user_id": request.user_id,  # ID of the user who liked
        "liked": True,
        "value": comment_data.get('CountLike', 0)
    })

    # Add general message for count update (without status change)
    await manager_video.broadcast(str(comment_data["video_id"]), {
        "type": "comment_like_count",
        "comment_id": str(request.comment_id),
        "value": comment_data.get('CountLike', 0)
    })

    return {"success": True}

@router.post("/like-article-comment")
async def like_article_comment(request: ArticleCommentLikeRequest):
    existing_like = article_comment_likes.find_one({
        "user_id": ObjectId(request.user_id),
        "comment_id": ObjectId(request.comment_id)
    })

    if existing_like:
        raise HTTPException(
            status_code=400,
            detail="This user has already liked this comment"
        )

    article_comment_likes.insert_one({
        "user_id": ObjectId(request.user_id),
        "comment_id": ObjectId(request.comment_id),
        "article_id": ObjectId(request.article_id),
        "created_at": datetime.datetime.now(datetime.timezone.utc)
    })

    article_comment_collection.update_one(
        {"_id": ObjectId(request.comment_id)},
        {"$inc": {"CountLike": 1}}
    )

    comment_data = article_comment_collection.find_one({"_id": ObjectId(request.comment_id)})
    await manager_article.broadcast(str(comment_data["article_id"]), {
        "type": "comment_like_status",
        "comment_id": str(request.comment_id),
        "user_id": request.user_id,
        "liked": True,
        "value": comment_data.get('CountLike', 0)
    })

    await manager_article.broadcast(str(comment_data["article_id"]), {
        "type": "comment_like_count",
        "comment_id": str(request.comment_id),
        "value": comment_data.get('CountLike', 0)
    })

    return {"success": True}

@router.post("/like-theory-comment")
async def like_comment(request: TheoryCommentLikeRequest):
    # Check if the user has already liked this comment
    existing_like = theories_comment_likes.find_one({
        "user_id": ObjectId(request.user_id),
        "comment_id": ObjectId(request.comment_id)
    })

    if existing_like:
        raise HTTPException(
            status_code=400,
            detail="This user has already liked this comment"
        )

    existing_like = theories_comment_likes.find_one({
        "user_id": ObjectId(request.user_id),
        "comment_id": ObjectId(request.comment_id)
    })

    if existing_like:
        return {"success": True, "message": "Already liked"}

    theories_comment_likes.insert_one({
        "user_id": ObjectId(request.user_id),
        "comment_id": ObjectId(request.comment_id),
        "theory_id": ObjectId(request.theory_id),
        "created_at": datetime.datetime.now(datetime.timezone.utc)
    })

    theories_comment_collection.update_one(
        {"_id": ObjectId(request.comment_id)},
        {"$inc": {"CountLike": 1}}
    )

    # Broadcast updated like count
    comment_data = theories_comment_collection.find_one({"_id": ObjectId(request.comment_id)})
    await manager_theory.broadcast(str(comment_data["theory_id"]), {
        "type": "comment_like_status",
        "comment_id": str(request.comment_id),
        "user_id": request.user_id,  # ID of the user who liked
        "liked": True,
        "value": comment_data.get('CountLike', 0)
    })

    # Add general message for count update (without status change)
    await manager_theory.broadcast(str(comment_data["theory_id"]), {
        "type": "comment_like_count",
        "comment_id": str(request.comment_id),
        "value": comment_data.get('CountLike', 0)
    })

    return {"success": True}

@router.post("/like-image-comment")
async def like_comment(request: ImageCommentLikeRequest):
    # Check if the user has already liked this comment
    existing_like = images_comment_likes.find_one({
        "user_id": ObjectId(request.user_id),
        "comment_id": ObjectId(request.comment_id)
    })

    if existing_like:
        # Instead of exception, return message
        return {"success": True, "message": "Already liked"}

    images_comment_likes.insert_one({
        "user_id": ObjectId(request.user_id),
        "comment_id": ObjectId(request.comment_id),
        "image_id": ObjectId(request.image_id),
        "created_at": datetime.datetime.now(datetime.timezone.utc)
    })

    images_comment_collection.update_one(
        {"_id": ObjectId(request.comment_id)},
        {"$inc": {"CountLike": 1}}
    )

    # Broadcast updated like count
    comment_data = images_comment_collection.find_one({"_id": ObjectId(request.comment_id)})
    await manager_image.broadcast(str(comment_data["image_id"]), {
        "type": "comment_like_status",
        "comment_id": str(request.comment_id),
        "user_id": request.user_id,  # ID of the user who liked
        "liked": True,
        "value": comment_data.get('CountLike', 0)
    })

    # Add general message for count update (without status change)
    await manager_image.broadcast(str(comment_data["image_id"]), {
        "type": "comment_like_count",
        "comment_id": str(request.comment_id),
        "value": comment_data.get('CountLike', 0)
    })

    return {"success": True}

@router.post("/like-product-comment")
async def like_comment(request: ProductCommentLikeRequest):
    # Check if the user has already liked this comment
    existing_like = product_comment_likes.find_one({
        "user_id": ObjectId(request.user_id),
        "comment_id": ObjectId(request.comment_id)
    })

    if existing_like:
        raise HTTPException(
            status_code=400,
            detail="This user has already liked this comment"
        )

    existing_like = product_comment_likes.find_one({
        "user_id": ObjectId(request.user_id),
        "comment_id": ObjectId(request.comment_id)
    })

    if existing_like:
        return {"success": True, "message": "Already liked"}

    product_comment_likes.insert_one({
        "user_id": ObjectId(request.user_id),
        "comment_id": ObjectId(request.comment_id),
        "product_id": ObjectId(request.product_id),
        "created_at": datetime.datetime.now(datetime.timezone.utc)
    })

    products_comment_collection.update_one(
        {"_id": ObjectId(request.comment_id)},
        {"$inc": {"CountLike": 1}}
    )

    # Broadcast updated like count
    comment_data = products_comment_collection.find_one({"_id": ObjectId(request.comment_id)})
    await manager_product.broadcast(str(comment_data["product_id"]), {
        "type": "comment_like_status",
        "comment_id": str(request.comment_id),
        "user_id": request.user_id,  # ID of the user who liked
        "liked": True,
        "value": comment_data.get('CountLike', 0)
    })

    # Add general message for count update (without status change)
    await manager_product.broadcast(str(comment_data["product_id"]), {
        "type": "comment_like_count",
        "comment_id": str(request.comment_id),
        "value": comment_data.get('CountLike', 0)
    })

    return {"success": True}

class VideoEditCommentRequest(BaseModel):
    user_id: str
    comment_id: str
    text: str

@router.post("/edit-video-comment")
async def edit_comment(request: VideoEditCommentRequest):
    if not ObjectId.is_valid(request.user_id) or not ObjectId.is_valid(request.comment_id):
        raise HTTPException(status_code=400, detail="Invalid user_id or comment_id format")

    comment = videos_comment_collection.find_one({"_id": ObjectId(request.comment_id)})

    if not comment:
        raise HTTPException(status_code=404, detail="Comment not found")

    if str(comment["user_id"]) != request.user_id:
        raise HTTPException(status_code=403, detail="You are not authorized to edit this comment")

    encrypted_text = encrypt_data(request.text, ENCRYPTION_KEY)
    new_timestamp = datetime.datetime.now(datetime.timezone.utc)

    # Update comment
    videos_comment_collection.update_one(
        {"_id": ObjectId(request.comment_id)},
        {
            "$set": {
                "text": encrypted_text,
                "is_edited": True,
                "edited_at": new_timestamp
            }
        }
    )

    user_info = users_collection.find_one({"_id": ObjectId(request.user_id)})
    if not user_info:
        raise HTTPException(status_code=404, detail="User not found")

    decrypted_display = decrypt_data(user_info.get("Display", ""), ENCRYPTION_KEY) if user_info.get("Display") else ""

    # 🔧 For notifications: Trim to 500 characters and encrypt
    trimmed_text = (request.text[:500] + '...') if len(request.text) > 500 else request.text
    formatted_message = f"@{user_info['Username']}: {trimmed_text}"
    encrypted_message = encrypt_data(formatted_message, ENCRYPTION_KEY)

    # 🔁 Update all notifications with this comment_id
    notifications_collection.update_many(
        {"PostId": ObjectId(request.comment_id)},
        {"$set": {"Message": encrypted_message}}
    )

    # Determine post ID for broadcast (video_id)
    post_id = str(comment.get("video_id"))

    await manager_video.broadcast(str(post_id), {
        "type": "edit_comment",
        "comment_id": str(request.comment_id),
        "text": request.text,
        "created_at": comment["created_at"].isoformat() + "Z",
        "user_id": str(comment["user_id"]),
        "username": user_info["Username"],
        "display": decrypted_display,
        "parent_comment_id": str(comment["parent_comment_id"]) if comment.get("parent_comment_id") else str(None),
        "CountReplays": comment.get("CountReplays", 0),
        "CountLike": comment.get("CountLike", 0),
        "pinned": comment.get("pinned", False),
        "is_edited": True,  # Add edit indicator
        "edited_at": new_timestamp.isoformat() + "Z"  # Add edit time
    })

    await manager_account.broadcast(str(post_id), {
        "type": "edit_comment",
        "comment_id": str(request.comment_id),
        "text": request.text,
        "created_at": comment["created_at"].isoformat() + "Z",
        "user_id": str(comment["user_id"]),
        "username": user_info["Username"],
        "display": decrypted_display,
        "parent_comment_id": str(comment["parent_comment_id"]) if comment.get("parent_comment_id") else str(None),
        "CountReplays": comment.get("CountReplays", 0),
        "CountLike": comment.get("CountLike", 0),
        "pinned": comment.get("pinned", False),
        "is_edited": True,  # Add edit indicator
        "edited_at": new_timestamp.isoformat() + "Z"  # Add edit time
    })

    return {"success": True}

class ArticleEditCommentRequest(BaseModel):
    user_id: str
    comment_id: str
    text: str

@router.post("/edit-article-comment")
async def edit_article_comment(request: ArticleEditCommentRequest):
    if not ObjectId.is_valid(request.user_id) or not ObjectId.is_valid(request.comment_id):
        raise HTTPException(status_code=400, detail="Invalid user_id or comment_id format")

    comment = article_comment_collection.find_one({"_id": ObjectId(request.comment_id)})

    if not comment:
        raise HTTPException(status_code=404, detail="Comment not found")

    if str(comment["user_id"]) != request.user_id:
        raise HTTPException(status_code=403, detail="You are not authorized to edit this comment")

    encrypted_text = encrypt_data(request.text, ENCRYPTION_KEY)
    new_timestamp = datetime.datetime.now(datetime.timezone.utc)

    article_comment_collection.update_one(
        {"_id": ObjectId(request.comment_id)},
        {
            "$set": {
                "text": encrypted_text,
                "is_edited": True,
                "edited_at": new_timestamp
            }
        }
    )

    user_info = users_collection.find_one({"_id": ObjectId(request.user_id)})
    if not user_info:
        raise HTTPException(status_code=404, detail="User not found")

    decrypted_display = decrypt_data(user_info.get("Display", ""), ENCRYPTION_KEY) if user_info.get("Display") else ""

    # Get avatar
    avatar_base64 = ''
    if user_info.get("ProfileImageId"):
        try:
            file_avatar = users_fs.get(ObjectId(user_info["ProfileImageId"]))
            avatar_base64 = base64.b64encode(file_avatar.read()).decode('utf-8')
        except:
            pass

    trimmed_text = (request.text[:500] + '...') if len(request.text) > 500 else request.text
    formatted_message = f"@{user_info['Username']}: {trimmed_text}"
    encrypted_message = encrypt_data(formatted_message, ENCRYPTION_KEY)

    notifications_collection.update_many(
        {"PostId": ObjectId(request.comment_id)},
        {"$set": {"Message": encrypted_message}}
    )

    post_id = str(comment.get("article_id"))

    await manager_article.broadcast(str(post_id), {
        "type": "edit_comment",
        "comment_id": str(request.comment_id),
        "text": request.text,
        "created_at": comment["created_at"].isoformat() + "Z",
        "user_id": str(comment["user_id"]),
        "username": user_info["Username"],
        "display": decrypted_display,
        "avatar": avatar_base64,
        "parent_comment_id": str(comment["parent_comment_id"]) if comment.get("parent_comment_id") else None,
        "CountReplays": comment.get("CountReplays", 0),
        "CountLike": comment.get("CountLike", 0),
        "pinned": comment.get("pinned", False),
        "is_edited": True,
        "edited_at": new_timestamp.isoformat() + "Z"
    })

    return {"success": True}

class TheoryEditCommentRequest(BaseModel):
    user_id: str
    comment_id: str
    text: str

@router.post("/edit-theory-comment")
async def edit_comment(request: TheoryEditCommentRequest):
    if not ObjectId.is_valid(request.user_id) or not ObjectId.is_valid(request.comment_id):
        raise HTTPException(status_code=400, detail="Invalid user_id or comment_id format")

    comment = theories_comment_collection.find_one({"_id": ObjectId(request.comment_id)})

    if not comment:
        raise HTTPException(status_code=404, detail="Comment not found")

    if str(comment["user_id"]) != request.user_id:
        raise HTTPException(status_code=403, detail="You are not authorized to edit this comment")

    encrypted_text = encrypt_data(request.text, ENCRYPTION_KEY)
    new_timestamp = datetime.datetime.now(datetime.timezone.utc)

    # Update comment
    theories_comment_collection.update_one(
        {"_id": ObjectId(request.comment_id)},
        {
            "$set": {
                "text": encrypted_text,
                "is_edited": True,
                "edited_at": new_timestamp
            }
        }
    )

    user_info = users_collection.find_one({"_id": ObjectId(request.user_id)})
    if not user_info:
        raise HTTPException(status_code=404, detail="User not found")

    decrypted_display = decrypt_data(user_info.get("Display", ""), ENCRYPTION_KEY) if user_info.get("Display") else ""

    # 🔧 For notifications: Trim to 500 characters and encrypt
    trimmed_text = (request.text[:500] + '...') if len(request.text) > 500 else request.text
    formatted_message = f"@{user_info['Username']}: {trimmed_text}"
    encrypted_message = encrypt_data(formatted_message, ENCRYPTION_KEY)

    # 🔁 Update all notifications with this comment_id
    notifications_collection.update_many(
        {"PostId": ObjectId(request.comment_id)},
        {"$set": {"Message": encrypted_message}}
    )

    # Determine post ID for broadcast (theory_id)
    post_id = str(comment.get("theory_id"))

    await manager_theory.broadcast(str(post_id), {
        "type": "edit_comment",
        "comment_id": str(request.comment_id),
        "text": request.text,
        "created_at": comment["created_at"].isoformat() + "Z",
        "user_id": str(comment["user_id"]),
        "username": user_info["Username"],
        "display": decrypted_display,
        "parent_comment_id": str(comment["parent_comment_id"]) if comment.get("parent_comment_id") else str(None),
        "CountReplays": comment.get("CountReplays", 0),
        "CountLike": comment.get("CountLike", 0),
        "pinned": comment.get("pinned", False),
        "is_edited": True,  # Add edit indicator
        "edited_at": new_timestamp.isoformat() + "Z"  # Add edit time
    })

    await manager_account.broadcast(str(post_id), {
        "type": "edit_comment",
        "comment_id": str(request.comment_id),
        "text": request.text,
        "created_at": comment["created_at"].isoformat() + "Z",
        "user_id": str(comment["user_id"]),
        "username": user_info["Username"],
        "display": decrypted_display,
        "parent_comment_id": str(comment["parent_comment_id"]) if comment.get("parent_comment_id") else str(None),
        "CountReplays": comment.get("CountReplays", 0),
        "CountLike": comment.get("CountLike", 0),
        "pinned": comment.get("pinned", False),
        "is_edited": True,  # Add edit indicator
        "edited_at": new_timestamp.isoformat() + "Z"  # Add edit time
    })

    return {"success": True}

class ImageEditCommentRequest(BaseModel):
    user_id: str
    comment_id: str
    text: str

@router.post("/edit-image-comment")
async def edit_comment(request: ImageEditCommentRequest):
    if not ObjectId.is_valid(request.user_id) or not ObjectId.is_valid(request.comment_id):
        raise HTTPException(status_code=400, detail="Invalid user_id or comment_id format")

    comment = images_comment_collection.find_one({"_id": ObjectId(request.comment_id)})

    if not comment:
        raise HTTPException(status_code=404, detail="Comment not found")

    if str(comment["user_id"]) != request.user_id:
        raise HTTPException(status_code=403, detail="You are not authorized to edit this comment")

    encrypted_text = encrypt_data(request.text, ENCRYPTION_KEY)
    new_timestamp = datetime.datetime.now(datetime.timezone.utc)

    # Update comment
    images_comment_collection.update_one(
        {"_id": ObjectId(request.comment_id)},
        {
            "$set": {
                "text": encrypted_text,
                "is_edited": True,
                "edited_at": new_timestamp
            }
        }
    )

    user_info = users_collection.find_one({"_id": ObjectId(request.user_id)})
    if not user_info:
        raise HTTPException(status_code=404, detail="User not found")

    decrypted_display = decrypt_data(user_info.get("Display", ""), ENCRYPTION_KEY) if user_info.get("Display") else ""

    # 🔧 For notifications: Trim to 500 characters and encrypt
    trimmed_text = (request.text[:500] + '...') if len(request.text) > 500 else request.text
    formatted_message = f"@{user_info['Username']}: {trimmed_text}"
    encrypted_message = encrypt_data(formatted_message, ENCRYPTION_KEY)

    # 🔁 Update all notifications with this comment_id
    notifications_collection.update_many(
        {"PostId": ObjectId(request.comment_id)},
        {"$set": {"Message": encrypted_message}}
    )

    # Determine post ID for broadcast (image_id)
    post_id = str(comment.get("image_id"))

    await manager_image.broadcast(str(post_id), {
        "type": "edit_comment",
        "comment_id": str(request.comment_id),
        "text": request.text,
        "created_at": comment["created_at"].isoformat() + "Z",
        "user_id": str(comment["user_id"]),
        "username": user_info["Username"],
        "display": decrypted_display,
        "parent_comment_id": str(comment["parent_comment_id"]) if comment.get("parent_comment_id") else str(None),
        "CountReplays": comment.get("CountReplays", 0),
        "CountLike": comment.get("CountLike", 0),
        "pinned": comment.get("pinned", False),
        "is_edited": True,  # Add edit indicator
        "edited_at": new_timestamp.isoformat() + "Z"  # Add edit time
    })

    await manager_account.broadcast(str(post_id), {
        "type": "edit_comment",
        "comment_id": str(request.comment_id),
        "text": request.text,
        "created_at": comment["created_at"].isoformat() + "Z",
        "user_id": str(comment["user_id"]),
        "username": user_info["Username"],
        "display": decrypted_display,
        "parent_comment_id": str(comment["parent_comment_id"]) if comment.get("parent_comment_id") else str(None),
        "CountReplays": comment.get("CountReplays", 0),
        "CountLike": comment.get("CountLike", 0),
        "pinned": comment.get("pinned", False),
        "is_edited": True,  # Add edit indicator
        "edited_at": new_timestamp.isoformat() + "Z"  # Add edit time
    })

    return {"success": True}

class ProductEditCommentRequest(BaseModel):
    user_id: str
    comment_id: str
    text: str

@router.post("/edit-product-comment")
async def edit_comment(request: ProductEditCommentRequest):
    if not ObjectId.is_valid(request.user_id) or not ObjectId.is_valid(request.comment_id):
        raise HTTPException(status_code=400, detail="Invalid user_id or comment_id format")

    # Search in both collections: image and video
    comment = products_comment_collection.find_one({"_id": ObjectId(request.comment_id)})
    db_target = products_comment_collection

    if not comment:
        raise HTTPException(status_code=404, detail="Comment not found")

    if str(comment["user_id"]) != request.user_id:
        raise HTTPException(status_code=403, detail="You are not authorized to edit this comment")

    encrypted_text = encrypt_data(request.text, ENCRYPTION_KEY)
    new_timestamp = datetime.datetime.now(datetime.timezone.utc)

    # Update comment
    db_target.update_one(
        {"_id": ObjectId(request.comment_id)},
        {
            "$set": {
                "text": encrypted_text,
                "is_edited": True,
                "edited_at": new_timestamp
            }
        }
    )

    user_info = users_collection.find_one({"_id": ObjectId(request.user_id)})
    if not user_info:
        raise HTTPException(status_code=404, detail="User not found")

    decrypted_display = decrypt_data(user_info.get("Display", ""), ENCRYPTION_KEY) if user_info.get("Display") else ""

    # Determine post ID for broadcast (product_id)
    product_id = str(comment.get("product_id"))

    await manager_product.broadcast(str(product_id), {
        "type": "edit_comment",
        "comment_id": str(request.comment_id),
        "text": request.text,
        "created_at": comment["created_at"].isoformat() + "Z",
        "user_id": str(comment["user_id"]),
        "username": user_info["Username"],
        "display": decrypted_display,
        "parent_comment_id": str(comment["parent_comment_id"]) if comment.get("parent_comment_id") else str(None),
        "CountReplays": comment.get("CountReplays", 0),
        "CountLike": comment.get("CountLike", 0),
        "pinned": comment.get("pinned", False),
        "is_edited": True,  # Add edit indicator
        "edited_at": new_timestamp.isoformat() + "Z"  # Add edit time
    })

    await manager_account.broadcast(str(product_id), {
        "type": "edit_comment",
        "comment_id": str(request.comment_id),
        "text": request.text,
        "created_at": comment["created_at"].isoformat() + "Z",
        "user_id": str(comment["user_id"]),
        "username": user_info["Username"],
        "display": decrypted_display,
        "parent_comment_id": str(comment["parent_comment_id"]) if comment.get("parent_comment_id") else str(None),
        "CountReplays": comment.get("CountReplays", 0),
        "CountLike": comment.get("CountLike", 0),
        "pinned": comment.get("pinned", False),
        "is_edited": True,  # Add edit indicator
        "edited_at": new_timestamp.isoformat() + "Z"  # Add edit time
    })

    return {"success": True}
