"""
app/schemas/dashboard.py — Response schema for the dashboard analytics.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class DashboardStatsResponse(BaseModel):
    delivered: int = Field(..., description="Count of delivered missions")
    failed: int = Field(..., description="Count of failed missions")
    active: int = Field(..., description="Count of active (in-progress/assigned) missions")
    average_eta: float = Field(..., description="Average ETA in minutes for missions")
    drone_utilization: float = Field(..., description="Percentage of fleet drones not in AVAILABLE state")
    average_response_time: float = Field(
        ...,
        description="Average response time in seconds (request created_at to mission started_at) for Critical and High requests",
    )
