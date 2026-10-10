"""
app/schemas/weather.py — Pydantic v2 schemas for the weather prediction endpoint.
"""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field


# ── Inbound ───────────────────────────────────────────────────────────────────


class WeatherPredictRequest(BaseModel):
    """Body for POST /api/weather/predict."""

    lat: float = Field(..., ge=-90.0, le=90.0, description="Latitude")
    lng: float = Field(..., ge=-180.0, le=180.0, description="Longitude")


# ── Outbound ──────────────────────────────────────────────────────────────────


class WeatherPredictResponse(BaseModel):
    """
    Response from POST /api/weather/predict.

    flight_condition is "UNSAFE" and reason is populated when the weather
    API was unavailable or the feature mapping failed (fail-closed).
    """

    observation_id: str = Field(..., description="UUID of the persisted observation")
    flight_condition: str = Field(
        ..., description="SAFE | CAUTION | UNSAFE"
    )
    probability: float = Field(
        ..., ge=0.0, le=1.0, description="Model confidence (0.0 on failure)"
    )
    raw_weather_snapshot: Optional[dict[str, Any]] = Field(
        None, description="Raw OWM API payload; null when API call failed"
    )
    reason: Optional[str] = Field(
        None, description="Populated only on failure — explains why UNSAFE was returned"
    )
