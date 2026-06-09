# backend/main.py

# main
from fastapi import FastAPI, Request
import os

# create post
from account.create.image_uploader import router as image_uploader
from account.create.product_uploader import router as product_uploader
from account.create.shop_uploader import router as shop_uploader
from account.create.theory_uploader import router as theory_uploader
from account.create.video_uploader import router as video_uploader

# account
from account.account import router as account_router
from account.comments_posted import router as comments_posted_router
from account.edit_profile import router as edit_profile_router
from account.liked_stores import router as liked_stores_router
from account.purchased_products import router as purchased_products_router
from account.reaction_to_theories import router as reaction_to_theories_router
from account.saved_liked_articles import router as saved_liked_articles_router
from account.saved_posts import router as saved_posts_router
from account.supported_posts import router as supported_posts_router

# authentication
from authentication.login import router as login_router
from authentication.signup import router as signup_router
from authentication.forgot_password import router as forgot_password_router

# dispute
from dispute.article.article_item import router as article_item
from dispute.article.article_list import router as article_list
from dispute.article.create_article import router as create_article
from dispute.theory.explore_theory import router as explore_theory
from dispute.theory.theory_loader import router as theory_loader

# explore
from explore.comment import router as comment_router
from explore.video_loader import router as video_loader
from explore.image_loader import router as image_loader
from explore.explore_video import router as explore_video
from explore.explore_image import router as explore_image

# home
from home.home import router as home_router
from home.chat import router as router_chat
from home.status import router as status_router
from home.search import router as search_router

# menu
from menu.menu import router as menu_router

# shoping
from shoping.explore_product import router as explore_product
from shoping.shoping_loader import router as shoping_loader
from shoping.product_loader import router as product_loader

# admin
from admin_withdrawal_backend import router as admin_withdrawal

from security.middleware import FrontendOnlyMiddleware
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.responses import Response

app = FastAPI()

app.add_middleware(FrontendOnlyMiddleware)

# -----------------------------------

# Allowed frontend

# -----------------------------------

ALLOWED_ORIGIN = os.getenv("ALLOWED_ORIGIN")

# -----------------------------------

# CORS Security

# -----------------------------------

app.add_middleware(
CORSMiddleware,
allow_origins=[ALLOWED_ORIGIN],
allow_credentials=True,
allow_methods=["GET", "POST", "PUT", "DELETE"],
allow_headers=["Authorization", "Content-Type"],
)

# -----------------------------------

# Trusted Host (protects Host header attacks)

# -----------------------------------

app.add_middleware(
TrustedHostMiddleware,
allowed_hosts=["api.anyvoice.world"])

# -----------------------------------

# Security Headers Middleware

# -----------------------------------

@app.middleware("http")
async def security_headers(request: Request, call_next):
    response: Response = await call_next(request)

    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Strict-Transport-Security"] = "max-age=63072000; includeSubDomains"
    response.headers["Content-Security-Policy"] = "default-src 'self'"

    return response

# -----------------------------------

# Routers

# -----------------------------------

# create post
app.include_router(image_uploader)
app.include_router(product_uploader)
app.include_router(shop_uploader)
app.include_router(theory_uploader)
app.include_router(video_uploader)

# account
app.include_router(account_router)
app.include_router(comments_posted_router)
app.include_router(edit_profile_router)
app.include_router(liked_stores_router)
app.include_router(purchased_products_router)
app.include_router(reaction_to_theories_router)
app.include_router(saved_liked_articles_router)
app.include_router(saved_posts_router)
app.include_router(supported_posts_router)

# authentication
app.include_router(login_router, tags=["Authentication"])
app.include_router(signup_router)
app.include_router(forgot_password_router)

# dispute
app.include_router(article_item)
app.include_router(article_list)
app.include_router(create_article)
app.include_router(explore_theory)
app.include_router(theory_loader)

# explore
app.include_router(comment_router)
app.include_router(video_loader)
app.include_router(image_loader)
app.include_router(explore_video)
app.include_router(explore_image)

# home
app.include_router(home_router)
app.include_router(router_chat)
app.include_router(status_router, prefix="", tags=["status"])
app.include_router(search_router)

# menu
app.include_router(menu_router)

# shoping
app.include_router(explore_product)
app.include_router(shoping_loader)
app.include_router(product_loader)

# admin
app.include_router(admin_withdrawal)
