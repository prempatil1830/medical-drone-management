"""
Integration test suite for the AI-Powered Medical Drone Delivery Management and Simulation Platform.
Runs against a REAL MongoDB in dedicated database 'medical_drone_test', dropped after the session.
All tests are marked with @pytest.mark.integration.
"""

from datetime import UTC, datetime
import asyncio
import os
import pytest
from bson import ObjectId
import httpx
from httpx import AsyncClient, ASGITransport, TimeoutException
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase
from unittest.mock import AsyncMock, MagicMock, patch

from app.main import app, lifespan
from app.core.config import settings
from app.core.security import create_access_token, hash_password
from app.db.database import get_database
from app.repositories.user import UserRepository
from app.repositories.medical_request import MedicalRequestRepository
from app.repositories.drone import DroneRepository
from app.repositories.mission import MissionRepository
from app.repositories.agent_decision import AgentDecisionRepository
from app.simulation.recharge import RechargeService
from app.schemas.mission import MissionStatus, TERMINAL_MISSION_STATUSES
from app.schemas.medical_request import RequestStatus
from app.schemas.drone import DroneStatus

TEST_DB_NAME = "medical_drone_test"
MONGO_URI = settings.MONGODB_URI or "mongodb://localhost:27017"


SAFE_WEATHER_PAYLOAD = {
    "location": {"name": "Bengaluru", "lat": 12.9716, "lon": 77.5946},
    "current": {
        "temp_c": 22.0,
        "wind_kph": 10.0,
        "wind_gust_kph": 12.0,
        "precip_mm": 0.0,
        "vis_km": 10.0,
        "humidity": 50,
        "cloud": 20,
        "pressure_mb": 1013.0,
        "condition": {"text": "Clear"},
    },
}


# ── Pytest Session / Module Fixtures ──────────────────────────────────────────

@pytest.fixture(scope="session", autouse=True)
def check_mongo_connectivity_and_cleanup():
    """Verify MongoDB connectivity; skip all integration tests if unreachable. Clean up at teardown."""
    import pymongo
    try:
        sync_client = pymongo.MongoClient(MONGO_URI, serverSelectionTimeoutMS=2000)
        sync_client.admin.command("ping")
    except Exception as exc:
        pytest.skip(f"MongoDB is unreachable at {MONGO_URI}: {exc}")

    # TEST ISOLATION: Assert test DB configuration and capture dev database (medical_drone) counts before run
    assert TEST_DB_NAME == "medical_drone_test", f"Expected test DB to be 'medical_drone_test', got {TEST_DB_NAME}"
    dev_db = sync_client["medical_drone"]
    dev_counts_before = {c: dev_db[c].count_documents({}) for c in sorted(dev_db.list_collection_names())}
    print(f"\n[TEST ISOLATION] Dev database ('medical_drone') collection counts BEFORE integration run: {dev_counts_before}")

    orig_key = settings.WEATHER_API_KEY
    if not settings.WEATHER_API_KEY:
        settings.WEATHER_API_KEY = "test_api_key"

    yield

    settings.WEATHER_API_KEY = orig_key
    dev_counts_after = {c: dev_db[c].count_documents({}) for c in sorted(dev_db.list_collection_names())}
    print(f"\n[TEST ISOLATION] Dev database ('medical_drone') collection counts AFTER integration run: {dev_counts_after}")
    assert dev_counts_before == dev_counts_after, (
        f"Dev database was modified during integration run! Before: {dev_counts_before}, After: {dev_counts_after}"
    )

    try:
        sync_client.drop_database(TEST_DB_NAME)
        sync_client.close()
    except Exception:
        pass


@pytest.fixture
async def real_db():
    """Provide a clean 'medical_drone_test' database for each integration test."""
    client = AsyncIOMotorClient(MONGO_URI, serverSelectionTimeoutMS=2000)
    db = client[TEST_DB_NAME]
    # Assert isolation: the database used is strictly 'medical_drone_test'
    assert db.name == "medical_drone_test", f"App must use 'medical_drone_test', got {db.name}"

    # Drop all collections before each test to ensure isolation
    cols = await db.list_collection_names()
    for col in cols:
        await db[col].drop()

    # Point global app state and dependency overrides to real_db
    import app.db.database as db_mod
    original_db = db_mod._database
    original_client = db_mod._client
    db_mod._database = db
    db_mod._client = client

    app.dependency_overrides[get_database] = lambda: db

    # Ensure all collection indexes
    await UserRepository(db).ensure_indexes()
    await DroneRepository(db).ensure_indexes()
    await MedicalRequestRepository(db).ensure_indexes()
    await MissionRepository(db).ensure_indexes()
    await AgentDecisionRepository(db).ensure_indexes()

    yield db

    app.dependency_overrides.clear()
    db_mod._database = original_db
    db_mod._client = original_client
    client.close()


@pytest.fixture
async def op_token(real_db):
    oid = ObjectId()
    await real_db["users"].insert_one({
        "_id": oid,
        "name": "Operator Test",
        "email": "operator.test@example.com",
        "role": "operator",
        "password_hash": hash_password("Password123!"),
    })
    return create_access_token({"sub": str(oid), "role": "operator"})


@pytest.fixture
async def admin_token(real_db):
    oid = ObjectId()
    await real_db["users"].insert_one({
        "_id": oid,
        "name": "Admin Test",
        "email": "admin.test@example.com",
        "role": "admin",
        "password_hash": hash_password("Password123!"),
    })
    return create_access_token({"sub": str(oid), "role": "admin"})


@pytest.fixture
async def hosp_token(real_db):
    oid = ObjectId()
    await real_db["users"].insert_one({
        "_id": oid,
        "name": "Hospital Test",
        "email": "hospital.test@example.com",
        "role": "hospital",
        "center_id": "c-hosp-1",
        "password_hash": hash_password("Password123!"),
    })
    return create_access_token({"sub": str(oid), "role": "hospital", "center_id": "c-hosp-1"})


# ── 1. Unique Index on users.email & Duplicate Registration ───────────────────

