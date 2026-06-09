# backend/account/saved_liked_articles.py

from fastapi import HTTPException, Query, APIRouter
from bson import ObjectId
from typing import List
from menu.menu import article_likes_collection, article_saves_collection, articles_collection

router = APIRouter()

@router.get("/get-user-liked-articles")
async def get_user_liked_articles(
    user_id: str = Query(..., description="ID of the user whose liked articles are requested"),
    requester_id: str = Query(None, description="ID of the authenticated user making the request"),
    limit: int = Query(20, description="Number of articles to return"),
    exclude_ids: List[str] = Query(default=[], description="List of article IDs to exclude")
):
    if not ObjectId.is_valid(user_id):
        raise HTTPException(status_code=400, detail="Invalid user_id")
    if requester_id and not ObjectId.is_valid(requester_id):
        raise HTTPException(status_code=400, detail="Invalid requester_id")

    try:
        excluded_object_ids = [ObjectId(i) for i in exclude_ids if ObjectId.is_valid(i)]
    except Exception:
        excluded_object_ids = []

    liked_articles = list(
        article_likes_collection.find({"user_id": ObjectId(user_id)})
        .sort("liked_at", -1)
        .skip(len(excluded_object_ids))
        .limit(limit)
    )

    filtered_article_ids = []
    for item in liked_articles:
        article_id = item.get("article_id")
        if article_id and ObjectId.is_valid(article_id) and article_id not in excluded_object_ids:
            filtered_article_ids.append(article_id)
        if len(filtered_article_ids) >= limit:
            break

    if not filtered_article_ids:
        return {"articles": []}

    articles = list(articles_collection.find({"_id": {"$in": filtered_article_ids}}))

    article_map = {art["_id"]: art for art in articles}
    sorted_results = []
    for article_id in filtered_article_ids:
        article = article_map.get(article_id)
        if article:
            sorted_results.append({"id": str(article["_id"])})

    return {"articles": sorted_results}

@router.get("/get-user-saved-articles")
async def get_user_saved_articles(
    user_id: str = Query(..., description="ID of the user whose saved articles are requested"),
    requester_id: str = Query(None, description="ID of the authenticated user making the request"),
    limit: int = Query(20, description="Number of articles to return"),
    exclude_ids: List[str] = Query(default=[], description="List of article IDs to exclude")
):
    if not ObjectId.is_valid(user_id):
        raise HTTPException(status_code=400, detail="Invalid user_id")
    if requester_id and not ObjectId.is_valid(requester_id):
        raise HTTPException(status_code=400, detail="Invalid requester_id")

    try:
        excluded_object_ids = [ObjectId(i) for i in exclude_ids if ObjectId.is_valid(i)]
    except Exception:
        excluded_object_ids = []

    saved_articles = list(
        article_saves_collection.find({"user_id": ObjectId(user_id)})
        .sort("saved_at", -1)
        .skip(len(excluded_object_ids))
        .limit(limit)
    )

    filtered_article_ids = []
    for item in saved_articles:
        article_id = item.get("article_id")
        if article_id and ObjectId.is_valid(article_id) and article_id not in excluded_object_ids:
            filtered_article_ids.append(article_id)
        if len(filtered_article_ids) >= limit:
            break

    if not filtered_article_ids:
        return {"articles": []}

    articles = list(articles_collection.find({"_id": {"$in": filtered_article_ids}}))

    article_map = {art["_id"]: art for art in articles}
    sorted_results = []
    for article_id in filtered_article_ids:
        article = article_map.get(article_id)
        if article:
            sorted_results.append({"id": str(article["_id"])})

    return {"articles": sorted_results}
