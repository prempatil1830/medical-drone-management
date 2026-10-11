import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from app.schemas.mission import MissionStatus, TERMINAL_MISSION_STATUSES
from app.schemas.medical_request import RequestStatus
from app.schemas.drone import DroneStatus
from app.core.config import settings


@pytest.mark.asyncio
async def test_orphaned_missions_on_simulated_restart():
    """
    Simulated server restart:
    Missions in non-terminal states with no active running task must be marked FAILED
    with failure_reason='server restarted', their requests marked FAILED with
    failure_reason='server restarted', and their drones released:
    - mid-flight mission with last tracking battery 70% -> drone released at tracking point as AVAILABLE
    - last tracking battery below reserve (15% < 20%) -> drone released as CHARGING
    - mission with no tracking documents -> drone document values used
    - DELIVERED, FAILED and CANCELLED missions, their requests and drones remain untouched.
    """
    from app.main import lifespan, app

    # In-memory mock documents
    missions = {
        # 1. Mid-flight mission with last tracking battery 70%
        "m-midflight": {
            "_id": "oid-m1",
            "mission_id": "m-midflight",
            "request_id": "req-midflight",
            "drone_id": "BLR-D001",
            "status": "IN_TRANSIT",
            "failure_reason": None,
        },
        # 2. Below reserve mission (battery 15% < 20%)
        "m-lowbatt": {
            "_id": "oid-m2",
            "mission_id": "m-lowbatt",
            "request_id": "req-lowbatt",
            "drone_id": "BLR-D002",
            "status": "TRAVELLING_TO_PICKUP",
            "failure_reason": None,
        },
        # 3. Orphan with no tracking documents
        "m-notracking": {
            "_id": "oid-m3",
            "mission_id": "m-notracking",
            "request_id": "req-notracking",
            "drone_id": "BLR-D003",
            "status": "ASSIGNED",
            "failure_reason": None,
        },
        # 4. Terminal: DELIVERED
        "m-delivered": {
            "_id": "oid-m4",
            "mission_id": "m-delivered",
            "request_id": "req-delivered",
            "drone_id": "BLR-D004",
            "status": "DELIVERED",
            "failure_reason": None,
        },
        # 5. Terminal: FAILED
        "m-failed": {
            "_id": "oid-m5",
            "mission_id": "m-failed",
            "request_id": "req-failed",
            "drone_id": "BLR-D005",
            "status": "FAILED",
            "failure_reason": "weather abort",
        },
        # 6. Terminal: CANCELLED
        "m-cancelled": {
            "_id": "oid-m6",
            "mission_id": "m-cancelled",
            "request_id": "req-cancelled",
            "drone_id": "BLR-D006",
            "status": "CANCELLED",
            "failure_reason": None,
        },
    }

    requests = {
        "req-midflight": {"_id": "oid-r1", "request_id": "req-midflight", "status": "IN_TRANSIT", "failure_reason": None},
        "req-lowbatt": {"_id": "oid-r2", "request_id": "req-lowbatt", "status": "ASSIGNED", "failure_reason": None},
        "req-notracking": {"_id": "oid-r3", "request_id": "req-notracking", "status": "ASSIGNED", "failure_reason": None},
        "req-delivered": {"_id": "oid-r4", "request_id": "req-delivered", "status": "DELIVERED", "failure_reason": None},
        "req-failed": {"_id": "oid-r5", "request_id": "req-failed", "status": "FAILED", "failure_reason": "weather abort"},
        "req-cancelled": {"_id": "oid-r6", "request_id": "req-cancelled", "status": "CANCELLED", "failure_reason": None},
    }

    drones = {
        "BLR-D001": {
            "_id": "oid-d1",
            "drone_id": "BLR-D001",
            "latitude": 12.0,
            "longitude": 77.0,
            "battery_pct": 95.0,
            "status": "IN_FLIGHT",
        },
        "BLR-D002": {
            "_id": "oid-d2",
            "drone_id": "BLR-D002",
            "latitude": 12.1,
            "longitude": 77.1,
            "battery_pct": 50.0,
            "status": "IN_FLIGHT",
        },
        "BLR-D003": {
            "_id": "oid-d3",
            "drone_id": "BLR-D003",
            "latitude": 12.91,
            "longitude": 77.61,
            "battery_pct": 85.0,
            "status": "ASSIGNED",
        },
        "BLR-D004": {
            "_id": "oid-d4",
            "drone_id": "BLR-D004",
            "latitude": 12.92,
            "longitude": 77.62,
            "battery_pct": 90.0,
            "status": "AVAILABLE",
        },
        "BLR-D005": {
            "_id": "oid-d5",
            "drone_id": "BLR-D005",
            "latitude": 12.93,
            "longitude": 77.63,
            "battery_pct": 50.0,
            "status": "MAINTENANCE",
        },
        "BLR-D006": {
            "_id": "oid-d6",
            "drone_id": "BLR-D006",
            "latitude": 12.94,
            "longitude": 77.64,
            "battery_pct": 95.0,
            "status": "AVAILABLE",
        },
    }

    # Tracking points:
    # m-midflight: tracking battery 70.0% at lat 12.95, lng 77.55
    # m-lowbatt: tracking battery 15.0% (< reserve 20.0%) at lat 12.85, lng 77.45
    # m-notracking: no points
    tracking = [
        {"mission_id": "m-midflight", "lat": 12.95, "lng": 77.55, "battery_pct": 70.0, "timestamp": 10},
        {"mission_id": "m-lowbatt", "lat": 12.85, "lng": 77.45, "battery_pct": 15.0, "timestamp": 20},
    ]

    mock_db = MagicMock()

    def find_missions(query):
        res = []
        nin = query.get("status", {}).get("$nin", [])
        for m in missions.values():
            if m["status"] not in nin:
                res.append(dict(m))
        cursor = MagicMock()
        cursor.to_list = AsyncMock(return_value=res)
        return cursor

    async def update_mission(query, update):
        mid = query.get("mission_id")
        if mid in missions:
            missions[mid].update(update.get("$set", {}))
        res = MagicMock()
        res.matched_count = 1
        res.modified_count = 1
        return res

    async def update_request(query, update):
        req_id = query.get("request_id") or query.get("_id")
        for r in requests.values():
            if r["request_id"] == req_id or r["_id"] == req_id:
                r.update(update.get("$set", {}))
        res = MagicMock()
        res.matched_count = 1
        res.modified_count = 1
        return res

    async def update_drone(query, update):
        did = query.get("drone_id")
        if did in drones:
            drones[did].update(update.get("$set", {}))
        res = MagicMock()
        res.matched_count = 1
        res.modified_count = 1
        return res

    async def find_tracking(query, sort=None):
        mid = query.get("mission_id")
        for t in tracking:
            if t["mission_id"] == mid:
                return dict(t)
        return None

    missions_col = MagicMock()
    missions_col.find = find_missions
    missions_col.update_one = AsyncMock(side_effect=update_mission)
    missions_col.create_index = AsyncMock()

    requests_col = MagicMock()
    requests_col.update_one = AsyncMock(side_effect=update_request)
    requests_col.create_index = AsyncMock()

    drones_col = MagicMock()
    drones_col.find_one = AsyncMock(side_effect=lambda q: dict(drones[q["drone_id"]]) if q.get("drone_id") in drones else None)
    drones_col.update_one = AsyncMock(side_effect=update_drone)
    drones_col.create_index = AsyncMock()

    tracking_col = MagicMock()
    tracking_col.find_one = AsyncMock(side_effect=find_tracking)
    tracking_col.create_index = AsyncMock()

    cols = {
        "missions": missions_col,
        "medical_requests": requests_col,
        "drones": drones_col,
        "mission_tracking": tracking_col,
        "mission_trackings": tracking_col,
        "users": MagicMock(create_index=AsyncMock()),
        "weather_observations": MagicMock(create_index=AsyncMock()),
        "agent_decisions": MagicMock(create_index=AsyncMock()),
    }
    mock_db.__getitem__.side_effect = lambda name: cols[name]

    with patch("app.main.connect_db", AsyncMock()), \
         patch("app.main.close_db", AsyncMock()), \
         patch("app.db.database.get_database", return_value=mock_db), \
         patch("app.simulation.recharge.recharge_service.start", MagicMock()), \
         patch("app.simulation.recharge.recharge_service.stop", AsyncMock()):

        # Simulate app startup via lifespan
        async with lifespan(app):
            pass

    # ── Assertion 1: Mid-flight mission with tracking point battery 70.0% ─────
    # Mission marked FAILED with 'server restarted'
    assert missions["m-midflight"]["status"] == MissionStatus.failed.value
    assert missions["m-midflight"]["failure_reason"] == "server restarted"
    # Request marked FAILED with 'server restarted'
    assert requests["req-midflight"]["status"] == RequestStatus.failed.value
    assert requests["req-midflight"]["failure_reason"] == "server restarted"
    # Drone released at tracking coordinates as AVAILABLE
    assert drones["BLR-D001"]["status"] == DroneStatus.available.value
    assert drones["BLR-D001"]["latitude"] == pytest.approx(12.95)
    assert drones["BLR-D001"]["longitude"] == pytest.approx(77.55)
    assert drones["BLR-D001"]["battery_pct"] == pytest.approx(70.0)

    # ── Assertion 2: Mission with tracking battery below reserve (15.0% < 20%) ─
    # Mission marked FAILED with 'server restarted'
    assert missions["m-lowbatt"]["status"] == MissionStatus.failed.value
    assert missions["m-lowbatt"]["failure_reason"] == "server restarted"
    # Request marked FAILED with 'server restarted'
    assert requests["req-lowbatt"]["status"] == RequestStatus.failed.value
    assert requests["req-lowbatt"]["failure_reason"] == "server restarted"
    # Drone released as CHARGING due to reserve threshold
    assert drones["BLR-D002"]["status"] == DroneStatus.charging.value
    assert drones["BLR-D002"]["latitude"] == pytest.approx(12.85)
    assert drones["BLR-D002"]["longitude"] == pytest.approx(77.45)
    assert drones["BLR-D002"]["battery_pct"] == pytest.approx(15.0)

    # ── Assertion 3: Orphan mission with no tracking documents ────────────────
    # Mission marked FAILED with 'server restarted'
    assert missions["m-notracking"]["status"] == MissionStatus.failed.value
    assert missions["m-notracking"]["failure_reason"] == "server restarted"
    # Request marked FAILED with 'server restarted'
    assert requests["req-notracking"]["status"] == RequestStatus.failed.value
    assert requests["req-notracking"]["failure_reason"] == "server restarted"
    # Drone released using drone document values (lat 12.91, lng 77.61, battery 85.0% >= 20% -> AVAILABLE)
    assert drones["BLR-D003"]["status"] == DroneStatus.available.value
    assert drones["BLR-D003"]["latitude"] == pytest.approx(12.91)
    assert drones["BLR-D003"]["longitude"] == pytest.approx(77.61)
    assert drones["BLR-D003"]["battery_pct"] == pytest.approx(85.0)

    # ── Assertion 4: Terminal DELIVERED mission, request and drone untouched ──
    assert missions["m-delivered"]["status"] == "DELIVERED"
    assert missions["m-delivered"]["failure_reason"] is None
    assert requests["req-delivered"]["status"] == "DELIVERED"
    assert requests["req-delivered"]["failure_reason"] is None
    assert drones["BLR-D004"]["status"] == "AVAILABLE"
    assert drones["BLR-D004"]["battery_pct"] == pytest.approx(90.0)

    # ── Assertion 5: Terminal FAILED mission, request and drone untouched ──────
    assert missions["m-failed"]["status"] == "FAILED"
    assert missions["m-failed"]["failure_reason"] == "weather abort"
    assert requests["req-failed"]["status"] == "FAILED"
    assert requests["req-failed"]["failure_reason"] == "weather abort"
    assert drones["BLR-D005"]["status"] == "MAINTENANCE"
    assert drones["BLR-D005"]["battery_pct"] == pytest.approx(50.0)

    # ── Assertion 6: Terminal CANCELLED mission, request and drone untouched ───
    assert missions["m-cancelled"]["status"] == "CANCELLED"
    assert missions["m-cancelled"]["failure_reason"] is None
    assert requests["req-cancelled"]["status"] == "CANCELLED"
    assert requests["req-cancelled"]["failure_reason"] is None
    assert drones["BLR-D006"]["status"] == "AVAILABLE"
    assert drones["BLR-D006"]["battery_pct"] == pytest.approx(95.0)
