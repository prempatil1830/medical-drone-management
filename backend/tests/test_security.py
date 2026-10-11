import asyncio
from datetime import UTC, datetime
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi.testclient import TestClient
from fastapi import HTTPException

from app.main import app
from app.api.auth import get_current_user, require_role
from app.core.security import create_access_token
from app.repositories.user import get_user_repo
from app.repositories.medical_center import get_medical_center_repo
from app.repositories.medical_request import get_request_repo
from app.repositories.drone import get_drone_repo
from app.repositories.mission import get_mission_repo
from app.repositories.weather_observation import get_weather_obs_repo
from app.repositories.agent_decision import get_agent_decision_repo

FAKE_HOSP_CENTER_ID = "64f1a2b3c4d5e6f7a8b9c0d2"
FOREIGN_CENTER_ID = "64f1a2b3c4d5e6f7a8b9c0d9"
FAKE_REQ_ID = "64f1a2b3c4d5e6f7a8b9c0d3"
FAKE_MISSION_ID = "m-sec-100"
FAKE_DRONE_ID = "BLR-D001"


@pytest.fixture(autouse=True)
def mock_db_init():
    import app.db.database as db_mod
    mock_db = MagicMock()
    cols = {
        "users": MagicMock(),
        "medical_requests": MagicMock(),
        "drones": MagicMock(),
        "missions": MagicMock(),
        "medical_centers": MagicMock(),
        "weather_observations": MagicMock(),
        "agent_decisions": MagicMock(),
    }
    for c in cols.values():
        c.create_index = AsyncMock()
        c.find_one = AsyncMock(return_value=None)
        c.update_one = AsyncMock(return_value=MagicMock(matched_count=1, modified_count=1))
        c.insert_one = AsyncMock(return_value=MagicMock(inserted_id="fake_oid"))
        c.aggregate = MagicMock(return_value=MagicMock(to_list=AsyncMock(return_value=[])))
    mock_db.__getitem__.side_effect = lambda name: cols.get(name, MagicMock())
    old_db = db_mod._database
    db_mod._database = mock_db
    try:
        yield mock_db
    finally:
        db_mod._database = old_db


# ── 1. Route 401 Sweep ────────────────────────────────────────────────────────

@pytest.mark.parametrize("method,path,payload", [
    ("GET", "/api/medical-centers/", None),
    ("POST", "/api/medical-centers/", {"name": "C", "type": "hospital", "address": "A", "latitude": 12.0, "longitude": 77.0, "contact": "1"}),
    ("GET", f"/api/medical-centers/{FAKE_HOSP_CENTER_ID}", None),
    ("PUT", f"/api/medical-centers/{FAKE_HOSP_CENTER_ID}", {"name": "C"}),
    ("DELETE", f"/api/medical-centers/{FAKE_HOSP_CENTER_ID}", None),
    ("GET", "/api/requests/", None),
    ("POST", "/api/requests/", {"center_id": FAKE_HOSP_CENTER_ID, "medical_type": "Blood", "quantity": 1, "weight_kg": 1.0, "pickup": {"lat": 12.0, "lng": 77.0}, "destination": {"lat": 12.1, "lng": 77.1}}),
    ("GET", f"/api/requests/{FAKE_REQ_ID}", None),
    ("GET", f"/api/requests/{FAKE_REQ_ID}/summary", None),
    ("GET", f"/api/requests/{FAKE_REQ_ID}/decisions", None),
    ("POST", f"/api/requests/{FAKE_REQ_ID}/dispatch", None),
    ("GET", "/api/drones/", None),
    ("GET", "/api/drones/available", None),
    ("PATCH", f"/api/drones/{FAKE_DRONE_ID}/status", {"status": "AVAILABLE"}),
    ("POST", "/api/weather/predict", {"lat": 12.0, "lng": 77.0}),
    ("GET", f"/api/missions/{FAKE_MISSION_ID}", None),
    ("POST", f"/api/missions/{FAKE_MISSION_ID}/fail", {"reason": "test"}),
    ("GET", "/api/dashboard/stats", None),
    ("PATCH", "/api/users/u-123/center", {"center_id": FAKE_HOSP_CENTER_ID}),
])
def test_route_401_sweep_unauthenticated(method, path, payload):
    """
    Every protected HTTP route must reject unauthenticated requests with HTTP 401.
    """
    client = TestClient(app)
    app.dependency_overrides.clear()

    kwargs = {}
    if payload is not None:
        kwargs["json"] = payload

    res = client.request(method, path, **kwargs)
    assert res.status_code == 401, f"{method} {path} returned {res.status_code}, expected 401"
    data = res.json()
    assert "detail" in data
    assert data["detail"] in ("Not authenticated", "Could not validate credentials")