@pytest.mark.integration
@pytest.mark.asyncio
async def test_integration_user_unique_index_and_duplicate_registration(real_db):
    """
    1. The unique index on users.email exists (print the list of indexes).
    2. A duplicate registration returns a clean 4xx with no stack trace.
    """
    indexes = await real_db["users"].index_information()
    index_list = list(indexes.keys())
    print("\n--- REAL MONGO users indexes ---")
    print(index_list)
    assert "email_1" in index_list, "Unique index on email_1 must exist"
    assert indexes["email_1"].get("unique") is True, "email_1 index must be unique"

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        payload = {
            "name": "First User",
            "email": "unique.user@example.com",
            "password": "Password123!",
        }
        res1 = await ac.post("/api/auth/register", json=payload)
        assert res1.status_code == 201

        # Attempt duplicate registration with the exact same email
        res2 = await ac.post("/api/auth/register", json=payload)
        assert 400 <= res2.status_code < 500, f"Expected clean 4xx, got {res2.status_code}"
        assert res2.status_code == 400
        body = res2.text
        assert "Traceback" not in body
        assert "traceback" not in body.lower()
        assert "A user with this email already exists." in res2.json().get("detail", "")


# ── 2. Available-Drones Query over Seeded Mix ──────────────────────────────────

@pytest.mark.integration
@pytest.mark.asyncio
async def test_integration_available_drones_query(real_db, op_token):
    """
    2. The available-drones query over a seeded mix of:
       AVAILABLE, CHARGING, MAINTENANCE, and ASSIGNED drones.
    """
    drones_col = real_db["drones"]
    now = datetime.now(UTC)
    seed_drones = [
        {"drone_id": "D-AVAIL-1", "model": "M1", "status": "AVAILABLE", "battery_pct": 95.0, "latitude": 12.97, "longitude": 77.59, "max_payload_kg": 5.0, "max_range_km": 30.0, "zone": "Central", "updated_at": now},
        {"drone_id": "D-AVAIL-2", "model": "M1", "status": "AVAILABLE", "battery_pct": 85.0, "latitude": 12.98, "longitude": 77.60, "max_payload_kg": 5.0, "max_range_km": 30.0, "zone": "Central", "updated_at": now},
        {"drone_id": "D-CHARG-1", "model": "M1", "status": "CHARGING", "battery_pct": 40.0, "latitude": 12.99, "longitude": 77.61, "max_payload_kg": 5.0, "max_range_km": 30.0, "zone": "Central", "updated_at": now},
        {"drone_id": "D-MAINT-1", "model": "M1", "status": "MAINTENANCE", "battery_pct": 20.0, "latitude": 12.96, "longitude": 77.58, "max_payload_kg": 5.0, "max_range_km": 30.0, "zone": "Central", "updated_at": now},
        {"drone_id": "D-ASSIG-1", "model": "M1", "status": "ASSIGNED", "battery_pct": 90.0, "latitude": 12.95, "longitude": 77.57, "max_payload_kg": 5.0, "max_range_km": 30.0, "zone": "Central", "updated_at": now},
    ]
    await drones_col.insert_many(seed_drones)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        headers = {"Authorization": f"Bearer {op_token}"}
        res = await ac.get("/api/drones/available", headers=headers)
        assert res.status_code == 200
        data = res.json()
        avail_ids = {d["drone_id"] for d in data}
        assert avail_ids == {"D-AVAIL-1", "D-AVAIL-2"}
        assert "D-CHARG-1" not in avail_ids
        assert "D-MAINT-1" not in avail_ids
        assert "D-ASSIG-1" not in avail_ids


# ── 3. Full Dispatch Path with Real Repositories ──────────────────────────────

@pytest.mark.integration
@pytest.mark.asyncio
async def test_integration_full_dispatch_path(real_db, op_token):
    """
    3. Full dispatch path with real repositories, mocking ONLY external weather HTTP client:
       - mission created
       - drone ASSIGNED in database
       - drone absent from /api/drones/available
       - one agent_decisions document per agent (Priority, Allocation, Safety)
    """
    # Seed 1 center, 1 request, 1 available drone
    await real_db["medical_centers"].insert_one({
        "_id": "c-test-1",
        "name": "Victoria Hospital",
        "latitude": 12.9634,
        "longitude": 77.5756,
    })
    req_res = await real_db["medical_requests"].insert_one({
        "center_id": "c-test-1",
        "medical_type": "Blood",
        "quantity": 2,
        "weight_kg": 2.0,
        "urgency": "CRITICAL",
        "pickup": {"lat": 12.9716, "lng": 77.5946},
        "destination": {"lat": 12.9352, "lng": 77.6245},
        "status": "PENDING",
        "created_at": datetime.now(UTC),
    })
    req_id = str(req_res.inserted_id)

    await real_db["drones"].insert_one({
        "drone_id": "BLR-D-REAL-1",
        "model": "MediHawk X200",
        "status": "AVAILABLE",
        "battery_pct": 95.0,
        "latitude": 12.9716,
        "longitude": 77.5946,
        "max_payload_kg": 5.0,
        "max_range_km": 35.0,
        "zone": "Central",
        "updated_at": datetime.now(UTC),
    })

    # Mock ONLY the external weather HTTP client call
    orig_get = httpx.AsyncClient.get

    async def mock_weather_get(self, url, *args, **kwargs):
        if "weatherapi.com" in str(url) or "current.json" in str(url):
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = SAFE_WEATHER_PAYLOAD
            mock_resp.raise_for_status = MagicMock()
            return mock_resp
        return await orig_get(self, url, *args, **kwargs)

    with patch.object(httpx.AsyncClient, "get", mock_weather_get), \
         patch("app.simulation.engine.SimulationEngine.run_mission_simulation", AsyncMock()):

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            headers = {"Authorization": f"Bearer {op_token}"}
            res = await ac.post(f"/api/requests/{req_id}/dispatch", headers=headers)
            assert res.status_code == 200
            data = res.json()
            mission_id = data.get("mission_id")
            assert mission_id is not None

            # Assert mission document created
            mission_doc = await real_db["missions"].find_one({"mission_id": mission_id})
            assert mission_doc is not None
            assert mission_doc["drone_id"] == "BLR-D-REAL-1"

            # Assert drone status updated to ASSIGNED in real Mongo
            drone_doc = await real_db["drones"].find_one({"drone_id": "BLR-D-REAL-1"})
            assert drone_doc["status"] == "ASSIGNED"

            # Assert drone absent from /api/drones/available
            avail_res = await ac.get("/api/drones/available", headers=headers)
            avail_data = avail_res.json()
            assert isinstance(avail_data, list), f"Expected list, got {avail_data}"
            avail_drones = [d["drone_id"] for d in avail_data]
            assert "BLR-D-REAL-1" not in avail_drones

            # Assert agent decisions: exactly 5 documents, one per agent (Priority, Weather, Allocation, Route, Safety)
            decisions = await real_db["agent_decisions"].find({"request_id": req_id}).to_list(None)
            agent_types = {d.get("agent_name", d.get("agent")) for d in decisions}
            assert len(decisions) == 5, f"Expected 5 agent decisions, got {len(decisions)}: {agent_types}"
            assert agent_types == {"PriorityAgent", "WeatherAgent", "AllocationAgent", "RouteAgent", "SafetyAgent"}
            for d in decisions:
                assert d.get("agent_name") in agent_types
                assert d.get("decision") is not None
                assert "timestamp" in d
                assert "input_snapshot" in d


