"""
Pydantic v2 schemas for User.

Separation of concerns
-----------------------
UserCreate   — inbound registration payload (has plain password)
UserInDB     — internal representation that includes password_hash (never sent out)
UserResponse — outbound representation (no password_hash, id as str)
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, EmailStr, Field


class UserRole(str, Enum):
    hospital = "hospital"
    operator = "operator"
    admin = "admin"


# ── Shared base ───────────────────────────────────────────────────────────────


class UserBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    email: EmailStr
    role: UserRole = UserRole.hospital
    center_id: Optional[str] = None


# ── Inbound: registration request ────────────────────────────────────────────


class UserCreate(BaseModel):
    """Registration payload — center_id is removed; public registration assigns center_id=None."""
    name: str = Field(..., min_length=1, max_length=100)
    email: EmailStr
    password: str = Field(..., min_length=8, max_length=128)

    model_config = {"extra": "ignore"}


class UpdateUserCenterRequest(BaseModel):
    center_id: str = Field(..., min_length=1, description="Medical center ID to assign to the user")


# ── Internal DB model (for use inside repositories only) ─────────────────────


class UserInDB(UserBase):
    """Full DB document model — includes hashed password.  Never serialise to client."""

    id: Optional[str] = None
    password_hash: str
    created_at: Optional[datetime] = None


# ── Outbound: response ────────────────────────────────────────────────────────


class UserResponse(UserBase):
    """Safe outbound representation — password_hash is intentionally absent."""

    id: str
    created_at: datetime

    model_config = {"from_attributes": True}


# ── Auth payloads ─────────────────────────────────────────────────────────────


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserResponse
