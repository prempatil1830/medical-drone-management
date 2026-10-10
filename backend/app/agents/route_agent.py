"""
app/agents/route_agent.py — Route Agent for Phase 8.

Responsibilities
----------------
1. Receive pickup and destination coordinates.
2. Calculate route distance (using Haversine for v1).
3. Compute ETA based on drone cruise speed.
4. Compute estimated battery consumption based on distance.
5. Return RouteResult dataclass.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from app.core.config import settings
from app.core.logging import get_logger

log = get_logger(__name__)


def _haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Return great-circle distance in kilometres between two (lat, lng) points."""
    R = 6371.0  # Earth radius in km
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lng2 - lng1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


@dataclass
class RouteResult:
    route: list[dict]
    distance_km: float
    eta_minutes: float
    battery_required_pct: float


class RouteAgent:
    """
    Computes route metrics using straight-line distance (v1).
    """

    def run(self, pickup: dict, destination: dict, drone_location: dict = None) -> RouteResult:
        """
        Computes route and returns RouteResult.

        total_flight_km = drone→pickup (approach) + pickup→destination (mission).
        Assumption: drones do NOT return to base after delivery.
        """
        try:
            lat1 = float(pickup["lat"])
            lng1 = float(pickup["lng"])
            lat2 = float(destination["lat"])
            lng2 = float(destination["lng"])
        except (KeyError, TypeError, ValueError) as exc:
            log.error("route_agent_invalid_coordinates", error=str(exc))
            # Return zeroed out metrics safely if parsing fails
            return RouteResult(
                route=[],
                distance_km=0.0,
                eta_minutes=0.0,
                battery_required_pct=0.0
            )

        # ── Approach leg: drone → pickup ──────────────────────────────────────
        approach_km = 0.0
        drone_lat, drone_lng = lat1, lng1  # default: drone is at pickup
        if drone_location:
            try:
                drone_lat = float(
                    drone_location.get("lat", drone_location.get("latitude", lat1))
                )
                drone_lng = float(
                    drone_location.get("lng", drone_location.get("longitude", lng1))
                )
                approach_km = _haversine_km(drone_lat, drone_lng, lat1, lng1)
            except (TypeError, ValueError):
                drone_lat, drone_lng = lat1, lng1

        # ── Mission leg: pickup → destination ─────────────────────────────────
        mission_km = _haversine_km(lat1, lng1, lat2, lng2)

        # ── Total flight (drone does NOT return to base) ──────────────────────
        distance_km = approach_km + mission_km

        # Calculate ETA from total flight distance
        speed_kmh = settings.ROUTE_DRONE_CRUISE_SPEED_KMH
        eta_hours = distance_km / speed_kmh if speed_kmh > 0 else 0
        eta_minutes = eta_hours * 60.0

        # Calculate battery required from total flight distance
        battery_pct_per_km = settings.ROUTE_BATTERY_CONSUMPTION_PER_KM
        battery_required_pct = distance_km * battery_pct_per_km

        # Route waypoints (delivery path: pickup → destination).
        # The simulation engine handles the approach leg independently.
        route = [
            {"lat": lat1, "lng": lng1},
            {"lat": lat2, "lng": lng2},
        ]

        log.info(
            "route_agent_computed",
            approach_km=round(approach_km, 2),
            mission_km=round(mission_km, 2),
            distance_km=round(distance_km, 2),
            eta_minutes=round(eta_minutes, 2),
            battery_required_pct=round(battery_required_pct, 2),
        )

        return RouteResult(
            route=route,
            distance_km=distance_km,
            eta_minutes=eta_minutes,
            battery_required_pct=battery_required_pct
        )
