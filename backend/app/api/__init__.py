from fastapi import APIRouter

from app.api import auth, companies, dashboard, deals, documents, taxonomy

api_router = APIRouter()
for module in (auth, taxonomy, companies, deals, documents, dashboard):
    api_router.include_router(module.router)

__all__ = ["api_router"]
