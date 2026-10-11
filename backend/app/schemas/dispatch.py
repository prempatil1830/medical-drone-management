"""
app/schemas/dispatch.py — Response schema for the dispatch endpoint (Phase 7).

POST /api/requests/{id}/dispatch returns a DispatchResponse combining the
outputs of all three agents: Priority Agent, Weather Agent, Allocation Agent.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class DispatchResponse(BaseModel):
    """Combined decision trail from the full dispatch pipeline."""

    request_id: str
    """The MongoDB document ID of the dispatched medical request."""

    # ── Priority Agent output ─────────────────────────────────────────────────
    priority_decision: str
    """Priority tier: Critical | High | Medium | Normal."""

    priority_score: Optional[float] = None
    """Priority score [0.25 - 1.00] from Priority Agent."""

    priority_reason: str
    """Human-readable explanation of the priority classification."""

    priority_decision_id: str
    """ID of the agent_decisions document for the priority call."""

    # ── Weather Agent output ──────────────────────────────────────────────────
    weather_condition: str
    """SAFE | CAUTION | UNSAFE — from the ML flight-condition model."""

    weather_observation_id: str
    """ID of the weather_observations document for audit."""

    weather_halted: bool
    """
    True if the pipeline was stopped because weather is UNSAFE.
    When True, allocated_drone_id is always None.
    """

    # ── Allocation Agent output ───────────────────────────────────────────────
    allocated_drone_id: Optional[str] = None
    """drone_id of the selected drone, or None if halted/no feasible drone."""

    allocation_score: Optional[float] = None
    """Weighted allocation score [0,1], or None if no drone allocated."""

    allocation_reason: str
    """
    Human-readable reason for the allocation decision.
    Includes why the pipeline was halted if weather_halted=True.
    """

    allocation_decision_id: Optional[str] = None
    """ID of the agent_decisions document for the allocation call, or None if halted."""

    # ── Route Agent output (Phase 8) ──────────────────────────────────────────
    route_distance_km: Optional[float] = None
    """Computed distance of the route, or None if halted before routing."""

    route_eta_minutes: Optional[float] = None
    """Estimated time of arrival, or None if halted before routing."""

    route_battery_required_pct: Optional[float] = None
    """Estimated battery required, or None if halted before routing."""

    # ── Safety Agent output (Phase 8) ─────────────────────────────────────────
    safety_decision: Optional[str] = None
    """PASS | REJECT | REQUEST_REALLOCATION, or None if halted before safety check."""

    safety_reason: Optional[str] = None
    """Reason for the safety decision, or None if halted before safety check."""

    safety_decision_id: Optional[str] = None
    """ID of the agent_decisions document for the safety call, or None if halted."""

    # ── Mission output (Phase 8) ──────────────────────────────────────────────
    mission_id: Optional[str] = None
    """ID of the created mission, or None if halted/rejected."""


class AgentDecisionItem(BaseModel):
    agent_name: str
    decision: str
    score: Optional[float] = None
    reason: Optional[str] = None
    timestamp: datetime


class DispatchSummaryResponse(BaseModel):
    text: str
    source: str
    generated_at: datetime
