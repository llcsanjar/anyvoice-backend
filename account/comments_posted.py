# backend/account/comments_posted.py

from fastapi import APIRouter, HTTPException, Query
from bson import ObjectId
from menu.menu import users_collection, images_comment_collection, article_comment_collection, videos_comment_collection, \
products_comment_collection, theories_comment_collection
from menu.menu import decrypt_data
import datetime
import os

router = APIRouter()

ENCRYPTION_KEY = os.getenv("ENCRYPTION_KEY")

@router.get("/get-user-comments")
def get_user_comments(
    user_id: str = Query(..., description="ID of the user whose comments are requested"),
    page: int = Query(1, ge=1, description="Page number, starting from 1"),
    limit: int = Query(10, ge=1, le=100, description="Number of comments per page"),
):
    if not ObjectId.is_valid(user_id):
        raise HTTPException(status_code=400, detail="Invalid user ID format")

    user = users_collection.find_one({"_id": ObjectId(user_id)})
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    skip = (page - 1) * limit

    # Get comments from all databases
    image_comments = list(images_comment_collection.find({"user_id": ObjectId(user_id)}))
    article_comments = list(article_comment_collection.find({"user_id": ObjectId(user_id)}))
    video_comments = list(videos_comment_collection.find({"user_id": ObjectId(user_id)}))
    product_comments = list(products_comment_collection.find({"user_id": ObjectId(user_id)}))
    theory_comments = list(theories_comment_collection.find({"user_id": ObjectId(user_id)}))

    all_comments = image_comments + article_comments + video_comments + product_comments + theory_comments
    all_comments.sort(key=lambda c: c.get("created_at", datetime.datetime.min), reverse=True)

    total_count = len(all_comments)
    paged_comments = all_comments[skip:skip + limit]

    result = []
    for comment in paged_comments:
        user_info = users_collection.find_one({"_id": comment["user_id"]})
        if not user_info:
            continue

        decrypted_display = decrypt_data(user_info.get("Display", ""), ENCRYPTION_KEY) if user_info.get("Display") else ""
        decrypted_text = decrypt_data(comment["text"], ENCRYPTION_KEY)

        post_type = None
        if "video_id" in comment:
            post_type = 'video'
            post_id = str(comment.get("video_id"))

        elif "image_id" in comment:
            post_type = 'image'
            post_id = str(comment.get("image_id"))

        elif "article_id" in comment:
            post_type = 'article'
            post_id = str(comment.get("article_id"))

        elif "product_id" in comment:
            post_type = 'product'
            post_id = str(comment.get("product_id"))

        elif "theory_id" in comment:
            post_type = 'theory'
            post_id = str(comment.get("theory_id"))

        parent_comment_id = comment.get("parent_comment_id")
        parent_username = None

        if parent_comment_id:
            if post_type == 'video':
                parent_comment = videos_comment_collection.find_one({"_id": ObjectId(parent_comment_id)})

            elif post_type == 'image':
                parent_comment = images_comment_collection.find_one({"_id": ObjectId(parent_comment_id)})

            elif post_type == 'article':
                parent_comment = article_comment_collection.find_one({"_id": ObjectId(parent_comment_id)})

            elif post_type == 'product':
                parent_comment = products_comment_collection.find_one({"_id": ObjectId(parent_comment_id)})

            elif post_type == 'theory':
                parent_comment = theories_comment_collection.find_one({"_id": ObjectId(parent_comment_id)})

            if parent_comment:
                parent_user = users_collection.find_one({"_id": parent_comment["user_id"]})
                if parent_user:
                    parent_username = parent_user.get("Username")

        result.append({
            "id": str(comment["_id"]),
            "text": decrypted_text,
            "created_at": comment["created_at"].isoformat() + "Z",
            "user_id": str(comment["user_id"]),
            "username": user_info["Username"],
            "display": decrypted_display,
            "post_type": post_type,
            "post_id": post_id,
            "parent_comment_id": str(comment.get("parent_comment_id")) if comment.get("parent_comment_id") else None,
            "CountReplays": comment.get("CountReplays", 0),
            "CountLike": comment.get("CountLike", 0),
            "pinned": comment.get("pinned", False),
            "is_edited": comment.get("is_edited", False),
            "edited_at": comment["edited_at"].isoformat() + "Z" if comment.get("edited_at") else None,
            "parent_username": parent_username,
        })

    has_more = skip + len(result) < total_count

    return {
        "comments": result,
        "total_count": total_count,
        "has_more": has_more,
        "page": page,
        "limit": limit
    }
