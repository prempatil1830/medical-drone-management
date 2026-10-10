"""
Pydantic v2 schemas for Drone.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


# ── Enum ──────────────────────────────────────────────────────────────────────


class DroneStatus(str, Enum):
    available = "AVAILABLE"
    assigned = "ASSIGNED"
    in_flight = "IN_FLIGHT"
    charging = "CHARGING"
    maintenance = "MAINTENANCE"
    offline = "OFFLINE"

class DroneStatusUpdate(BaseModel):
    status: DroneStatus

# ── Outbound ──────────────────────────────────────────────────────────────────


class DroneResponse(BaseModel):
    id: str
    drone_id: str
    model: str
    battery_pct: float = Field(..., ge=0.0, le=100.0)
    max_payload_kg: float = Field(..., gt=0.0)
    max_range_km: float = Field(..., gt=0.0)
    latitude: float = Field(..., ge=-90.0, le=90.0)
    longitude: float = Field(..., ge=-180.0, le=180.0)
    status: DroneStatus
    zone: str
    updated_at: datetime

    model_config = {"from_attributes": True}