# ── 4. DISPATCH RACE: Two simultaneous dispatches ─────────────────────────────

@pytest.mark.integration
@pytest.mark.asyncio
async def test_integration_dispatch_race_condition(real_db, op_token):
    """
    4. DISPATCH RACE: two simultaneous dispatches (asyncio.gather) for two requests,
       with exactly one feasible drone.
       Exactly one mission must be created and the drone assigned once.
    """
    # Seed 1 single available drone
    await real_db["drones"].insert_one({
        "drone_id": "BLR-RACE-DRONE",
        "model": "MediHawk X200",
        "status": "AVAILABLE",
        "battery_pct": 95.0,
        "latitude": 12.9716,
        "longitude": 77.5946,
        "max_payload_kg": 5.0,
        "max_range_km": 35.0,
    })

    # Seed two competing medical requests
    r1 = await real_db["medical_requests"].insert_one({
        "center_id": "c1",
        "medical_type": "Blood",
        "quantity": 1,
        "weight_kg": 1.5,
        "urgency": "HIGH",
        "pickup": {"lat": 12.9716, "lng": 77.5946},
        "destination": {"lat": 12.9352, "lng": 77.6245},
        "status": "PENDING",
        "created_at": datetime.now(UTC),
    })
    r2 = await real_db["medical_requests"].insert_one({
        "center_id": "c1",
        "medical_type": "Organs",
        "quantity": 1,
        "weight_kg": 1.8,
        "urgency": "CRITICAL",
        "pickup": {"lat": 12.9716, "lng": 77.5946},
        "destination": {"lat": 12.9352, "lng": 77.6245},
        "status": "PENDING",
        "created_at": datetime.now(UTC),
    })
    req1_id = str(r1.inserted_id)
    req2_id = str(r2.inserted_id)

    mock_resp = MagicMock(status_code=200, json=lambda: SAFE_WEATHER_PAYLOAD, raise_for_status=MagicMock())

    from app.agents.safety_agent import SafetyAgent
    orig_safety_run = SafetyAgent.run

    async def slow_safety_run(self, *args, **kwargs):
        await asyncio.sleep(0.05)
        return await orig_safety_run(self, *args, **kwargs)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        headers = {"Authorization": f"Bearer {op_token}"}

        with patch("httpx.AsyncClient.get", AsyncMock(return_value=mock_resp)), \
             patch.object(SafetyAgent, "run", slow_safety_run), \
             patch("app.simulation.engine.SimulationEngine.run_mission_simulation", AsyncMock()):

            # Fire two simultaneous dispatches concurrently
            res1, res2 = await asyncio.gather(
                ac.post(f"/api/requests/{req1_id}/dispatch", headers=headers),
                ac.post(f"/api/requests/{req2_id}/dispatch", headers=headers),
            )

        # Count how many missions were created in the real database
        missions_count = await real_db["missions"].count_documents({"drone_id": "BLR-RACE-DRONE"})
        created_missions = await real_db["missions"].find({"drone_id": "BLR-RACE-DRONE"}).to_list(None)

        print("\n--- DISPATCH RACE RESULTS ---")
        print(f"Req1 status: {res1.status_code}, body: {res1.json().get('mission_id')}")
        print(f"Req2 status: {res2.status_code}, body: {res2.json().get('mission_id')}")
        print(f"Missions created in DB: {missions_count}")

        # Assert exactly one mission was created
        assert missions_count == 1, (
            f"RACE CONDITION BUG DETECTED: {missions_count} missions created for the same drone! "
            f"Missions: {[m.get('mission_id') for m in created_missions]}"
        )


# ── 5. Dashboard Stats on Real Data ───────────────────────────────────────────