# ── 2. Public Registration Ignores Client-Supplied Role and Center ID ─────────

@pytest.mark.asyncio
async def test_public_registration_ignores_elevated_role_and_center():
    """
    Public registration creates only 'hospital' users with center_id=None.
    Client-supplied role and center_id are strictly ignored.
    """
    client = TestClient(app)
    mock_user_repo = MagicMock()
    mock_user_repo.get_by_email = AsyncMock(return_value=None)
    
    saved_user_doc = {}
    async def fake_create(doc):
        nonlocal saved_user_doc
        saved_user_doc = dict(doc)
        saved_user_doc["id"] = "new-user-123"
        saved_user_doc["created_at"] = datetime.now(UTC)
        return saved_user_doc

    mock_user_repo.create = AsyncMock(side_effect=fake_create)
    app.dependency_overrides[get_user_repo] = lambda: mock_user_repo

    try:
        payload = {
            "name": "Attacker",
            "email": "attacker@example.com",
            "password": "SecurePassword123!",
            "role": "admin",
            "center_id": "malicious_center_999",
        }
        res = client.post("/api/auth/register", json=payload)
        assert res.status_code == 201
        data = res.json()

        # Outbound response check
        assert data["role"] == "hospital"
        assert data["center_id"] is None
        assert data["email"] == "attacker@example.com"
        assert "password" not in data
        assert "password_hash" not in data

        # Internal document storage check
        assert saved_user_doc["role"] == "hospital"
        assert saved_user_doc["center_id"] is None
    finally:
        app.dependency_overrides.clear()


# ── 3. No-Center Hospital User Gets 403 ───────────────────────────────────────

def test_no_center_hospital_user_gets_403_on_all_request_and_mission_endpoints():
    """
    A hospital user with center_id=None must receive 403 Forbidden on:
    - GET /api/requests/
    - GET /api/requests/{id}
    - POST /api/requests/
    - GET /api/missions/{id}
    """
    client = TestClient(app)
    mock_user = {
        "id": "u-no-center",
        "name": "Unassigned Hospital User",
        "email": "unassigned@hospital.test",
        "role": "hospital",
        "center_id": None,
    }
    app.dependency_overrides[get_current_user] = lambda: mock_user

    mock_req_repo = MagicMock()
    mock_req_repo.get_by_id = AsyncMock(return_value={"id": FAKE_REQ_ID, "center_id": FAKE_HOSP_CENTER_ID})
    mock_req_repo.list_requests = AsyncMock(return_value=[])
    mock_req_repo.create = AsyncMock(return_value={"id": FAKE_REQ_ID, "center_id": FAKE_HOSP_CENTER_ID})
    app.dependency_overrides[get_request_repo] = lambda: mock_req_repo

    mock_mission_repo = MagicMock()
    mock_mission_repo.get_by_id = AsyncMock(return_value={"id": FAKE_MISSION_ID, "request_id": FAKE_REQ_ID})
    app.dependency_overrides[get_mission_repo] = lambda: mock_mission_repo

    try:
        # GET /api/requests/
        res_list = client.get("/api/requests/")
        assert res_list.status_code == 403
        assert res_list.json()["detail"] == "Hospital user has no medical center assigned."

        # GET /api/requests/{id}
        res_get = client.get(f"/api/requests/{FAKE_REQ_ID}")
        assert res_get.status_code == 403
        assert res_get.json()["detail"] == "Hospital user has no medical center assigned."

        # POST /api/requests/
        create_payload = {
            "center_id": FAKE_HOSP_CENTER_ID,
            "medical_type": "Blood",
            "quantity": 1,
            "weight_kg": 1.0,
            "pickup": {"lat": 12.0, "lng": 77.0},
            "destination": {"lat": 12.1, "lng": 77.1},
        }
        res_create = client.post("/api/requests/", json=create_payload)
        assert res_create.status_code == 403
        assert res_create.json()["detail"] == "Hospital user has no medical center assigned."

        # GET /api/missions/{id}
        res_m = client.get(f"/api/missions/{FAKE_MISSION_ID}")
        assert res_m.status_code == 403
        assert res_m.json()["detail"] == "Hospital user has no medical center assigned."
    finally:
        app.dependency_overrides.clear()


