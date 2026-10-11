"""
app/schemas/mission.py — Schemas for missions.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel


class MissionStatus(str, Enum):
    assigned = "ASSIGNED"
    travelling_to_pickup = "TRAVELLING_TO_PICKUP"
    package_collected = "PACKAGE_COLLECTED"
    in_transit = "IN_TRANSIT"
    approaching_destination = "APPROACHING_DESTINATION"
    delivered = "DELIVERED"
    failed = "FAILED"
    cancelled = "CANCELLED"


TERMINAL_MISSION_STATUSES = (
    MissionStatus.delivered.value,
    MissionStatus.failed.value,
    MissionStatus.cancelled.value,
)


class RoutePoint(BaseModel):
    lat: float
    lng: float


class WeatherNote(BaseModel):
    condition: str
    probability: Optional[float] = None
    note: str


class MissionResponse(BaseModel):
    id: str
    mission_id: str
    request_id: str
    drone_id: str
    route: list[RoutePoint]
    distance_km: float
    eta_minutes: float
    battery_required_pct: float
    status: MissionStatus
    started_at: datetime
    failure_reason: Optional[str] = None
    weather: Optional[WeatherNote] = None

    model_config = {"from_attributes": True}