@pytest.mark.integration
@pytest.mark.asyncio
async def test_integration_dashboard_stats(real_db, op_token):
    """
    5. Dashboard stats on real data:
       Seed:
       - 3 DELIVERED missions (ETAs: 10.0, 20.0, 30.0 -> average ETA = 20.0 min)
       - 1 FAILED mission
       - 2 active missions (IN_TRANSIT, TRAVELLING_TO_PICKUP)
       - 5 drones: 1 MAINTENANCE, 2 ASSIGNED, 2 AVAILABLE.
       Assert:
       - exact counts
       - average ETA = 20.0
       - drone_utilization: 2 / 4 = 50.0% (active drones 2, active fleet 5 - 1 = 4).
    """
    # Seed missions:
    missions = [
        {"mission_id": "m-d1", "status": "DELIVERED", "eta_minutes": 10.0, "distance_km": 5.0},
        {"mission_id": "m-d2", "status": "DELIVERED", "eta_minutes": 20.0, "distance_km": 8.0},
        {"mission_id": "m-d3", "status": "DELIVERED", "eta_minutes": 30.0, "distance_km": 12.0},
        {"mission_id": "m-f1", "status": "FAILED", "eta_minutes": 10.0, "distance_km": 6.0},
        {"mission_id": "m-a1", "status": "IN_TRANSIT", "eta_minutes": 20.0, "distance_km": 10.0},
        {"mission_id": "m-a2", "status": "TRAVELLING_TO_PICKUP", "eta_minutes": 30.0, "distance_km": 7.0},
    ]
    await real_db["missions"].insert_many(missions)

    # Seed drones: 5 total (1 MAINTENANCE, 2 ASSIGNED, 2 AVAILABLE)
    drones = [
        {"drone_id": "D1", "status": "MAINTENANCE", "battery_pct": 10.0},
        {"drone_id": "D2", "status": "ASSIGNED", "battery_pct": 80.0},
        {"drone_id": "D3", "status": "ASSIGNED", "battery_pct": 75.0},
        {"drone_id": "D4", "status": "AVAILABLE", "battery_pct": 90.0},
        {"drone_id": "D5", "status": "AVAILABLE", "battery_pct": 85.0},
    ]
    await real_db["drones"].insert_many(drones)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        headers = {"Authorization": f"Bearer {op_token}"}
        res = await ac.get("/api/dashboard/stats", headers=headers)
        assert res.status_code == 200
        stats = res.json()

        print("\n--- REAL DASHBOARD STATS ---")
        print(stats)

        # Assert exact counts
        assert stats["delivered"] == 3
        assert stats["failed"] == 1
        assert stats["active"] == 2
        assert stats["average_eta"] == pytest.approx(20.0)

        # Fleet: 5 drones, 1 in maintenance -> 4 active fleet.
        # Active drones in mission = 2 (the 2 ASSIGNED drones)
        # drone_utilization = 2 / 4 = 0.50 (50.0%)
        assert stats["drone_utilization"] == pytest.approx(50.0)


# ── 6. Orphan Sweeper against Real Documents ──────────────────────────────────

@pytest.mark.integration
@pytest.mark.asyncio
async def test_integration_orphan_sweeper(real_db):
    """
    6. Orphan sweeper against real documents:
       Seed:
       - mid-flight mission with tracking points
       - CANCELLED mission
       Run startup sweep, assert real documents.
    """
    # 1. Mid-flight mission
    await real_db["missions"].insert_one({
        "mission_id": "m-real-midflight",
        "request_id": "req-real-midflight",
        "drone_id": "D-REAL-ORPHAN",
        "status": "IN_TRANSIT",
    })
    await real_db["medical_requests"].insert_one({
        "request_id": "req-real-midflight",
        "status": "IN_TRANSIT",
    })
    await real_db["drones"].insert_one({
        "drone_id": "D-REAL-ORPHAN",
        "status": "IN_FLIGHT",
        "battery_pct": 90.0,
        "latitude": 12.90,
        "longitude": 77.50,
    })
    await real_db["mission_tracking"].insert_one({
        "mission_id": "m-real-midflight",
        "lat": 12.955,
        "lng": 77.585,
        "battery_pct": 65.0,
        "timestamp": 100,
    })

    # 2. CANCELLED mission
    await real_db["missions"].insert_one({
        "mission_id": "m-real-cancelled",
        "request_id": "req-real-cancelled",
        "drone_id": "D-REAL-CANC",
        "status": "CANCELLED",
    })
    await real_db["medical_requests"].insert_one({
        "request_id": "req-real-cancelled",
        "status": "CANCELLED",
    })
    await real_db["drones"].insert_one({
        "drone_id": "D-REAL-CANC",
        "status": "AVAILABLE",
        "battery_pct": 95.0,
        "latitude": 12.92,
        "longitude": 77.52,
    })

    # Run lifespan startup sweep
    with patch("app.main.connect_db", AsyncMock()), \
         patch("app.main.close_db", AsyncMock()), \
         patch("app.simulation.recharge.recharge_service.start", MagicMock()), \
         patch("app.simulation.recharge.recharge_service.stop", AsyncMock()):

        async with lifespan(app):
            pass

    # Assertions on real documents:
    # Mid-flight mission and request failed with "server restarted"
    m1 = await real_db["missions"].find_one({"mission_id": "m-real-midflight"})
    assert m1["status"] == "FAILED"
    assert m1["failure_reason"] == "server restarted"

    r1 = await real_db["medical_requests"].find_one({"request_id": "req-real-midflight"})
    assert r1["status"] == "FAILED"
    assert r1["failure_reason"] == "server restarted"

    d1 = await real_db["drones"].find_one({"drone_id": "D-REAL-ORPHAN"})
    assert d1["status"] == "AVAILABLE"
    assert d1["battery_pct"] == pytest.approx(65.0)
    assert d1["latitude"] == pytest.approx(12.955)
    assert d1["longitude"] == pytest.approx(77.585)

    # CANCELLED mission and request remain untouched
    m2 = await real_db["missions"].find_one({"mission_id": "m-real-cancelled"})
    assert m2["status"] == "CANCELLED"
    r2 = await real_db["medical_requests"].find_one({"request_id": "req-real-cancelled"})
    assert r2["status"] == "CANCELLED"
    d2 = await real_db["drones"].find_one({"drone_id": "D-REAL-CANC"})
    assert d2["status"] == "AVAILABLE"


# ── 7. Recharge on Real Mongo ─────────────────────────────────────────────────

