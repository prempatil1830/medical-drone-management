"""
app/simulation/engine.py — Drone Simulation Engine for Phase 9.

Maintains the state machine of the drone flight, interpolates movement,
updates DB documents, and broadcasts updates via WebSockets.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
import math
from typing import Any

from app.core.config import settings
from app.core.logging import get_logger
from app.db.database import get_database
from app.repositories.drone import DroneRepository
from app.repositories.mission import MissionRepository
from app.repositories.mission_tracking import MissionTrackingRepository
from app.websocket.manager import manager

log = get_logger(__name__)


def _haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Return great-circle distance in kilometres between two (lat, lng) points."""
    R = 6371.0  # Earth radius in km
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lng2 - lng1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


class SimulationEngine:
    def __init__(self) -> None:
        self.active_tasks: dict[str, asyncio.Task] = {}

    async def run_mission_simulation(self, mission_id: str) -> None:
        """
        Runs the async simulation loop for a single mission.
        """
        db = get_database()
        mission_repo = MissionRepository(db)
        drone_repo = DroneRepository(db)
        tracking_repo = MissionTrackingRepository(db)

        # ── 1. Fetch Mission ──────────────────────────────────────────────────
        mission = await mission_repo.get_by_id(mission_id)
        if not mission:
            log.error("simulation_mission_not_found", mission_id=mission_id)
            return

        drone_id = mission["drone_id"]
        request_id = mission["request_id"]
        
        # Get target coordinates
        route_coords = mission["route"]
        if len(route_coords) < 2:
            log.error("simulation_invalid_route", mission_id=mission_id)
            return
            
        pickup_lat = float(route_coords[0]["lat"])
        pickup_lng = float(route_coords[0]["lng"])
        dest_lat = float(route_coords[-1]["lat"])
        dest_lng = float(route_coords[-1]["lng"])

        # ── 2. Fetch Drone Initial Coordinates ────────────────────────────────
        drone = await drone_repo.get_by_drone_id(drone_id)
        if not drone:
            log.error("simulation_drone_not_found", drone_id=drone_id)
            return

        curr_lat = float(drone.get("latitude", pickup_lat))
        curr_lng = float(drone.get("longitude", pickup_lng))
        curr_batt = float(drone.get("battery_pct", 100.0))

        # Simulation speeds
        tick_interval = settings.SIMULATION_TICK_INTERVAL_SEC
        speed_multiplier = settings.SIMULATION_SPEED_MULTIPLIER
        cruise_speed = settings.ROUTE_DRONE_CRUISE_SPEED_KMH  # km/h
        battery_pct_per_km = settings.ROUTE_BATTERY_CONSUMPTION_PER_KM

        # Distance step per tick in km
        step_km = (cruise_speed / 3600.0) * tick_interval * speed_multiplier

        log.info(
            "simulation_started",
            mission_id=mission_id,
            drone_id=drone_id,
            start_coord=(curr_lat, curr_lng),
            pickup_coord=(pickup_lat, pickup_lng),
            dest_coord=(dest_lat, dest_lng),
            step_km=step_km,
        )

        # Helper to log, update DB, and broadcast
        async def update_state(status: str, lat: float, lng: float, batt: float, rem_dist: float, eta: float, failure_reason: str = None):
            # 1. Update Mission collection status
            mission_update = {"status": status}
            if failure_reason:
                mission_update["failure_reason"] = failure_reason
            await db["missions"].update_one(
                {"mission_id": mission_id},
                {"$set": mission_update}
            )

            # Update associated request status in MongoDB
            req_update = {"status": status}
            if failure_reason:
                req_update["failure_reason"] = failure_reason
                
            from bson import ObjectId
            try:
                await db["medical_requests"].update_one(
                    {"_id": ObjectId(request_id)},
                    {"$set": req_update}
                )
            except Exception:
                await db["medical_requests"].update_one(
                    {"request_id": request_id},
                    {"$set": req_update}
                )

            # 2. Update Drone status & coordinates
            await db["drones"].update_one(
                {"drone_id": drone_id},
                {"$set": {"latitude": lat, "longitude": lng, "battery_pct": max(0.0, batt)}}
            )

            # 3. Save to tracking log
            tracking_doc = {
                "mission_id": mission_id,
                "timestamp": datetime.now(UTC),
                "lat": lat,
                "lng": lng,
                "battery_pct": max(0.0, batt),
                "remaining_distance_km": max(0.0, rem_dist),
                "eta_minutes": max(0.0, eta),
                "status": status,
            }
            if failure_reason:
                tracking_doc["failure_reason"] = failure_reason
            await tracking_repo.create(tracking_doc)

            # 4. Broadcast via WebSockets
            await manager.broadcast_to_mission(mission_id, tracking_doc)

        # ── Phase 1: TRAVELLING_TO_PICKUP ────────────────────────────────────
        dist_to_pickup = _haversine_km(curr_lat, curr_lng, pickup_lat, pickup_lng)
        
        if dist_to_pickup > 0.01:
            log.info("simulation_travelling_to_pickup", mission_id=mission_id, dist=dist_to_pickup)
            while dist_to_pickup > 0.01:
                # Decide if we reach in this step
                if dist_to_pickup <= step_km:
                    curr_lat, curr_lng = pickup_lat, pickup_lng
                    curr_batt -= dist_to_pickup * battery_pct_per_km
                    dist_to_pickup = 0.0
                else:
                    fraction = step_km / dist_to_pickup
                    curr_lat += fraction * (pickup_lat - curr_lat)
                    curr_lng += fraction * (pickup_lng - curr_lng)
                    curr_batt -= step_km * battery_pct_per_km
                    dist_to_pickup = _haversine_km(curr_lat, curr_lng, pickup_lat, pickup_lng)

                # Total remaining distance is pickup + destination distance
                rem_to_dest = dist_to_pickup + _haversine_km(pickup_lat, pickup_lng, dest_lat, dest_lng)
                eta = (rem_to_dest / cruise_speed) * 60.0

                if curr_batt <= 0:
                    curr_batt = 0.0
                    await update_state("FAILED", curr_lat, curr_lng, curr_batt, rem_to_dest, 0.0, failure_reason="Battery exhaustion")
                    log.error("simulation_failed_battery_exhaustion", mission_id=mission_id, phase="TRAVELLING_TO_PICKUP")
                    await drone_repo.release_drone(drone_id, curr_lat, curr_lng, curr_batt, "MAINTENANCE")
                    return

                await update_state("TRAVELLING_TO_PICKUP", curr_lat, curr_lng, curr_batt, rem_to_dest, eta)
                await asyncio.sleep(tick_interval)

        # ── Phase 2: PACKAGE_COLLECTED ────────────────────────────────────────
        log.info("simulation_package_collected", mission_id=mission_id)
        # Stay at pickup point for one tick
        rem_to_dest = _haversine_km(pickup_lat, pickup_lng, dest_lat, dest_lng)
        eta = (rem_to_dest / cruise_speed) * 60.0
        await update_state("PACKAGE_COLLECTED", pickup_lat, pickup_lng, curr_batt, rem_to_dest, eta)
        await asyncio.sleep(tick_interval)

        # ── Phase 3: IN_TRANSIT & APPROACHING_DESTINATION ──────────────────────
        dist_to_dest = _haversine_km(pickup_lat, pickup_lng, dest_lat, dest_lng)
        log.info("simulation_in_transit", mission_id=mission_id, dist=dist_to_dest)

        while dist_to_dest > 0.005:
            # Decide if we reach in this step
            if dist_to_dest <= step_km:
                curr_lat, curr_lng = dest_lat, dest_lng
                curr_batt -= dist_to_dest * battery_pct_per_km
                dist_to_dest = 0.0
            else:
                fraction = step_km / dist_to_dest
                curr_lat += fraction * (dest_lat - curr_lat)
                curr_lng += fraction * (dest_lng - curr_lng)
                curr_batt -= step_km * battery_pct_per_km
                dist_to_dest = _haversine_km(curr_lat, curr_lng, dest_lat, dest_lng)

            # Check if approaching
            status = "APPROACHING_DESTINATION" if dist_to_dest < 0.1 else "IN_TRANSIT"
            eta = (dist_to_dest / cruise_speed) * 60.0

            if curr_batt <= 0:
                curr_batt = 0.0
                await update_state("FAILED", curr_lat, curr_lng, curr_batt, dist_to_dest, 0.0, failure_reason="Battery exhaustion")
                log.error("simulation_failed_battery_exhaustion", mission_id=mission_id, phase="IN_TRANSIT")
                await drone_repo.release_drone(drone_id, curr_lat, curr_lng, curr_batt, "MAINTENANCE")
                return

            await update_state(status, curr_lat, curr_lng, curr_batt, dist_to_dest, eta)
            await asyncio.sleep(tick_interval)

        # ── Phase 4: DELIVERED ────────────────────────────────────────────────
        log.info("simulation_delivered", mission_id=mission_id)
        await update_state("DELIVERED", dest_lat, dest_lng, curr_batt, 0.0, 0.0)

        # ── Release Drone ─────────────────────────────────────────────────────
        min_reserve = settings.ALLOCATION_MIN_BATTERY_RESERVE_PCT
        new_status = "AVAILABLE" if curr_batt >= min_reserve else "CHARGING"

        await drone_repo.release_drone(
            drone_id=drone_id,
            latitude=dest_lat,
            longitude=dest_lng,
            battery_pct=curr_batt,
            new_status=new_status,
        )


# Module-level engine instance
simulation_engine = SimulationEngine()