# ── 4. Cross-Center Isolation ─────────────────────────────────────────────────

def test_hospital_cross_center_isolation():
    """
    Hospital user scoped to center A:
    - Attempting to access center B's request -> 404 (hidden for tenant isolation)
    - Attempting to access center B's mission -> 404
    - Attempting to dispatch a request -> 403 Forbidden (hospital denied dispatch)
    """
    client = TestClient(app)
    mock_user = {
        "id": "u-center-a",
        "name": "Hospital User A",
        "email": "usera@hospital.test",
        "role": "hospital",
        "center_id": FAKE_HOSP_CENTER_ID,
    }
    app.dependency_overrides[get_current_user] = lambda: mock_user

    foreign_req_doc = {
        "id": FAKE_REQ_ID,
        "request_id": "req-foreign-1",
        "center_id": FOREIGN_CENTER_ID,
        "medical_type": "Blood",
        "quantity": 1,
        "weight_kg": 1.0,
        "urgency": "HIGH",
        "pickup": {"lat": 12.0, "lng": 77.0},
        "destination": {"lat": 12.1, "lng": 77.1},
        "status": "PENDING",
        "created_at": datetime.now(UTC),
    }
    mock_req_repo = MagicMock()
    mock_req_repo.get_by_id = AsyncMock(return_value=foreign_req_doc)
    app.dependency_overrides[get_request_repo] = lambda: mock_req_repo

    foreign_mission_doc = {
        "id": FAKE_MISSION_ID,
        "mission_id": FAKE_MISSION_ID,
        "request_id": FAKE_REQ_ID,
        "drone_id": FAKE_DRONE_ID,
        "route": [],
        "distance_km": 5.0,
        "eta_minutes": 10.0,
        "battery_required_pct": 20.0,
        "status": "ASSIGNED",
        "started_at": datetime.now(UTC),
    }
    mock_mission_repo = MagicMock()
    mock_mission_repo.get_by_id = AsyncMock(return_value=foreign_mission_doc)
    app.dependency_overrides[get_mission_repo] = lambda: mock_mission_repo

    try:
        # GET foreign request -> 404
        res_r = client.get(f"/api/requests/{FAKE_REQ_ID}")
        assert res_r.status_code == 404
        assert res_r.json()["detail"] == f"Request '{FAKE_REQ_ID}' not found."

        # GET foreign mission -> 404
        res_m = client.get(f"/api/missions/{FAKE_MISSION_ID}")
        assert res_m.status_code == 404
        assert res_m.json()["detail"] == f"Mission '{FAKE_MISSION_ID}' not found."

        # POST dispatch foreign or own request -> 403 Forbidden
        res_d = client.post(f"/api/requests/{FAKE_REQ_ID}/dispatch")
        assert res_d.status_code == 403
    finally:
        app.dependency_overrides.clear()


# ── 5. require_role Denies None or Missing Role ────────────────────────────────

@pytest.mark.asyncio
async def test_require_role_denies_none_or_missing_role():
    """
    require_role dependency factory fail-closed behavior:
    Denies (403) whenever the user document lacks a role or role is None.
    """
    checker = require_role("operator", "admin")

    # 1. Missing role key
    with pytest.raises(HTTPException) as exc_info1:
        await checker({"id": "u-norole"})
    assert exc_info1.value.status_code == 403
    assert "Access denied" in exc_info1.value.detail

    # 2. None role
    with pytest.raises(HTTPException) as exc_info2:
        await checker({"id": "u-none", "role": None})
    assert exc_info2.value.status_code == 403
    assert "Access denied" in exc_info2.value.detail

    # 3. Empty string role
    with pytest.raises(HTTPException) as exc_info3:
        await checker({"id": "u-empty", "role": ""})
    assert exc_info3.value.status_code == 403


