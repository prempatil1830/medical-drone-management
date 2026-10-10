"""
app/agents/allocation_agent.py — Drone Allocation Agent for Phase 7.

Responsibilities
----------------
1. Receive a medical request document, the priority decision, and a list of
   candidate drone documents from the drones collection.
2. Pre-filter candidates against hard constraints (all must pass).
3. Score all feasible candidates using the weighted formula from the spec.
4. Select the highest-scoring drone.
5. Persist a decision document to agent_decisions for EVERY call.
6. Return an AllocationResult dataclass.

Scoring Formula (spec §7.2)
---------------------------
    allocation_score = 0.30 * battery_score
                     + 0.25 * distance_score
                     + 0.20 * payload_score
                     + 0.15 * availability_score
                     + 0.10 * priority_compatibility

Component definitions
~~~~~~~~~~~~~~~~~~~~~
    battery_score         = battery_pct / 100
                            (1.0 at full charge, 0.0 at empty)

    distance_score        = 1 - (drone_to_pickup_km / max_range_km)
                            clamped to [0.0, 1.0]
                            (1.0 when drone is co-located with pickup,
                             0.0 when approach distance equals max range;
                             normalization via max_range_km is configurable per drone)

    payload_score         = 1 - (weight_kg / max_payload_kg)
                            clamped to [0.0, 1.0]
                            (1.0 when very light payload, 0.0 at capacity)

    availability_score    = 1.0 always (pre-filter guarantees status=AVAILABLE)

    priority_compatibility = lookup by priority tier:
                             Critical → 1.00
                             High     → 0.75
                             Medium   → 0.50
                             Normal   → 0.25

Hard pre-filter constraints (all must pass; failing any → drone excluded)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
    1. status == "AVAILABLE"
    2. max_payload_kg >= weight_kg
    3. max_range_km  >= total_flight_km * ALLOCATION_SAFETY_FACTOR
       (total_flight_km = approach_km + mission_distance_km;
        drones do NOT return to base)
    4. battery_pct   >= ALLOCATION_MIN_BATTERY_RESERVE_PCT
    5. battery_pct - total_flight_km * BATTERY_CONSUMPTION_PER_KM >= MIN_RESERVE

Distance calculation
~~~~~~~~~~~~~~~~~~~~
    approach_km:         Haversine from (drone.lat, drone.lng) to (pickup.lat, pickup.lng).
    mission_distance_km: Haversine from (pickup.lat, pickup.lng) to (dest.lat, dest.lng).
    total_flight_km    = approach_km + mission_distance_km.
    Drones do NOT return to base after delivery.
    No external routing API is required for allocation scoring.

Failure semantics
-----------------
The agent never raises. If zero drones pass filtering, it returns
AllocationResult with drone_id=None and reason="NO_FEASIBLE_DRONE".
All outcomes (including failures) are persisted to agent_decisions.
"""

from __future__ import annotations

import math
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Optional

from app.core.config import settings
from app.core.logging import get_logger

log = get_logger(__name__)

# ── Priority compatibility lookup ─────────────────────────────────────────────

_PRIORITY_COMPAT: dict[str, float] = {
    "Critical": 1.00,
    "High":     0.75,
    "Medium":   0.50,
    "Normal":   0.25,
}

# ── Scoring weights (must sum to 1.0) ─────────────────────────────────────────

_W_BATTERY      = 0.30
_W_DISTANCE     = 0.25
_W_PAYLOAD      = 0.20
_W_AVAILABILITY = 0.15
_W_PRIORITY     = 0.10


# ── Haversine distance ────────────────────────────────────────────────────────

