"""
app/agents/safety_agent.py — Safety Agent for Phase 8.

Responsibilities
----------------
1. Final deterministic gate before mission creation.
2. Re-check the drone against the route and request independently (do not blindly trust upstream agents).
3. Outcomes: PASS, REJECT, REQUEST_REALLOCATION.
4. Log every call to agent_decisions.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from app.core.config import settings
from app.core.logging import get_logger

log = get_logger(__name__)


@dataclass
class SafetyResult:
    decision: str            # "PASS", "REJECT", "REQUEST_REALLOCATION"
    reason: str              # Explanation for the decision
    decision_id: str         # UUID of the agent_decisions document


class SafetyAgent:
    """
    Final deterministic gate for dispatch.
    
    Parameters
    ----------
    decision_repo : AgentDecisionRepository (injectable for testing).
    """

    def __init__(self, decision_repo: Any) -> None:
        self._repo = decision_repo

    async def run(
        self,
        request: dict,
        drone: dict,
        route_result: Any,  # RouteResult
        weather_condition: str,
    ) -> SafetyResult:
        """
        Validate safety constraints before dispatch.
        
        Outcomes:
        - PASS: everything is safe.
        - REJECT: hard failure (e.g. invalid payload size for the request).
        - REQUEST_REALLOCATION: drone changed state (e.g. no longer available, battery dropped).
        """
        decision_id = str(uuid.uuid4())
        now = datetime.now(UTC)
        request_id = str(request.get("request_id", request.get("id", "")))
        drone_id_str = str(drone.get("drone_id", drone.get("id", "?")))
        
        # Snapshot input for audit
        input_snapshot = {
            "request_weight_kg": request.get("weight_kg"),
            "drone_status": drone.get("status"),
            "drone_battery_pct": drone.get("battery_pct"),
            "drone_max_payload_kg": drone.get("max_payload_kg"),
            "drone_max_range_km": drone.get("max_range_km"),
            "route_distance_km": route_result.distance_km,
            "route_battery_required_pct": route_result.battery_required_pct,
            "weather_condition": weather_condition,
        }

        # ── 1. Re-check Drone Availability ────────────────────────────────────
        if drone.get("status") != "AVAILABLE":
            return await self._persist_and_return(
                decision_id=decision_id,
                request_id=request_id,
                decision="REQUEST_REALLOCATION",
                reason=f"Drone {drone_id_str} is no longer AVAILABLE (status: {drone.get('status')}).",
                input_snapshot=input_snapshot,
                timestamp=now,
            )

        # ── 2. Re-check Weather ───────────────────────────────────────────────
        if weather_condition == "UNSAFE":
            return await self._persist_and_return(
                decision_id=decision_id,
                request_id=request_id,
                decision="REJECT",
                reason="Weather is UNSAFE. Cannot proceed with mission.",
                input_snapshot=input_snapshot,
                timestamp=now,
            )

        # ── 3. Check Payload ──────────────────────────────────────────────────
        try:
            req_weight = float(request["weight_kg"])
            drone_max_payload = float(drone["max_payload_kg"])
        except (KeyError, ValueError, TypeError) as exc:
            return await self._persist_and_return(
                decision_id=decision_id,
                request_id=request_id,
                decision="REJECT",
                reason=f"Missing or invalid payload data: {exc}",
                input_snapshot=input_snapshot,
                timestamp=now,
            )

        if req_weight > drone_max_payload:
            return await self._persist_and_return(
                decision_id=decision_id,
                request_id=request_id,
                decision="REJECT",
                reason=f"Request weight ({req_weight}kg) exceeds drone capacity ({drone_max_payload}kg).",
                input_snapshot=input_snapshot,
                timestamp=now,
            )

        # ── 4. Check Range ────────────────────────────────────────────────────
        try:
            route_dist = float(route_result.distance_km)
            drone_max_range = float(drone["max_range_km"])
        except (KeyError, ValueError, TypeError) as exc:
            return await self._persist_and_return(
                decision_id=decision_id,
                request_id=request_id,
                decision="REJECT",
                reason=f"Missing or invalid range data: {exc}",
                input_snapshot=input_snapshot,
                timestamp=now,
            )

        if route_dist > drone_max_range:
            return await self._persist_and_return(
                decision_id=decision_id,
                request_id=request_id,
                decision="REQUEST_REALLOCATION",
                reason=f"Route distance ({route_dist:.2f}km) exceeds drone max range ({drone_max_range:.2f}km).",
                input_snapshot=input_snapshot,
                timestamp=now,
            )

        # ── 5. Check Battery vs Route Requirement ─────────────────────────────
        try:
            drone_battery = float(drone["battery_pct"])
            route_battery = float(route_result.battery_required_pct)
        except (KeyError, ValueError, TypeError) as exc:
            return await self._persist_and_return(
                decision_id=decision_id,
                request_id=request_id,
                decision="REJECT",
                reason=f"Missing or invalid battery data: {exc}",
                input_snapshot=input_snapshot,
                timestamp=now,
            )

        min_reserve = settings.ALLOCATION_MIN_BATTERY_RESERVE_PCT
        available_battery = drone_battery - min_reserve

        if route_battery > available_battery:
            return await self._persist_and_return(
                decision_id=decision_id,
                request_id=request_id,
                decision="REQUEST_REALLOCATION",
                reason=(
                    f"Insufficient battery for route. Drone has {drone_battery:.1f}% "
                    f"(available {available_battery:.1f}% after {min_reserve}% reserve). "
                    f"Route requires {route_battery:.1f}%."
                ),
                input_snapshot=input_snapshot,
                timestamp=now,
            )

        # ── 6. All Checks Passed ──────────────────────────────────────────────
        return await self._persist_and_return(
            decision_id=decision_id,
            request_id=request_id,
            decision="PASS",
            reason="All safety checks passed.",
            input_snapshot=input_snapshot,
            timestamp=now,
        )

    # ── Private helpers ───────────────────────────────────────────────────────

    async def _persist_and_return(
        self,
        *,
        decision_id: str,
        request_id: str,
        decision: str,
        reason: str,
        input_snapshot: dict,
        timestamp: datetime,
    ) -> SafetyResult:
        """Persist the decision and return the dataclass."""
        try:
            await self._repo.create({
                "decision_id": decision_id,
                "agent_name": "SafetyAgent",
                "request_id": request_id,
                "decision": decision,
                "score": None,
                "reason": reason,
                "input_snapshot": input_snapshot,
                "timestamp": timestamp,
            })
        except Exception as exc:
            log.error(
                "safety_agent_persist_error",
                decision_id=decision_id,
                error=str(exc),
            )

        log.info(
            "safety_agent_decision",
            request_id=request_id,
            decision=decision,
            reason=reason,
        )

        return SafetyResult(
            decision=decision,
            reason=reason,
            decision_id=decision_id,
        )
