"""Auth request/response models."""
from __future__ import annotations

import uuid

from pydantic import BaseModel, EmailStr, Field

from app.enums import Role


class PasswordLoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=200)


class OtpRequestBody(BaseModel):
    """Phone-first: suppliers log in with the number they already gave us."""

    phone: str | None = Field(None, max_length=30)
    email: EmailStr | None = None


class OtpVerifyBody(BaseModel):
    phone: str | None = Field(None, max_length=30)
    email: EmailStr | None = None
    code: str = Field(min_length=4, max_length=10)


class SessionResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in_hours: int


class CurrentUser(BaseModel):
    id: uuid.UUID
    name: str
    email: str | None
    phone: str | None
    role: Role
    side: str
    org_id: uuid.UUID | None
    org_name: str | None
    org_status: str | None
    language_pref: str
    # Portals the client should render. Sent by the server so the frontend never has to infer
    # authorisation from the role string.
    portals: list[str]


class AcceptInviteBody(BaseModel):
    token: str
    name: str = Field(min_length=2, max_length=160)
    password: str | None = Field(None, min_length=8, max_length=200)
    phone: str | None = Field(None, max_length=30)
    language_pref: str = "en"
