"""
Unit tests for the 4 issues fixed in the audit report.
"""

import pytest
from unittest.mock import MagicMock, AsyncMock, patch

from app.agents.allocation_agent import AllocationAgent, _haversine_km
from app.agents.route_agent import RouteAgent
from app.simulation.engine import SimulationEngine
from app.core.config import settings

def _mock_decision_repo() -> MagicMock:
    repo = MagicMock()
    repo.create = AsyncMock(return_value={"id": "fake-id"})
    return repo

def _request(pickup=None, destination=None) -> dict:
    return {
        "request_id": "req-1",
        "weight_kg": 2.0,
        "pickup": pickup or {"lat": 12.9716, "lng": 77.5946},
        "destination": destination or {"lat": 12.9352, "lng": 77.6245}, # ~4.7 km
    }

def _drone(drone_id, lat, lng, battery=90.0, max_range=30.0) -> dict:
    return {
        "drone_id": drone_id,
        "battery_pct": battery,
        "max_payload_kg": 5.0,
        "max_range_km": max_range,
        "status": "AVAILABLE",
        "latitude": lat,
        "longitude": lng,
    }


class TestAuditFixes:

    @pytest.mark.asyncio
    async def test_closer_drone_wins(self):
        """1 km vs 6 km drone: closer one wins (distance_score fix)."""
        req = _request(
            pickup={"lat": 12.000, "lng": 77.000},
            destination={"lat": 12.040, "lng": 77.000} # ~4.4km
        )
        # Drone A: 1 km away
        drone_a = _drone("A_1KM", 12.009, 77.000)
        # Drone B: 6 km away
        drone_b = _drone("B_6KM", 12.054, 77.000)

        agent = AllocationAgent(_mock_decision_repo())
        res = await agent.run(req, "High", [drone_a, drone_b])

        assert res.drone_id == "A_1KM"
        # Score breakdown should show drone A has higher distance_score
        assert "drone_to_pickup_km" in res.score_breakdown
        assert res.score_breakdown["drone_to_pickup_km"] < 2.0

    @pytest.mark.asyncio
    async def test_approach_leg_pushes_over_max_range(self):
        """Approach leg makes total > max_range → filtered."""
        req = _request(
            pickup={"lat": 12.000, "lng": 77.000},
            destination={"lat": 12.050, "lng": 77.000} # ~5.5km
        )
        # Drone is 20km away. total = 25.5km. safety factor 1.25 -> 31.8km required.
        # Drone has 30km max range. Should be filtered.
        drone = _drone("D1", 12.180, 77.000, max_range=30.0)

        agent = AllocationAgent(_mock_decision_repo())
        res = await agent.run(req, "High", [drone])
        assert res.drone_id is None
        assert "max_range" in res.reason

    @pytest.mark.asyncio
    async def test_battery_boundary_approach_leg(self):
        """Approach leg makes battery insufficient → rejected."""
        req = _request(
            pickup={"lat": 12.000, "lng": 77.000},
            destination={"lat": 12.050, "lng": 77.000} # ~5.5km
        )
        # Drone is 20km away. total = 25.5km.
        # Battery needed = 25.5 * 1.5 = 38.25%
        # Reserve = 20%
        # Total needed = 58.25%
        # Drone has 50% battery. Should be filtered.
        drone = _drone("D1", 12.180, 77.000, battery=50.0)

        agent = AllocationAgent(_mock_decision_repo())
        res = await agent.run(req, "High", [drone])
        assert res.drone_id is None
        assert "battery_after_flight" in res.reason

    @pytest.mark.asyncio
    async def test_nearest_below_reserve_rejected_next_selected(self):
        """Below-reserve drone rejected with reason, next-nearest wins."""
        req = _request(
            pickup={"lat": 12.000, "lng": 77.000},
            destination={"lat": 12.040, "lng": 77.000} # ~4.4km
        )
        # Drone A: 1 km away, but battery 15% (below 20% reserve)
        drone_a = _drone("A_1KM", 12.009, 77.000, battery=15.0)
        # Drone B: 6 km away, battery 90%
        drone_b = _drone("B_6KM", 12.054, 77.000, battery=90.0)

        agent = AllocationAgent(_mock_decision_repo())
        res = await agent.run(req, "High", [drone_a, drone_b])
        assert res.drone_id == "B_6KM"
        assert res.filtered_count == 1

    def test_route_agent_total_distance_and_battery(self):
        """5 km approach + 2 km mission = 7 km total, battery correct."""
        pickup = {"lat": 12.000, "lng": 77.000}
        destination = {"lat": 12.018, "lng": 77.000} # ~2km
        drone_location = {"lat": 12.045, "lng": 77.000} # ~5km from pickup

        agent = RouteAgent()
        res = agent.run(pickup, destination, drone_location)

        # Expected distance ~ 7.0 km
        assert 6.5 < res.distance_km < 7.5
        # Expected battery = distance * 1.5
        assert res.battery_required_pct == pytest.approx(res.distance_km * 1.5)


    @pytest.mark.asyncio
    async def test_drone_available_after_delivered(self):
        """Post-DELIVERED: drone AVAILABLE, position/battery updated."""
        
        # Mocking the repository calls directly
        mock_mission = {
            "mission_id": "M1",
            "request_id": "R1",
            "drone_id": "D1",
            "route": [{"lat": 12.000, "lng": 77.000}, {"lat": 12.000, "lng": 77.0001}] # 0.011km
        }
        
        mock_drone = {
            "drone_id": "D1",
            "latitude": 12.000,
            "longitude": 77.000,
            "battery_pct": 100.0
        }
        
        # We patch the db so that get_database returns a mock
        mock_db = MagicMock()
        mock_col = MagicMock()
        mock_col.update_one = AsyncMock()
        mock_db.__getitem__.return_value = mock_col # For db["missions"], etc.

        with patch("app.simulation.engine.get_database", return_value=mock_db), \
             patch("app.simulation.engine.MissionRepository") as mock_mission_repo_cls, \
             patch("app.simulation.engine.DroneRepository") as mock_drone_repo_cls, \
             patch("app.simulation.engine.MissionTrackingRepository") as mock_tracking_repo_cls, \
             patch("app.simulation.engine.manager") as mock_manager, \
             patch("asyncio.sleep", AsyncMock()):

            mock_mission_repo = MagicMock()
            mock_mission_repo.get_by_id = AsyncMock(return_value=mock_mission)
            mock_mission_repo_cls.return_value = mock_mission_repo

            mock_drone_repo = MagicMock()
            mock_drone_repo.get_by_drone_id = AsyncMock(return_value=mock_drone)
            mock_drone_repo.release_drone = AsyncMock(return_value=True)
            mock_drone_repo_cls.return_value = mock_drone_repo
            
            mock_tracking_repo = MagicMock()
            mock_tracking_repo.create = AsyncMock()
            mock_tracking_repo_cls.return_value = mock_tracking_repo
            
            mock_manager.broadcast_to_mission = AsyncMock()

            engine = SimulationEngine()
            await engine.run_mission_simulation("M1")
            
            # Since battery > 20%, status should be AVAILABLE
            mock_drone_repo.release_drone.assert_called_once()
            args, kwargs = mock_drone_repo.release_drone.call_args
            assert kwargs["drone_id"] == "D1"
            assert kwargs["new_status"] == "AVAILABLE"
            assert kwargs["battery_pct"] > 80.0
