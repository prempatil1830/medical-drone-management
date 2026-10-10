"""
Pydantic v2 schemas for MedicalCenter.
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class MedicalCenterBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    type: str = Field(..., description="E.g. 'hospital', 'clinic', 'pharmacy'")
    address: str = Field(..., min_length=1, max_length=500)
    latitude: float = Field(..., ge=-90.0, le=90.0)
    longitude: float = Field(..., ge=-180.0, le=180.0)
    contact: str = Field(..., description="Phone number or email contact")


# ── Inbound ───────────────────────────────────────────────────────────────────


class MedicalCenterCreate(MedicalCenterBase):
    """Payload for creating a new medical center."""
    pass


class MedicalCenterUpdate(BaseModel):
    """All fields optional for PATCH-style partial updates."""

    name: Optional[str] = Field(None, min_length=1, max_length=200)
    type: Optional[str] = None
    address: Optional[str] = Field(None, min_length=1, max_length=500)
    latitude: Optional[float] = Field(None, ge=-90.0, le=90.0)
    longitude: Optional[float] = Field(None, ge=-180.0, le=180.0)
    contact: Optional[str] = None


# ── Outbound ──────────────────────────────────────────────────────────────────


class MedicalCenterResponse(MedicalCenterBase):
    id: str

    model_config = {"from_attributes": True}
