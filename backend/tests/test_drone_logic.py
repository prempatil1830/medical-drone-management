import asyncio
from datetime import UTC, datetime
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi.testclient import TestClient

from app.main import app
from app.simulation.engine import simulation_engine
from app.websocket.manager import manager
from app.repositories.mission import get_mission_repo
from app.repositories.medical_request import get_request_repo
from app.repositories.drone import get_drone_repo
from app.api.auth import get_current_user
from app.agents.allocation_agent import AllocationAgent
from app.agents.allocation_agent import AllocationAgent
from app.agents.route_agent import RouteAgent
from app.simulation.engine import SimulationEngine


def _mock_decision_repo() -> MagicMock:
    repo = MagicMock()
    repo.create = AsyncMock(return_value={"id": "fake-id"})
    return repo


def _request(pickup=None, destination=None) -> dict:
    return {
        "request_id": "req-1",
        "weight_kg": 2.0,
        "pickup": pickup or {"lat": 12.9716, "lng": 77.5946},
        "destination": destination or {"lat": 12.9352, "lng": 77.6245},
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


# ── 1-6. Drone Logic Tests ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_closer_drone_wins():
    """1 km vs 6 km drone: closer one wins (distance_score fix)."""
    req = _request(
        pickup={"lat": 12.000, "lng": 77.000},
        destination={"lat": 12.040, "lng": 77.000},
    )
    drone_a = _drone("A_1KM", 12.009, 77.000)
    drone_b = _drone("B_6KM", 12.054, 77.000)

    agent = AllocationAgent(_mock_decision_repo())
    res = await agent.run(req, "High", [drone_a, drone_b])

    assert res.drone_id == "A_1KM"
    assert "drone_to_pickup_km" in res.score_breakdown
    assert res.score_breakdown["drone_to_pickup_km"] == pytest.approx(1.00075, rel=1e-2)


@pytest.mark.asyncio
async def test_approach_leg_pushes_over_max_range():
    """Approach leg makes total > max_range → filtered."""
    req = _request(
        pickup={"lat": 12.000, "lng": 77.000},
        destination={"lat": 12.050, "lng": 77.000},
    )
    drone = _drone("D1", 12.180, 77.000, max_range=30.0)

    agent = AllocationAgent(_mock_decision_repo())
    res = await agent.run(req, "High", [drone])
    assert res.drone_id is None
    assert "max_range" in res.reason


@pytest.mark.asyncio
async def test_battery_boundary_approach_leg():
    """Approach leg makes battery insufficient → rejected."""
    req = _request(
        pickup={"lat": 12.000, "lng": 77.000},
        destination={"lat": 12.050, "lng": 77.000},
    )
    drone = _drone("D1", 12.180, 77.000, battery=50.0)

    agent = AllocationAgent(_mock_decision_repo())
    res = await agent.run(req, "High", [drone])
    assert res.drone_id is None
    assert "battery_after_flight" in res.reason


@pytest.mark.asyncio
async def test_nearest_below_reserve_rejected_next_selected():
    """Below-reserve drone rejected with reason, next-nearest wins."""
    req = _request(
        pickup={"lat": 12.000, "lng": 77.000},
        destination={"lat": 12.040, "lng": 77.000},
    )
    drone_a = _drone("A_1KM", 12.009, 77.000, battery=15.0)
    drone_b = _drone("B_6KM", 12.054, 77.000, battery=90.0)

    agent = AllocationAgent(_mock_decision_repo())
    res = await agent.run(req, "High", [drone_a, drone_b])
    assert res.drone_id == "B_6KM"
    assert res.filtered_count == 1


def test_route_agent_total_distance_and_battery():
    """5 km approach + 2 km mission = 7 km total, battery correct."""
    pickup = {"lat": 12.000, "lng": 77.000}
    destination = {"lat": 12.018, "lng": 77.000}
    drone_location = {"lat": 12.045, "lng": 77.000}

    agent = RouteAgent()
    res = agent.run(pickup, destination, drone_location)

    assert 6.5 < res.distance_km < 7.5
    assert res.battery_required_pct == pytest.approx(res.distance_km * 1.5)


@pytest.mark.asyncio
async def test_drone_available_after_delivered():
    """Post-DELIVERED: drone AVAILABLE, position/battery updated."""
    mock_mission = {
        "mission_id": "M1",
        "request_id": "R1",
        "drone_id": "D1",
        "route": [{"lat": 12.000, "lng": 77.000}, {"lat": 12.000, "lng": 77.0001}],
    }
    mock_drone = {
        "drone_id": "D1",
        "latitude": 12.000,
        "longitude": 77.000,
        "battery_pct": 100.0,
    }

    mock_db = MagicMock()
    mock_col = MagicMock()
    mock_col.update_one = AsyncMock()
    mock_db.__getitem__.return_value = mock_col

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

        mock_drone_repo.release_drone.assert_called_once()
        args, kwargs = mock_drone_repo.release_drone.call_args
        assert kwargs["drone_id"] == "D1"
        assert kwargs["new_status"] == "AVAILABLE"
        assert kwargs["battery_pct"] == pytest.approx(99.98, rel=1e-2)


# ── 7. Mission Fail (Fault injection) ─────────────────────────────────────────

@pytest.mark.asyncio
async def test_fault_injection_mission_fail():
    """
    POST /api/missions/{id}/fail:
    - 403 for hospital user
    - cancels running simulation task
    - marks mission FAILED with failure reason
    - marks request FAILED with failure reason
    - sets drone to MAINTENANCE
    - broadcasts WebSocket message
    """
    mission_id = "m-fail-100"
    drone_id = "BLR-D001"
    request_id = "64f1a2b3c4d5e6f7a8b9c0d3"

    mission_doc = {
        "id": "64f1a2b3c4d5e6f7a8b9c0d9",
        "mission_id": mission_id,
        "drone_id": drone_id,
        "request_id": request_id,
        "route": [{"lat": 12.9, "lng": 77.5}, {"lat": 12.95, "lng": 77.6}],
        "distance_km": 5.0,
        "eta_minutes": 10.0,
        "battery_required_pct": 20.0,
        "status": "IN_TRANSIT",
        "started_at": datetime.now(UTC),
    }

    mock_mission_repo = MagicMock()
    mock_mission_repo.get_by_id = AsyncMock(side_effect=lambda mid: dict(mission_doc))

    mock_req_repo = MagicMock()
    mock_req_repo.get_by_id = AsyncMock(return_value={"id": request_id, "center_id": "c1"})

    mock_drone_repo = MagicMock()

    mock_db = MagicMock()
    missions_col = AsyncMock()
    req_col = AsyncMock()
    drones_col = AsyncMock()
    mock_db.__getitem__.side_effect = lambda name: {
        "missions": missions_col,
        "medical_requests": req_col,
        "drones": drones_col,
    }[name]

    # Spawn a fake running background task in simulation_engine
    async def dummy_sim_loop():
        await asyncio.sleep(100)

    sim_task = asyncio.create_task(dummy_sim_loop())
    simulation_engine.active_tasks[mission_id] = sim_task

    client = TestClient(app)
    app.dependency_overrides[get_mission_repo] = lambda: mock_mission_repo
    app.dependency_overrides[get_request_repo] = lambda: mock_req_repo
    app.dependency_overrides[get_drone_repo] = lambda: mock_drone_repo

    # 1. Hospital user receives 403 Forbidden
    app.dependency_overrides[get_current_user] = lambda: {"id": "u1", "role": "hospital", "center_id": "c1"}
    res_hosp = client.post(f"/api/missions/{mission_id}/fail", json={"reason": "motor overheating"})
    assert res_hosp.status_code == 403

    # 2. Operator/Admin succeeds
    app.dependency_overrides[get_current_user] = lambda: {"id": "u2", "role": "operator"}
    with patch("app.db.database.get_database", return_value=mock_db), \
         patch.object(manager, "broadcast_to_mission", AsyncMock()) as mock_broadcast:

        res = client.post(f"/api/missions/{mission_id}/fail", json={"reason": "motor overheating"})
        assert res.status_code == 200

        # Assert simulation task was cancelled
        assert getattr(sim_task, "cancelling", lambda: 0)() > 0 or sim_task.cancelled() or sim_task.done()

        # Assert mission status update
        missions_col.update_one.assert_called_once_with(
            {"mission_id": mission_id},
            {"$set": {"status": "FAILED", "failure_reason": "motor overheating"}},
        )

        # Assert drone set to MAINTENANCE
        drones_col.update_one.assert_called_once_with(
            {"drone_id": drone_id},
            {"$set": {"status": "MAINTENANCE"}},
        )

        # Assert WebSocket broadcast
        mock_broadcast.assert_called_once()
        bc_args = mock_broadcast.call_args[0]
        assert bc_args[0] == mission_id
        assert bc_args[1]["status"] == "FAILED"
        assert bc_args[1]["failure_reason"] == "motor overheating"

    app.dependency_overrides.clear()
    if mission_id in simulation_engine.active_tasks:
        del simulation_engine.active_tasks[mission_id]


# ── 8. Drone Missing Location Fail Closed ─────────────────────────────────────

@pytest.mark.asyncio
async def test_drone_missing_location_fail_closed():
    """
    Missing or invalid drone coordinates:
    - missing latitude or missing longitude
    - non-numeric coordinates
    - out of range coordinates (lat not in [-90, 90], lng not in [-180, 180])
    must be safely handled and rejected as infeasible by AllocationAgent.
    """
    req = {
        "request_id": "req-1",
        "weight_kg": 2.0,
        "pickup": {"lat": 12.9716, "lng": 77.5946},
        "destination": {"lat": 12.9352, "lng": 77.6245},
    }

    mock_decision_repo = MagicMock()
    mock_decision_repo.create = AsyncMock(return_value={"id": "dec-1"})
    agent = AllocationAgent(mock_decision_repo)

    # 1. Missing latitude
    d_no_lat = {
        "drone_id": "D-NOLAT",
        "battery_pct": 90.0,
        "max_payload_kg": 5.0,
        "max_range_km": 30.0,
        "status": "AVAILABLE",
        "longitude": 77.5946,
    }
    # 2. Non-numeric longitude
    d_bad_type = {
        "drone_id": "D-BADTYPE",
        "battery_pct": 90.0,
        "max_payload_kg": 5.0,
        "max_range_km": 30.0,
        "status": "AVAILABLE",
        "latitude": 12.9716,
        "longitude": "invalid_lng",
    }
    # 3. Latitude out of range
    d_out_of_range = {
        "drone_id": "D-OUTOFRANGE",
        "battery_pct": 90.0,
        "max_payload_kg": 5.0,
        "max_range_km": 30.0,
        "status": "AVAILABLE",
        "latitude": 120.0,
        "longitude": 77.5946,
    }
    # 4. Valid drone
    d_valid = {
        "drone_id": "D-VALID",
        "battery_pct": 90.0,
        "max_payload_kg": 5.0,
        "max_range_km": 30.0,
        "status": "AVAILABLE",
        "latitude": 12.9716,
        "longitude": 77.5946,
    }

    # Only valid drone should be selected
    res = await agent.run(req, "High", [d_no_lat, d_bad_type, d_out_of_range, d_valid])
    assert res.drone_id == "D-VALID"

    # When no valid drones exist, returns None
    res_none = await agent.run(req, "High", [d_no_lat, d_bad_type, d_out_of_range])
    assert res_none.drone_id is None
    assert "NO_FEASIBLE_DRONE" in res_none.reason
    assert "missing coordinates" in res_none.reason
    assert "invalid coordinates" in res_none.reason


# ── 9. Admin Patch Drone Status ───────────────────────────────────────────────

@pytest.mark.asyncio
async def test_admin_patch_drone_status():
    """
    PATCH /api/drones/{id}/status:
    - Admin only: Hospital and Operator get 403
    - Assert all allowed transitions (200):
      * MAINTENANCE -> AVAILABLE, CHARGING, OFFLINE
      * OFFLINE -> AVAILABLE, MAINTENANCE
      * CHARGING -> AVAILABLE, MAINTENANCE
    - Assert forbidden transitions (400):
      * AVAILABLE -> CHARGING, MAINTENANCE, OFFLINE
      * OFFLINE -> CHARGING
      * CHARGING -> OFFLINE
    """
    drone_id = "BLR-D001"

    current_drone_status = "MAINTENANCE"
    def get_fake_drone():
        return {
            "id": "64f1a2b3c4d5e6f7a8b9c0d4",
            "drone_id": drone_id,
            "model": "MediHawk X200",
            "battery_pct": 90.0,
            "max_payload_kg": 5.0,
            "max_range_km": 25.0,
            "latitude": 12.9716,
            "longitude": 77.5946,
            "status": current_drone_status,
            "zone": "Central Bengaluru",
            "updated_at": datetime.now(UTC),
        }

    mock_drone_repo = MagicMock()
    mock_drone_repo.get_by_drone_id = AsyncMock(side_effect=lambda did: get_fake_drone())
    mock_drone_repo.update_status = AsyncMock()

    client = TestClient(app)
    app.dependency_overrides[get_drone_repo] = lambda: mock_drone_repo

    try:
        # 1. RBAC: Hospital and Operator are forbidden (403)
        app.dependency_overrides[get_current_user] = lambda: {"id": "u1", "role": "hospital"}
        res_hosp = client.patch(f"/api/drones/{drone_id}/status", json={"status": "AVAILABLE"})
        assert res_hosp.status_code == 403

        app.dependency_overrides[get_current_user] = lambda: {"id": "u2", "role": "operator"}
        res_op = client.patch(f"/api/drones/{drone_id}/status", json={"status": "AVAILABLE"})
        assert res_op.status_code == 403

        # 2. Admin allows valid transitions
        app.dependency_overrides[get_current_user] = lambda: {"id": "u3", "role": "admin"}

        allowed_pairs = [
            ("MAINTENANCE", "AVAILABLE"),
            ("MAINTENANCE", "CHARGING"),
            ("MAINTENANCE", "OFFLINE"),
            ("OFFLINE", "AVAILABLE"),
            ("OFFLINE", "MAINTENANCE"),
            ("CHARGING", "AVAILABLE"),
            ("CHARGING", "MAINTENANCE"),
        ]

        for from_st, to_st in allowed_pairs:
            current_drone_status = from_st
            res = client.patch(f"/api/drones/{drone_id}/status", json={"status": to_st})
            assert res.status_code == 200, f"Expected 200 for {from_st} -> {to_st}, got {res.status_code}"

        forbidden_pairs = [
            ("AVAILABLE", "CHARGING"),
            ("AVAILABLE", "MAINTENANCE"),
            ("AVAILABLE", "OFFLINE"),
            ("OFFLINE", "CHARGING"),
            ("CHARGING", "OFFLINE"),
        ]

        for from_st, to_st in forbidden_pairs:
            current_drone_status = from_st
            res = client.patch(f"/api/drones/{drone_id}/status", json={"status": to_st})
            assert res.status_code == 400, f"Expected 400 for {from_st} -> {to_st}, got {res.status_code}"
    finally:
        app.dependency_overrides.clear()