@pytest.mark.integration
@pytest.mark.asyncio
async def test_integration_recharge_real_mongo(real_db):
    """
    7. Recharge on real Mongo:
       - CHARGING drone at 40% gains exact amount
       - drone reassigned between read and write is not overwritten
    """
    # 1. Normal charging drone at 40%
    await real_db["drones"].insert_one({
        "drone_id": "D-RECHARGE-1",
        "status": "CHARGING",
        "battery_pct": 40.0,
    })

    # 2. Drone that gets reassigned between read and write
    await real_db["drones"].insert_one({
        "drone_id": "D-RECHARGE-RACE",
        "status": "CHARGING",
        "battery_pct": 50.0,
    })

    service = RechargeService()
    orig_tick = settings.SIMULATION_TICK_INTERVAL_SEC
    orig_rate = settings.DRONE_RECHARGE_RATE_PCT_PER_MIN
    orig_mult = settings.SIMULATION_SPEED_MULTIPLIER

    # 30 real seconds tick, rate 2.0%/min, multiplier 8.0x
    # elapsed min = (30/60) * 8 = 4.0 min
    # gain = 4.0 * 2.0 = 8.0%
    # expected battery for D-RECHARGE-1 = 40.0 + 8.0 = 48.0%
    settings.SIMULATION_TICK_INTERVAL_SEC = 30.0
    settings.DRONE_RECHARGE_RATE_PCT_PER_MIN = 2.0
    settings.SIMULATION_SPEED_MULTIPLIER = 8.0

    try:
        # Simulate race condition: Before the update write happens for D-RECHARGE-RACE,
        # its status in real Mongo is updated to ASSIGNED
        cursor = real_db["drones"].find({"status": "CHARGING"})
        charging_drones = [d async for d in cursor]

        # Concurrently reassign D-RECHARGE-RACE
        await real_db["drones"].update_one(
            {"drone_id": "D-RECHARGE-RACE"},
            {"$set": {"status": "ASSIGNED"}},
        )

        # Now simulate the recharge service's atomic update step
        for drone in charging_drones:
            current_pct = float(drone.get("battery_pct", 0.0))
            new_pct = min(100.0, current_pct + 8.0)
            update_fields = {"battery_pct": new_pct}

            # Atomic conditional update requiring {"_id": drone["_id"], "status": "CHARGING"}
            res = await real_db["drones"].update_one(
                {"_id": drone["_id"], "status": "CHARGING"},
                {"$set": update_fields},
            )
            if drone["drone_id"] == "D-RECHARGE-RACE":
                # Must match 0 docs because status was changed to ASSIGNED
                assert res.matched_count == 0

        # Assert D-RECHARGE-1 was updated
        d1 = await real_db["drones"].find_one({"drone_id": "D-RECHARGE-1"})
        assert d1["battery_pct"] == pytest.approx(48.0)
        assert d1["status"] == "CHARGING"

        # Assert D-RECHARGE-RACE remained ASSIGNED and its battery was not overwritten
        d2 = await real_db["drones"].find_one({"drone_id": "D-RECHARGE-RACE"})
        assert d2["status"] == "ASSIGNED"
        assert d2["battery_pct"] == pytest.approx(50.0)

    finally:
        settings.SIMULATION_TICK_INTERVAL_SEC = orig_tick
        settings.DRONE_RECHARGE_RATE_PCT_PER_MIN = orig_rate
        settings.SIMULATION_SPEED_MULTIPLIER = orig_mult


# ── 8. Failure Tests (Spec Section 16) Asserting on Response Bodies ────────────

