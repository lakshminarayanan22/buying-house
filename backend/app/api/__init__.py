from fastapi import APIRouter

from app.api import auth, chat, companies, dashboard, deals, documents, taxonomy, users

api_router = APIRouter()
for module in (auth, users, taxonomy, companies, deals, documents, dashboard, chat):
    api_router.include_router(module.router)

__all__ = ["api_router"]
