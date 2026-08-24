"""HTTP routers. Endpoints stay thin: authorise, delegate to a service, serialise."""
from fastapi import APIRouter

from app.api import (
    auth,
    directory,
    imports,
    master_data,
    nlsql,
    organizations,
    suppliers,
)

api_router = APIRouter()
api_router.include_router(auth.router)
api_router.include_router(master_data.router)
api_router.include_router(organizations.router)
api_router.include_router(suppliers.router)
api_router.include_router(directory.router)
api_router.include_router(imports.router)
api_router.include_router(nlsql.router)

__all__ = ["api_router"]