# ── 6. Route x Role Matrix ────────────────────────────────────────────────────

@pytest.mark.parametrize("route_desc,method,path,payload,allowed_roles", [
    ("create_request", "POST", "/api/requests/", {"center_id": FAKE_HOSP_CENTER_ID, "medical_type": "Blood", "quantity": 1, "weight_kg": 1.0, "pickup": {"lat": 12.0, "lng": 77.0}, "destination": {"lat": 12.1, "lng": 77.1}}, ["hospital", "operator", "admin"]),
    ("list_requests", "GET", "/api/requests/", None, ["hospital", "operator", "admin"]),
    ("get_request_summary", "GET", f"/api/requests/{FAKE_REQ_ID}/summary", None, ["operator", "admin"]),
    ("get_request_decisions", "GET", f"/api/requests/{FAKE_REQ_ID}/decisions", None, ["operator", "admin"]),
    ("dispatch_request", "POST", f"/api/requests/{FAKE_REQ_ID}/dispatch", None, ["operator", "admin"]),
    ("list_drones", "GET", "/api/drones/", None, ["operator", "admin"]),
    ("list_available_drones", "GET", "/api/drones/available", None, ["operator", "admin"]),
    ("patch_drone_status", "PATCH", f"/api/drones/{FAKE_DRONE_ID}/status", {"status": "AVAILABLE"}, ["admin"]),
    ("predict_weather", "POST", "/api/weather/predict", {"lat": 12.0, "lng": 77.0}, ["operator", "admin"]),
    ("get_mission", "GET", f"/api/missions/{FAKE_MISSION_ID}", None, ["hospital", "operator", "admin"]),
    ("fail_mission", "POST", f"/api/missions/{FAKE_MISSION_ID}/fail", {"reason": "test"}, ["operator", "admin"]),
    ("dashboard_stats", "GET", "/api/dashboard/stats", None, ["operator", "admin"]),
    ("update_user_center", "PATCH", "/api/users/u-target/center", {"center_id": FAKE_HOSP_CENTER_ID}, ["admin"]),
    ("create_center", "POST", "/api/medical-centers/", {"name": "C", "type": "hospital", "address": "A", "latitude": 12.0, "longitude": 77.0, "contact": "1"}, ["admin"]),
    ("update_center", "PUT", f"/api/medical-centers/{FAKE_HOSP_CENTER_ID}", {"name": "Updated"}, ["admin"]),
    ("delete_center", "DELETE", f"/api/medical-centers/{FAKE_HOSP_CENTER_ID}", None, ["admin"]),
])
def test_route_x_role_table(route_desc, method, path, payload, allowed_roles):
    """
    Asserted route x role authorization matrix for all roles: hospital, operator, admin.
    """
    client = TestClient(app)

    # Setup mock repos
    mock_center_repo = MagicMock()
    valid_center = {
        "id": FAKE_HOSP_CENTER_ID,
        "name": "City General Hospital",
        "type": "hospital",
        "address": "MG Road, Bengaluru",
        "latitude": 12.0,
        "longitude": 77.0,
        "contact": "+91-80-12345678",
    }
    mock_center_repo.get_by_id = AsyncMock(return_value=valid_center)
    mock_center_repo.create = AsyncMock(return_value=valid_center)
    mock_center_repo.update = AsyncMock(return_value=valid_center)
    mock_center_repo.delete = AsyncMock(return_value=True)

    mock_req_repo = MagicMock()
    req_doc = {
        "id": FAKE_REQ_ID,
        "request_id": "req-1",
        "center_id": FAKE_HOSP_CENTER_ID,
        "medical_type": "Blood",
        "quantity": 1,
        "weight_kg": 1.0,
        "urgency": "HIGH",
        "pickup": {"lat": 12.0, "lng": 77.0},
        "destination": {"lat": 12.1, "lng": 77.1},
        "status": "PENDING",
        "dispatch_summary": {
            "text": "Medical request summary for testing.",
            "source": "template",
            "generated_at": datetime.now(UTC),
        },
        "created_at": datetime.now(UTC),
    }
    mock_req_repo.get_by_id = AsyncMock(return_value=req_doc)
    mock_req_repo.list_requests = AsyncMock(return_value=[req_doc])
    mock_req_repo.create = AsyncMock(return_value=req_doc)
    mock_req_repo.update_status = AsyncMock(return_value=True)

    mock_drone_repo = MagicMock()
    drone_doc = {
        "id": "d-1",
        "drone_id": FAKE_DRONE_ID,
        "model": "M",
        "battery_pct": 90.0,
        "max_payload_kg": 5.0,
        "max_range_km": 25.0,
        "latitude": 12.0,
        "longitude": 77.0,
        "status": "MAINTENANCE",
        "zone": "Z",
        "updated_at": datetime.now(UTC),
    }
    mock_drone_repo.get_all = AsyncMock(return_value=[drone_doc])
    mock_drone_repo.get_available = AsyncMock(return_value=[drone_doc])
    mock_drone_repo.get_by_drone_id = AsyncMock(return_value=drone_doc)
    mock_drone_repo.update_status = AsyncMock(return_value=True)

    mock_mission_repo = MagicMock()
    mission_doc = {
        "id": FAKE_MISSION_ID,
        "mission_id": FAKE_MISSION_ID,
        "request_id": FAKE_REQ_ID,
        "drone_id": FAKE_DRONE_ID,
        "route": [],
        "distance_km": 5.0,
        "eta_minutes": 10.0,
        "battery_required_pct": 20.0,
        "status": "ASSIGNED",
        "started_at": datetime.now(UTC),
    }
    mock_mission_repo.get_by_id = AsyncMock(return_value=mission_doc)

    mock_user_repo = MagicMock()
    mock_user_repo.update_center = AsyncMock(return_value={
        "id": "u-target", "name": "Target", "email": "target@test.com", "role": "hospital", "center_id": FAKE_HOSP_CENTER_ID, "created_at": datetime.now(UTC)
    })

    mock_decision_repo = MagicMock()
    mock_decision_repo.list_by_request = AsyncMock(return_value=[])

    app.dependency_overrides[get_medical_center_repo] = lambda: mock_center_repo
    app.dependency_overrides[get_request_repo] = lambda: mock_req_repo
    app.dependency_overrides[get_drone_repo] = lambda: mock_drone_repo
    app.dependency_overrides[get_mission_repo] = lambda: mock_mission_repo
    app.dependency_overrides[get_user_repo] = lambda: mock_user_repo
    app.dependency_overrides[get_agent_decision_repo] = lambda: mock_decision_repo

    roles = ["hospital", "operator", "admin"]
    kwargs = {}
    if payload is not None:
        kwargs["json"] = payload

    try:
        for r in roles:
            app.dependency_overrides[get_current_user] = lambda r=r: {
                "id": f"u-{r}",
                "name": f"User {r}",
                "email": f"{r}@test.com",
                "role": r,
                "center_id": FAKE_HOSP_CENTER_ID,
            }
            res = client.request(method, path, **kwargs)
            if r in allowed_roles:
                # Allowed role must NOT receive 401 or 403
                assert res.status_code not in (401, 403), f"{route_desc} unexpectedly gave {res.status_code} for role {r}"
            else:
                # Forbidden role MUST receive 403
                assert res.status_code == 403, f"{route_desc} expected 403 for role {r}, got {res.status_code}"
    finally:
        app.dependency_overrides.clear()


