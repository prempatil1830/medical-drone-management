"""
app/schemas/mission_tracking.py — Pydantic schema for mission tracking updates.
"""

from __future__ import annotations

from datetime import datetime
from pydantic import BaseModel


class MissionTrackingResponse(BaseModel):
    id: str
    mission_id: str
    timestamp: datetime
    lat: float
    lng: float
    battery_pct: float
    remaining_distance_km: float
    eta_minutes: float
    status: str

    model_config = {"from_attributes": True}
