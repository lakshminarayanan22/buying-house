"""Ecolink — sourcing and deal tracking.

One internal application. Everyone who signs in works here, which is why there is no tenancy
layer, no portal split and no identity gating anywhere in this codebase.
"""
import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import api_router
from app.config import settings

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

# Fail at boot, not at the first sign-in, if the sign-in setup would let the wrong people in.
settings.check_sign_in_config()

app = FastAPI(
    title="Ecolink",
    version="0.2.0",
    description="Companies, deals and commission tracking for Ecolink.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.app_base_url],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router, prefix="/api")


@app.get("/health", tags=["ops"])
def health() -> dict:
    return {"status": "ok", "environment": settings.environment}