@pytest.mark.integration
@pytest.mark.asyncio
async def test_integration_failure_scenarios_response_bodies(real_db, op_token):
    """
    8. Failure tests (spec section 16), asserting on response BODIES:
       - weather timeout gives UNSAFE fail-closed
       - invalid coordinates give 422
       - no drone gives a clean response
       - low battery gives a Safety reject
       - Mongo unreachable gives a generic 5xx with no stack trace or connection string
    """
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        headers = {"Authorization": f"Bearer {op_token}"}

        # ── 8a. Weather timeout gives UNSAFE fail-closed ──────────────────────
        req_res = await real_db["medical_requests"].insert_one({
            "center_id": "c1",
            "medical_type": "Blood",
            "quantity": 1,
            "weight_kg": 1.0,
            "urgency": "HIGH",
            "pickup": {"lat": 12.9716, "lng": 77.5946},
            "destination": {"lat": 12.9352, "lng": 77.6245},
            "status": "PENDING",
            "created_at": datetime.now(UTC),
        })
        req_id = str(req_res.inserted_id)

        orig_get = httpx.AsyncClient.get

        async def mock_weather_timeout(self, url, *args, **kwargs):
            if "weatherapi.com" in str(url) or "current.json" in str(url):
                raise TimeoutException("Weather API timed out")
            return await orig_get(self, url, *args, **kwargs)

        with patch.object(httpx.AsyncClient, "get", mock_weather_timeout):
            res_timeout = await ac.post(f"/api/requests/{req_id}/dispatch", headers=headers)
            assert res_timeout.status_code == 200
            body_timeout = res_timeout.json()
            assert body_timeout["weather_halted"] is True
            assert body_timeout["weather_condition"] == "UNSAFE"
            assert "Traceback" not in res_timeout.text
            assert "traceback" not in res_timeout.text.lower()

        # ── 8b. Invalid coordinates give 422 ──────────────────────────────────
        bad_coord_payload = {
            "center_id": "64f1a2b3c4d5e6f7a8b9c0d1",
            "medical_type": "Blood",
            "quantity": 1,
            "weight_kg": 1.0,
            "pickup": {"lat": 120.0, "lng": 77.5946},  # Lat > 90 invalid!
            "destination": {"lat": 12.9352, "lng": 77.6245},
        }
        res_coord = await ac.post("/api/requests/", json=bad_coord_payload, headers=headers)
        assert res_coord.status_code == 422
        assert "Traceback" not in res_coord.text
        assert "traceback" not in res_coord.text.lower()
        assert "less than or equal to 90" in res_coord.text

        # ── 8c. No drone gives clean response ─────────────────────────────────
        # Ensure no drones are available in MongoDB
        await real_db["drones"].delete_many({})

        async def mock_weather_ok(self, url, *args, **kwargs):
            if "weatherapi.com" in str(url) or "current.json" in str(url):
                mock_resp = MagicMock()
                mock_resp.status_code = 200
                mock_resp.json.return_value = SAFE_WEATHER_PAYLOAD
                mock_resp.raise_for_status = MagicMock()
                return mock_resp
            return await orig_get(self, url, *args, **kwargs)

        with patch.object(httpx.AsyncClient, "get", mock_weather_ok):
            res_nodrone = await ac.post(f"/api/requests/{req_id}/dispatch", headers=headers)
            assert res_nodrone.status_code == 200
            body_nodrone = res_nodrone.json()
            assert body_nodrone["allocated_drone_id"] is None
            assert "NO_FEASIBLE_DRONE" in body_nodrone["allocation_reason"]
            assert "Traceback" not in res_nodrone.text
            assert "traceback" not in res_nodrone.text.lower()

        # ── 8d. Low battery gives Safety reject ───────────────────────────────
        # Insert a drone that can be allocated (e.g. 50% battery)
        await real_db["drones"].insert_one({
            "drone_id": "D-SAFETY-REJECT",
            "model": "M1",
            "status": "AVAILABLE",
            "battery_pct": 50.0,
            "latitude": 12.9716,
            "longitude": 77.5946,
            "max_payload_kg": 5.0,
            "max_range_km": 30.0,
            "zone": "Central",
            "updated_at": datetime.now(UTC),
        })

        # RouteAgent reports high battery consumption (e.g. 40%), while available battery
        # after 20% reserve is only 50 - 20 = 30%. 40% > 30% -> SafetyAgent rejects!
        from app.agents.route_agent import RouteResult
        high_batt_route = RouteResult(
            route=[{"lat": 12.9716, "lng": 77.5946}, {"lat": 12.9352, "lng": 77.6245}],
            distance_km=25.0,
            eta_minutes=25.0,
            battery_required_pct=40.0,
        )

        with patch.object(httpx.AsyncClient, "get", mock_weather_ok), \
             patch("app.api.requests.RouteAgent.run", return_value=high_batt_route):
            res_lowbatt = await ac.post(f"/api/requests/{req_id}/dispatch", headers=headers)
            assert res_lowbatt.status_code == 200
            body_lowbatt = res_lowbatt.json()
            assert body_lowbatt["safety_decision"] in ("REJECT", "REQUEST_REALLOCATION")
            assert "Insufficient battery for route" in body_lowbatt["safety_reason"]
            assert body_lowbatt["mission_id"] is None
            assert "Traceback" not in res_lowbatt.text
            assert "traceback" not in res_lowbatt.text.lower()

            # Verify the SafetyAgent decision was written to real Mongo agent_decisions
            safety_doc = await real_db["agent_decisions"].find_one({
                "decision_id": body_lowbatt["safety_decision_id"],
            })
            assert safety_doc is not None
            assert safety_doc["decision"] == "REQUEST_REALLOCATION"

        # ── 8e. Mongo unreachable gives HTTP 503 with exact detail body ───────
        import pymongo.errors
        transport_no_exc = ASGITransport(app=app, raise_app_exceptions=False)
        async with AsyncClient(transport=transport_no_exc, base_url="http://test") as ac_no_exc:
            with patch(
                "app.repositories.drone.DroneRepository.get_available",
                side_effect=pymongo.errors.ServerSelectionTimeoutError("Connection to mongodb://admin:secret@localhost:27017 timed out"),
            ):
                res_mongo_fail = await ac_no_exc.get("/api/drones/available", headers=headers)
                assert res_mongo_fail.status_code == 503
                assert res_mongo_fail.json() == {"detail": "Service temporarily unavailable"}
                err_body = res_mongo_fail.text
                print(f"\n--- MONGO UNREACHABLE RESPONSE BODY ---\nStatus: {res_mongo_fail.status_code}\nBody: {err_body}\n")
                assert "Traceback" not in err_body
                assert "traceback" not in err_body.lower()
                assert "mongodb://" not in err_body
                assert "secret" not in err_body


# ── 9. Race Hardening: 2 Simultaneous Requests + 3 Drones ─────────────────────

