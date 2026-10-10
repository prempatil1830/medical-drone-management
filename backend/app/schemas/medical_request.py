"""
Pydantic v2 schemas for MedicalRequest.

Separation of concerns
-----------------------
MedicalRequestCreate  — inbound payload (center_id as str, validated at API layer)
MedicalRequestResponse — outbound response (id as str, no internal details)
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


# ── Enums ─────────────────────────────────────────────────────────────────────


class Urgency(str, Enum):
    low = "LOW"
    medium = "MEDIUM"
    high = "HIGH"
    critical = "CRITICAL"


class RequestStatus(str, Enum):
    pending = "PENDING"
    assigned = "ASSIGNED"
    in_transit = "IN_TRANSIT"
    delivered = "DELIVERED"
    cancelled = "CANCELLED"


class MedicalType(str, Enum):
    BLOOD = "Blood"
    ORGANS = "Organs"
    VACCINES = "Vaccines"
    EMERGENCY_MEDICINE = "Emergency Medicine"
    PLASMA = "Plasma"
    INSULIN = "Insulin"
    OTHER = "Other"


# ── Nested coordinate schema ──────────────────────────────────────────────────


class Coordinates(BaseModel):
    lat: float = Field(..., ge=-90.0, le=90.0)
    lng: float = Field(..., ge=-180.0, le=180.0)


# ── Inbound ───────────────────────────────────────────────────────────────────


class MedicalRequestCreate(BaseModel):
    center_id: str = Field(..., description="ID of the originating medical center")
    medical_type: MedicalType = Field(..., description="Type of medical supply")
    quantity: int = Field(..., gt=0, description="Number of units — must be at least 1")
    weight_kg: float = Field(..., gt=0.0, description="Total payload weight in kg — must be > 0")
    urgency: Urgency = Urgency.medium
    pickup: Coordinates
    destination: Coordinates


# ── Outbound ──────────────────────────────────────────────────────────────────


class MedicalRequestResponse(BaseModel):
    id: str
    request_id: str
    center_id: str
    medical_type: MedicalType
    quantity: int
    weight_kg: float
    urgency: Urgency
    pickup: Coordinates
    destination: Coordinates
    status: RequestStatus
    mission_id: Optional[str] = None
    priority_tier: Optional[str] = None
    priority_score: Optional[float] = None
    assigned_drone_id: Optional[str] = None
    created_at: datetime

    model_config = {"from_attributes": True}