# ── 7. WebSocket Security Scenarios ───────────────────────────────────────────

def test_websocket_security_scenarios():
    """
    WebSocket /ws/missions/{mission_id} security verification:
    - Missing token -> closed with code 1008
    - Invalid/tampered token -> closed with code 1008
    - Foreign hospital user -> closed with code 1008
    - Owner hospital user -> connected
    - Operator -> connected
    """
    client = TestClient(app)

    mock_mission_repo = MagicMock()
    mock_mission = {
        "id": FAKE_MISSION_ID,
        "mission_id": FAKE_MISSION_ID,
        "request_id": FAKE_REQ_ID,
        "drone_id": FAKE_DRONE_ID,
    }
    mock_mission_repo.get_by_id = AsyncMock(return_value=mock_mission)

    mock_req_repo = MagicMock()
    mock_req = {"id": FAKE_REQ_ID, "center_id": FAKE_HOSP_CENTER_ID}
    mock_req_repo.get_by_id = AsyncMock(return_value=mock_req)

    mock_user_repo = MagicMock()
    def get_user_by_id(uid):
        if uid == "u-owner":
            return {"id": uid, "role": "hospital", "center_id": FAKE_HOSP_CENTER_ID}
        if uid == "u-foreign":
            return {"id": uid, "role": "hospital", "center_id": FOREIGN_CENTER_ID}
        if uid == "u-operator":
            return {"id": uid, "role": "operator"}
        return None
    mock_user_repo.get_by_id = AsyncMock(side_effect=get_user_by_id)

    app.dependency_overrides[get_mission_repo] = lambda: mock_mission_repo
    app.dependency_overrides[get_request_repo] = lambda: mock_req_repo
    app.dependency_overrides[get_user_repo] = lambda: mock_user_repo

    try:
        # 1. No token -> rejected
        with pytest.raises(Exception):
            with client.websocket_connect(f"/ws/missions/{FAKE_MISSION_ID}"):
                pass

        # 2. Invalid token -> rejected
        with pytest.raises(Exception):
            with client.websocket_connect(f"/ws/missions/{FAKE_MISSION_ID}?token=invalid.jwt.token"):
                pass

        # 3. Foreign hospital user -> rejected
        token_foreign = create_access_token({"sub": "u-foreign", "role": "hospital"})
        with pytest.raises(Exception):
            with client.websocket_connect(f"/ws/missions/{FAKE_MISSION_ID}?token={token_foreign}"):
                pass

        # 4. Owner hospital user -> connected
        token_owner = create_access_token({"sub": "u-owner", "role": "hospital"})
        with client.websocket_connect(f"/ws/missions/{FAKE_MISSION_ID}?token={token_owner}") as ws:
            assert ws is not None

        # 5. Operator -> connected
        token_op = create_access_token({"sub": "u-operator", "role": "operator"})
        with client.websocket_connect(f"/ws/missions/{FAKE_MISSION_ID}?token={token_op}") as ws:
            assert ws is not None
    finally:
        app.dependency_overrides.clear()