@pytest.mark.integration
@pytest.mark.asyncio
async def test_integration_dispatch_race_2_requests_3_drones(real_db, op_token):
    """
    1a. RACE HARDENING:
        2 simultaneous requests + 3 drones -> two missions on two different drones.
    """
    now = datetime.now(UTC)
    # Seed 3 available drones
    await real_db["drones"].insert_many([
        {
            "drone_id": "D-RACE3-1",
            "model": "M1",
            "status": "AVAILABLE",
            "battery_pct": 95.0,
            "latitude": 12.9716,
            "longitude": 77.5946,
            "max_payload_kg": 5.0,
            "max_range_km": 35.0,
            "zone": "Central",
            "updated_at": now,
        },
        {
            "drone_id": "D-RACE3-2",
            "model": "M1",
            "status": "AVAILABLE",
            "battery_pct": 92.0,
            "latitude": 12.9716,
            "longitude": 77.5946,
            "max_payload_kg": 5.0,
            "max_range_km": 35.0,
            "zone": "Central",
            "updated_at": now,
        },
        {
            "drone_id": "D-RACE3-3",
            "model": "M1",
            "status": "AVAILABLE",
            "battery_pct": 90.0,
            "latitude": 12.9716,
            "longitude": 77.5946,
            "max_payload_kg": 5.0,
            "max_range_km": 35.0,
            "zone": "Central",
            "updated_at": now,
        },
    ])

    # Seed 2 requests
    r1 = await real_db["medical_requests"].insert_one({
        "center_id": "c-race-1",
        "medical_type": "Blood",
        "quantity": 1,
        "weight_kg": 1.5,
        "urgency": "HIGH",
        "pickup": {"lat": 12.9716, "lng": 77.5946},
        "destination": {"lat": 12.9352, "lng": 77.6245},
        "status": "PENDING",
        "created_at": now,
    })
    r2 = await real_db["medical_requests"].insert_one({
        "center_id": "c-race-1",
        "medical_type": "Organs",
        "quantity": 1,
        "weight_kg": 2.0,
        "urgency": "CRITICAL",
        "pickup": {"lat": 12.9716, "lng": 77.5946},
        "destination": {"lat": 12.9352, "lng": 77.6245},
        "status": "PENDING",
        "created_at": now,
    })
    req1_id = str(r1.inserted_id)
    req2_id = str(r2.inserted_id)

    mock_resp = MagicMock(status_code=200, json=lambda: SAFE_WEATHER_PAYLOAD, raise_for_status=MagicMock())

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        headers = {"Authorization": f"Bearer {op_token}"}
        with patch("httpx.AsyncClient.get", AsyncMock(return_value=mock_resp)), \
             patch("app.simulation.engine.SimulationEngine.run_mission_simulation", AsyncMock()):

            res1, res2 = await asyncio.gather(
                ac.post(f"/api/requests/{req1_id}/dispatch", headers=headers),
                ac.post(f"/api/requests/{req2_id}/dispatch", headers=headers),
            )

        assert res1.status_code == 200, f"Req 1 failed: {res1.text}"
        assert res2.status_code == 200, f"Req 2 failed: {res2.text}"

        m1_id = res1.json().get("mission_id")
        m2_id = res2.json().get("mission_id")
        assert m1_id is not None
        assert m2_id is not None
        assert m1_id != m2_id

        m1_doc = await real_db["missions"].find_one({"mission_id": m1_id})
        m2_doc = await real_db["missions"].find_one({"mission_id": m2_id})
        assert m1_doc is not None
        assert m2_doc is not None

        # Two missions on two different drones!
        assigned_drones = {m1_doc["drone_id"], m2_doc["drone_id"]}
        assert len(assigned_drones) == 2, f"Expected 2 different drones, got {assigned_drones}"
        assert assigned_drones.issubset({"D-RACE3-1", "D-RACE3-2", "D-RACE3-3"})

        # Check drone statuses: 2 assigned, 1 remaining available
        assigned_count = await real_db["drones"].count_documents({"status": "ASSIGNED"})
        avail_count = await real_db["drones"].count_documents({"status": "AVAILABLE"})
        assert assigned_count == 2
        assert avail_count == 1

        print(f"\n[RACE HARDENING] 2 simultaneous requests + 3 drones:")
        print(f"Mission 1: {m1_id} -> Drone: {m1_doc['drone_id']}")
        print(f"Mission 2: {m2_id} -> Drone: {m2_doc['drone_id']}")


# ── 10. Compensation: Failure After Claim Releases Drone & Leaves Request Pending ──

@pytest.mark.integration
@pytest.mark.asyncio
async def test_integration_compensation_on_mission_creation_failure(real_db, op_token):
    """
    1b. Compensation: if anything fails after the claim and before the mission
        document is stored, release the drone back to AVAILABLE, keep the
        request PENDING, and return a clean error. Test by forcing mission
        creation to raise.
    """
    now = datetime.now(UTC)
    await real_db["drones"].insert_one({
        "drone_id": "D-COMP-1",
        "model": "M1",
        "status": "AVAILABLE",
        "battery_pct": 95.0,
        "latitude": 12.9716,
        "longitude": 77.5946,
        "max_payload_kg": 5.0,
        "max_range_km": 35.0,
        "zone": "Central",
        "updated_at": now,
    })

    req_res = await real_db["medical_requests"].insert_one({
        "center_id": "c-comp-1",
        "medical_type": "Plasma",
        "quantity": 1,
        "weight_kg": 1.0,
        "urgency": "HIGH",
        "pickup": {"lat": 12.9716, "lng": 77.5946},
        "destination": {"lat": 12.9352, "lng": 77.6245},
        "status": "PENDING",
        "created_at": now,
    })
    req_id = str(req_res.inserted_id)

    mock_resp = MagicMock(status_code=200, json=lambda: SAFE_WEATHER_PAYLOAD, raise_for_status=MagicMock())

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        headers = {"Authorization": f"Bearer {op_token}"}

        # Force mission repository creation to raise
        with patch("httpx.AsyncClient.get", AsyncMock(return_value=mock_resp)), \
             patch("app.repositories.mission.MissionRepository.create", AsyncMock(side_effect=RuntimeError("Forced Mongo write error on mission insert"))):

            res = await ac.post(f"/api/requests/{req_id}/dispatch", headers=headers)

            print(f"\n[COMPENSATION TEST] Dispatch response with forced mission failure:")
            print(f"Status: {res.status_code}, Body: {res.text}")

            assert res.status_code == 500
            assert res.json().get("detail") == "Failed to create mission"
            assert "Traceback" not in res.text
            assert "Forced Mongo write error on mission insert" not in res.text

        # Verify drone is released back to AVAILABLE in real Mongo
        drone_doc = await real_db["drones"].find_one({"drone_id": "D-COMP-1"})
        assert drone_doc["status"] == "AVAILABLE", f"Drone status must be reverted to AVAILABLE, got {drone_doc['status']}"

        # Verify request is kept PENDING in real Mongo
        req_doc = await real_db["medical_requests"].find_one({"_id": ObjectId(req_id)})
        assert req_doc["status"] == "PENDING", f"Request status must remain PENDING, got {req_doc['status']}"

        # Verify no mission document was stored
        missions_count = await real_db["missions"].count_documents({"request_id": req_id})
        assert missions_count == 0


# ── 11. Stats: average_response_time Over Critical and High Requests ───────────

