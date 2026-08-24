"""FastAPI application.

One app serves all three portals; the frontend routes under /internal, /brand and /supplier,
and every endpoint authorises through app.rbac rather than trusting the path it was reached by.
"""
import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import api_router
from app.auth.deps import access_denied_handler
from app.config import settings
from app.rbac.policy import AccessDenied

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

app = FastAPI(
    title="Buying House Platform",
    version="0.1.0",
    description=(
        "Two-sided platform connecting brands and suppliers, with an internal merchandising "
        "console. Brand and supplier identities are separated by an explicit reveal."
    ),
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.app_base_url],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.add_exception_handler(AccessDenied, access_denied_handler)
app.include_router(api_router, prefix="/api")


@app.get("/health", tags=["ops"])
def health() -> dict:
    return {"status": "ok", "environment": settings.environment}
