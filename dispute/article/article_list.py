# backend/dispute/article/article_list.py

from fastapi import APIRouter, Query
import os
from bson import ObjectId
from menu.menu import articles_collection
from typing import List

ENCRYPTION_KEY = os.getenv("ENCRYPTION_KEY")

router = APIRouter()

@router.get("/get-random-articles")
async def get_random_articles(
    limit: int = 20,
    exclude_ids: List[str] = Query(default=[]),
):
    """Get random articles with full article data"""
    try:
        excluded_object_ids = [ObjectId(i) for i in exclude_ids if i]
    except Exception:
        excluded_object_ids = []

    match_criteria = {
        "_id": {"$nin": excluded_object_ids},
        "Banned": {"$ne": True}  # мақолаҳои аккаунтҳои баншуда гирифта намешаванд
    }

    pipeline = [
        {
            "$match": match_criteria
        },
        {
            "$sample": {"size": limit}
        }
    ]

    results = list(articles_collection.aggregate(pipeline))

    articles = []
    for article in results:
        try:
            articles.append({
                "id": str(article["_id"])
            })
        except Exception as e:
            print(f"Error processing article {article.get('_id')}: {e}")
            continue

    return {
        "articles": articles,
    }