def _haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Return great-circle distance in kilometres between two (lat, lng) points."""
    R = 6371.0  # Earth radius in km
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lng2 - lng1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


# ── Per-drone score calculation ───────────────────────────────────────────────

def _compute_score(
    drone: dict,
    drone_to_pickup_km: float,
    weight_kg: float,
    priority: str,
) -> float:
    """Compute the allocation score for a single (pre-filtered) candidate drone."""
    battery_score = drone["battery_pct"] / 100.0

    # Closer drone → higher score.  Normalization uses drone's own max_range.
    normalization_km = drone["max_range_km"]
    raw_distance_score = 1.0 - (drone_to_pickup_km / normalization_km)
    distance_score = max(0.0, min(1.0, raw_distance_score))

    raw_payload_score = 1.0 - (weight_kg / drone["max_payload_kg"])
    payload_score = max(0.0, min(1.0, raw_payload_score))

    availability_score = 1.0  # guaranteed AVAILABLE by pre-filter

    priority_compat = _PRIORITY_COMPAT.get(priority, 0.25)

    return (
        _W_BATTERY      * battery_score
        + _W_DISTANCE     * distance_score
        + _W_PAYLOAD      * payload_score
        + _W_AVAILABILITY * availability_score
        + _W_PRIORITY     * priority_compat
    )


# ── Result dataclass ──────────────────────────────────────────────────────────

@dataclass
class AllocationResult:
    drone_id: Optional[str]          # None if no feasible drone found
    score: Optional[float]           # Allocation score [0,1], None if no drone
    reason: str                      # Human-readable explanation
    decision_id: str                 # UUID of the agent_decisions document
    filtered_count: int = 0          # Number of drones that passed pre-filter
    candidate_count: int = 0         # Total drones examined before filtering
    score_breakdown: dict = field(default_factory=dict)  # Sub-scores for winner


# ── Agent ─────────────────────────────────────────────────────────────────────

class AllocationAgent:
    """
    Drone allocation agent — filters, scores, and selects the best drone.

    Parameters
    ----------
    decision_repo : AgentDecisionRepository (injectable for testing).
    """

    def __init__(self, decision_repo: Any) -> None:
        self._repo = decision_repo

    async def run(
        self,
        request: dict,
        priority: str,
        drones: list[dict],
    ) -> AllocationResult:
        """
        Select the best available drone for a medical delivery request.

        Parameters
        ----------
        request  : raw MongoDB document from medical_requests.
        priority : string tier from PriorityAgent ("Critical"|"High"|…).
        drones   : list of drone documents from DroneRepository.

        Returns
        -------
        AllocationResult — never raises.
        """
        decision_id = str(uuid.uuid4())
        now = datetime.now(UTC)
        request_id = str(request.get("request_id", request.get("id", "")))

        # ── Extract mission parameters ────────────────────────────────────────
        try:
            pickup = request["pickup"]
            destination = request["destination"]
            weight_kg: float = float(request["weight_kg"])

            pickup_lat = float(pickup["lat"])
            pickup_lng = float(pickup["lng"])
            dest_lat   = float(destination["lat"])
            dest_lng   = float(destination["lng"])
        except (KeyError, TypeError, ValueError) as exc:
            reason = f"Failed to extract mission parameters from request: {exc}"
            log.error("allocation_agent_input_error", request_id=request_id, error=str(exc))
            return await self._persist_and_return(
                decision_id=decision_id,
                request_id=request_id,
                drone_id=None,
                score=None,
                reason=reason,
                input_snapshot={"error": str(exc)},
                timestamp=now,
                filtered_count=0,
                candidate_count=len(drones),
            )

        mission_distance_km = _haversine_km(pickup_lat, pickup_lng, dest_lat, dest_lng)

        safety_factor      = settings.ALLOCATION_SAFETY_FACTOR
        min_battery_pct    = settings.ALLOCATION_MIN_BATTERY_RESERVE_PCT
        battery_pct_per_km = settings.ROUTE_BATTERY_CONSUMPTION_PER_KM

        log.info(
            "allocation_agent_started",
            request_id=request_id,
            mission_distance_km=round(mission_distance_km, 2),
            weight_kg=weight_kg,
            total_drones=len(drones),
        )

        # ── Pre-filter ────────────────────────────────────────────────────────
        feasible: list[tuple[dict, float]] = []  # (drone, approach_km)
        filter_rejections: list[str] = []

        for drone in drones:
            drone_id_str = drone.get("drone_id", drone.get("id", "?"))
            reasons: list[str] = []

            if drone.get("status") != "AVAILABLE":
                reasons.append(f"status={drone.get('status')!r} (need AVAILABLE)")
            if drone.get("max_payload_kg", 0) < weight_kg:
                reasons.append(
                    f"payload_capacity={drone.get('max_payload_kg')}kg < {weight_kg}kg"
                )

            # ── Per-drone approach leg and total flight distance ───────────
            if "latitude" not in drone or "longitude" not in drone:
                reasons.append("missing coordinates")
                drone_lat, drone_lng = 0.0, 0.0
            else:
                try:
                    drone_lat = float(drone["latitude"])
                    drone_lng = float(drone["longitude"])
                except (ValueError, TypeError):
                    reasons.append("invalid coordinates")
                    drone_lat, drone_lng = 0.0, 0.0
            approach_km = _haversine_km(drone_lat, drone_lng, pickup_lat, pickup_lng)
            total_flight_km = approach_km + mission_distance_km

            required_range_km = total_flight_km * safety_factor
            if drone.get("max_range_km", 0) < required_range_km:
                reasons.append(
                    f"max_range={drone.get('max_range_km')}km < required "
                    f"{required_range_km:.2f}km (total_flight={total_flight_km:.2f}km"
                    f" [approach={approach_km:.2f}+mission={mission_distance_km:.2f}]×{safety_factor})"
                )

            if drone.get("battery_pct", 0) < min_battery_pct:
                reasons.append(
                    f"battery={drone.get('battery_pct')}% < {min_battery_pct}% reserve"
                )

            # Check battery can cover total flight plus reserve
            battery_after_flight = drone.get("battery_pct", 0) - (
                total_flight_km * battery_pct_per_km
            )
            if battery_after_flight < min_battery_pct:
                reasons.append(
                    f"battery_after_flight={battery_after_flight:.1f}% "
                    f"< {min_battery_pct}% reserve "
                    f"(flight needs {total_flight_km * battery_pct_per_km:.1f}% "
                    f"for {total_flight_km:.2f}km)"
                )

            if reasons:
                filter_rejections.append(f"{drone_id_str}: {'; '.join(reasons)}")
            else:
                feasible.append((drone, approach_km))

        if filter_rejections:
            log.info(
                "allocation_agent_filtered_out",
                request_id=request_id,
                rejections=filter_rejections,
            )

        # ── No feasible drone ─────────────────────────────────────────────────
        if not feasible:
            reason = (
                f"NO_FEASIBLE_DRONE — all {len(drones)} drones failed pre-filter. "
                f"Rejections: {'; '.join(filter_rejections) or 'none (empty fleet)'}"
            )
            log.warning("allocation_agent_no_feasible_drone", request_id=request_id)
            return await self._persist_and_return(
                decision_id=decision_id,
                request_id=request_id,
                drone_id=None,
                score=None,
                reason=reason,
                input_snapshot={
                    "mission_distance_km": round(mission_distance_km, 3),
                    "weight_kg": weight_kg,
                    "min_battery_pct": min_battery_pct,
                    "priority": priority,
                    "total_drones": len(drones),
                    "rejections": filter_rejections,
                },
                timestamp=now,
                filtered_count=0,
                candidate_count=len(drones),
            )

        # ── Score all feasible candidates ─────────────────────────────────────
        scored: list[tuple[float, dict, float]] = []  # (score, drone, approach_km)
        for drone, approach_km in feasible:
            s = _compute_score(drone, approach_km, weight_kg, priority)
            scored.append((s, drone, approach_km))

        scored.sort(key=lambda t: t[0], reverse=True)
        best_score, best_drone, best_approach_km = scored[0]
        best_id = best_drone.get("drone_id", best_drone.get("id", "?"))

        # Build breakdown for transparency
        battery_score    = best_drone["battery_pct"] / 100.0
        raw_dist         = 1.0 - (best_approach_km / best_drone["max_range_km"])
        distance_score   = max(0.0, min(1.0, raw_dist))
        raw_payload      = 1.0 - (weight_kg / best_drone["max_payload_kg"])
        payload_score    = max(0.0, min(1.0, raw_payload))
        priority_compat  = _PRIORITY_COMPAT.get(priority, 0.25)

        score_breakdown = {
            "battery_score":        round(battery_score,   4),
            "distance_score":       round(distance_score,  4),
            "drone_to_pickup_km":   round(best_approach_km, 4),
            "payload_score":        round(payload_score,   4),
            "availability_score":   1.0,
            "priority_compatibility": round(priority_compat, 4),
            "total":                round(best_score, 4),
        }

        reason = (
            f"Selected drone {best_id!r} with score {best_score:.4f} "
            f"(battery={battery_score:.2f}, dist={distance_score:.2f}"
            f" [approach={best_approach_km:.2f}km], "
            f"payload={payload_score:.2f}, avail=1.00, priority={priority_compat:.2f}). "
            f"{len(feasible)}/{len(drones)} drones passed pre-filter."
        )

        log.info(
            "allocation_agent_selected",
            request_id=request_id,
            drone_id=best_id,
            score=round(best_score, 4),
            feasible_count=len(feasible),
        )

        return await self._persist_and_return(
            decision_id=decision_id,
            request_id=request_id,
            drone_id=best_id,
            score=best_score,
            reason=reason,
            input_snapshot={
                "mission_distance_km": round(mission_distance_km, 3),
                "weight_kg": weight_kg,
                "min_battery_pct": min_battery_pct,
                "priority": priority,
                "total_drones": len(drones),
                "feasible_count": len(feasible),
                "score_breakdown": score_breakdown,
            },
            timestamp=now,
            filtered_count=len(feasible),
            candidate_count=len(drones),
            score_breakdown=score_breakdown,
        )

    # ── Private helpers ───────────────────────────────────────────────────────

    async def _persist_and_return(
        self,
        *,
        decision_id: str,
        request_id: str,
        drone_id: Optional[str],
        score: Optional[float],
        reason: str,
        input_snapshot: dict,
        timestamp: datetime,
        filtered_count: int,
        candidate_count: int,
        score_breakdown: dict = {},
    ) -> AllocationResult:
        """Persist the decision and return the result dataclass. Swallows storage errors."""
        try:
            await self._repo.create({
                "decision_id": decision_id,
                "agent_name": "AllocationAgent",
                "request_id": request_id,
                "decision": drone_id if drone_id else "NO_FEASIBLE_DRONE",
                "score": round(score, 6) if score is not None else None,
                "reason": reason,
                "input_snapshot": input_snapshot,
                "timestamp": timestamp,
            })
        except Exception as exc:
            log.error(
                "allocation_agent_persist_error",
                decision_id=decision_id,
                error=str(exc),
            )

        return AllocationResult(
            drone_id=drone_id,
            score=score,
            reason=reason,
            decision_id=decision_id,
            filtered_count=filtered_count,
            candidate_count=candidate_count,
            score_breakdown=score_breakdown,
        )
