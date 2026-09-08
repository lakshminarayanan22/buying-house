"""Placeholder app. The HTTP layer is rebuilt against the new schema next."""
from fastapi import FastAPI

from app.config import settings

app = FastAPI(title="Ecolink", version="0.2.0")


@app.get("/health", tags=["ops"])
def health() -> dict:
    return {"status": "ok", "environment": settings.environment}