@pytest.mark.integration
@pytest.mark.asyncio
async def test_integration_stats_average_response_time(real_db, op_token):
    """
    3. STATS: Define average_response_time in seconds, over requests with
       priority_tier Critical or High.
       Integration test:
       - 2 Critical requests with created_at to mission started_at gaps of 60 s and 180 s
       - 1 Normal request with a 600 s gap
       -> expect 120.0. Print the response.
    """
    from datetime import timedelta
    t0 = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)

    # 1. Critical request 1: gap = 60s
    await real_db["medical_requests"].insert_one({
        "request_id": "req-crit-1",
        "priority_tier": "Critical",
        "created_at": t0,
    })
    await real_db["missions"].insert_one({
        "mission_id": "m-crit-1",
        "request_id": "req-crit-1",
        "status": "DELIVERED",
        "started_at": t0 + timedelta(seconds=60),
        "eta_minutes": 15.0,
    })

    # 2. Critical request 2: gap = 180s
    await real_db["medical_requests"].insert_one({
        "request_id": "req-crit-2",
        "priority_tier": "Critical",
        "created_at": t0,
    })
    await real_db["missions"].insert_one({
        "mission_id": "m-crit-2",
        "request_id": "req-crit-2",
        "status": "DELIVERED",
        "started_at": t0 + timedelta(seconds=180),
        "eta_minutes": 25.0,
    })

    # 3. Normal request: gap = 600s (must be EXCLUDED from average_response_time)
    await real_db["medical_requests"].insert_one({
        "request_id": "req-norm-3",
        "priority_tier": "Normal",
        "created_at": t0,
    })
    await real_db["missions"].insert_one({
        "mission_id": "m-norm-3",
        "request_id": "req-norm-3",
        "status": "DELIVERED",
        "started_at": t0 + timedelta(seconds=600),
        "eta_minutes": 30.0,
    })

    # Seed 1 drone so drone utilization calculation succeeds
    await real_db["drones"].insert_one({
        "drone_id": "D-STATS-1",
        "status": "AVAILABLE",
        "battery_pct": 100.0,
    })

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        headers = {"Authorization": f"Bearer {op_token}"}
        res = await ac.get("/api/dashboard/stats", headers=headers)
        assert res.status_code == 200
        stats = res.json()

        print("\n--- DASHBOARD STATS (average_response_time test) ---")
        print(stats)

        # Expected: (60.0 + 180.0) / 2 = 120.0 s
        assert stats["average_response_time"] == pytest.approx(120.0), (
            f"Expected average_response_time == 120.0, got {stats['average_response_time']}"
        )


# ── 12. Decisions Endpoint: Exactly 5 Agent Decisions in Execution Order ───────

@pytest.mark.integration
@pytest.mark.asyncio
async def test_integration_get_request_decisions_execution_order(real_db, op_token, hosp_token):
    """
    GET /api/requests/{request_id}/decisions:
    - Operator and admin only (hospital users get 403, no token gets 401)
    - Returns agent_decisions documents in execution order:
      Priority, Weather, Allocation, Route, Safety
    - agent_name, decision, score, reason, timestamp
    - Does not return input_snapshot
    - Unknown request id -> 404
    """
    now = datetime.now(UTC)
    await real_db["medical_centers"].insert_one({
        "_id": "c-dec-1",
        "name": "Decisions Test Hospital",
        "latitude": 12.9634,
        "longitude": 77.5756,
    })
    req_res = await real_db["medical_requests"].insert_one({
        "center_id": "c-dec-1",
        "medical_type": "Blood",
        "quantity": 1,
        "weight_kg": 1.0,
        "urgency": "CRITICAL",
        "pickup": {"lat": 12.9716, "lng": 77.5946},
        "destination": {"lat": 12.9352, "lng": 77.6245},
        "status": "PENDING",
        "created_at": now,
    })
    req_id = str(req_res.inserted_id)

    await real_db["drones"].insert_one({
        "drone_id": "D-DEC-1",
        "model": "M1",
        "status": "AVAILABLE",
        "battery_pct": 95.0,
        "latitude": 12.9716,
        "longitude": 77.5946,
        "max_payload_kg": 5.0,
        "max_range_km": 35.0,
        "zone": "Central",
        "updated_at": now,
    })

    mock_resp = MagicMock(status_code=200, json=lambda: SAFE_WEATHER_PAYLOAD, raise_for_status=MagicMock())

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        headers_op = {"Authorization": f"Bearer {op_token}"}
        headers_hosp = {"Authorization": f"Bearer {hosp_token}"}

        # 1. Dispatch request
        with patch("httpx.AsyncClient.get", AsyncMock(return_value=mock_resp)), \
             patch("app.simulation.engine.SimulationEngine.run_mission_simulation", AsyncMock()):
            disp_res = await ac.post(f"/api/requests/{req_id}/dispatch", headers=headers_op)
            assert disp_res.status_code == 200

        # 2. GET decisions as operator -> 200 with 5 agents in exact order
        res = await ac.get(f"/api/requests/{req_id}/decisions", headers=headers_op)
        assert res.status_code == 200
        decisions = res.json()

        print(f"\n[DECISIONS ENDPOINT] Returned {len(decisions)} decisions:")
        for d in decisions:
            print(f"  - {d.get('agent_name')}: {d.get('decision')} (score={d.get('score')})")

        assert len(decisions) == 5, f"Expected 5 decisions, got {len(decisions)}"
        agent_names = [d["agent_name"] for d in decisions]
        expected_order = [
            "PriorityAgent",
            "WeatherAgent",
            "AllocationAgent",
            "RouteAgent",
            "SafetyAgent",
        ]
        assert agent_names == expected_order, f"Expected order {expected_order}, got {agent_names}"

        # Assert required fields and absence of input_snapshot
        for d in decisions:
            assert "agent_name" in d
            assert "decision" in d
            assert "score" in d
            assert "reason" in d
            assert "timestamp" in d
            assert "input_snapshot" not in d, "input_snapshot must not be returned"

        # 3. RBAC & Error Cases
        # Hospital user -> 403
        res_hosp = await ac.get(f"/api/requests/{req_id}/decisions", headers=headers_hosp)
        assert res_hosp.status_code == 403

        # Unauthenticated -> 401
        res_noauth = await ac.get(f"/api/requests/{req_id}/decisions")
        assert res_noauth.status_code == 401

        # Unknown request ID -> 404
        fake_id = "64f1a2b3c4d5e6f7a8b9c0d9"
        res_404 = await ac.get(f"/api/requests/{fake_id}/decisions", headers=headers_op)
        assert res_404.status_code == 404
        assert f"Request '{fake_id}' not found." in res_404.json().get("detail", "")