# ── 8. Seed Users and Migrate Roles Dry-Run Behavior ──────────────────────────

@pytest.mark.asyncio
async def test_migrate_roles_dry_run_and_apply():
    """
    Test migrate_roles script logic for dry-run and apply modes.
    """
    from scripts.migrate_roles import run_migration

    legacy_users = [
        {"_id": "u-leg-1", "email": "ha@test.com", "role": "hospital_admin", "center_id": "c1"},
        {"_id": "u-leg-2", "email": "sa_allowed@test.com", "role": "system_admin", "center_id": None},
        {"_id": "u-leg-3", "email": "sa_denied@test.com", "role": "system_admin", "center_id": None},
    ]

    mock_col = MagicMock()
    cursor = MagicMock()
    cursor.to_list = AsyncMock(return_value=legacy_users)
    mock_col.find = MagicMock(return_value=cursor)
    mock_col.update_one = AsyncMock()

    mock_db = MagicMock()
    mock_db.__getitem__.side_effect = lambda name: mock_col if name == "users" else AsyncMock()

    with patch("scripts.migrate_roles.connect_db", AsyncMock()), \
         patch("scripts.migrate_roles.close_db", AsyncMock()), \
         patch("scripts.migrate_roles.get_database", return_value=mock_db):

        # Dry-run: should not update MongoDB
        await run_migration(apply=False, allow_admin=["sa_allowed@test.com"])
        assert mock_col.update_one.call_count == 0

        # Apply mode: updates hospital_admin and allowed system_admin
        await run_migration(apply=True, allow_admin=["sa_allowed@test.com"])
        assert mock_col.update_one.call_count == 2
        calls = mock_col.update_one.call_args_list
        assert calls[0][0][1]["$set"]["role"] == "hospital"
        assert calls[1][0][1]["$set"]["role"] == "admin"


@pytest.mark.asyncio
async def test_seed_users():
    """
    Test scripts/seed_users.py:
    - Rejects invalid roles with ValueError
    - Creates new user when user does not exist
    - Updates existing user when user exists
    """
    from scripts.seed_users import seed_user

    # 1. Reject invalid role
    with pytest.raises(ValueError) as exc:
        await seed_user("bad@example.com", "pass1234", "Bad User", "invalid_role")
    assert "Invalid role" in str(exc.value)

    # 2. Create new user
    mock_db = MagicMock()
    mock_users_col = AsyncMock()
    mock_db.__getitem__.side_effect = lambda name: mock_users_col if name == "users" else AsyncMock()

    with patch("scripts.seed_users.connect_db", AsyncMock()), \
         patch("scripts.seed_users.close_db", AsyncMock()), \
         patch("scripts.seed_users.get_database", return_value=mock_db), \
         patch("scripts.seed_users.UserRepository") as mock_user_repo_cls:

        mock_repo = MagicMock()
        mock_repo.ensure_indexes = AsyncMock()
        mock_repo.get_by_email = AsyncMock(return_value=None)
        mock_repo.create = AsyncMock(return_value={"id": "u-seeded-1", "role": "admin"})
        mock_user_repo_cls.return_value = mock_repo

        created = await seed_user("admin@example.com", "AdminPass123!", "Admin User", "admin")
        assert created["id"] == "u-seeded-1"
        assert created["role"] == "admin"
        mock_repo.create.assert_called_once()
        create_payload = mock_repo.create.call_args[0][0]
        assert create_payload["email"] == "admin@example.com"
        assert create_payload["role"] == "admin"
        assert "password_hash" in create_payload

        # 3. Update existing user
        mock_repo.get_by_email = AsyncMock(return_value={"_id": "u-existing-1", "email": "op@example.com"})
        mock_repo._col = AsyncMock()
        mock_repo._col.update_one = AsyncMock()

        updated = await seed_user("op@example.com", "NewOpPass123!", "Op User", "operator")
        assert updated["_id"] == "u-existing-1"
        mock_repo._col.update_one.assert_called_once()
        update_doc = mock_repo._col.update_one.call_args[0][1]["$set"]
        assert update_doc["role"] == "operator"
        assert update_doc["name"] == "Op User"
        assert "password_hash" in update_doc


# ── 9. Dashboard Stats Exact Numbers ──────────────────────────────────────────

def test_dashboard_stats_exact_numbers():
    """
    Test GET /api/dashboard/stats computes exact aggregation values.
    """
    client = TestClient(app)
    app.dependency_overrides[get_current_user] = lambda: {"id": "u-op", "role": "operator"}

    mock_db = MagicMock()
    missions_res = [{
        "status_counts": [
            {"_id": "DELIVERED", "count": 10},
            {"_id": "FAILED", "count": 2},
            {"_id": "IN_TRANSIT", "count": 3},
            {"_id": "ASSIGNED", "count": 1},
        ],
        "avg_eta": [{"avg_eta": 14.5}],
        "response_time": [{"avg_response_time": 42.0}],
    }]

    drones_res = [{
        "operational": [{"count": 20}],
        "busy": [{"count": 4}],
    }]

    missions_col = MagicMock()
    m_cursor = MagicMock()
    m_cursor.to_list = AsyncMock(return_value=missions_res)
    missions_col.aggregate = MagicMock(return_value=m_cursor)

    drones_col = MagicMock()
    d_cursor = MagicMock()
    d_cursor.to_list = AsyncMock(return_value=drones_res)
    drones_col.aggregate = MagicMock(return_value=d_cursor)

    mock_db.__getitem__.side_effect = lambda name: {
        "missions": missions_col,
        "drones": drones_col,
    }[name]

    from app.db.database import get_database
    app.dependency_overrides[get_database] = lambda: mock_db

    res = client.get("/api/dashboard/stats")
    assert res.status_code == 200
    data = res.json()

    assert data["delivered"] == 10
    assert data["failed"] == 2
    assert data["active"] == 4  # IN_TRANSIT (3) + ASSIGNED (1)
    assert data["average_eta"] == pytest.approx(14.5)
    assert data["average_response_time"] == pytest.approx(42.0)
    # Utilization: (4 busy / 20 operational) * 100 = 20.0%
    assert data["drone_utilization"] == pytest.approx(20.0)

    app.dependency_overrides.clear()
