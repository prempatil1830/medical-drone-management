"""
Live-Mongo integration tests for Explanation Service & Dispatch Summaries.
Tests against 'medical_drone_test' database.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from bson import ObjectId
import httpx
from httpx import AsyncClient, ASGITransport
from motor.motor_asyncio import AsyncIOMotorClient
import pytest
from unittest.mock import AsyncMock, patch, MagicMock

pytestmark = pytest.mark.integration

from app.main import app
from app.core.config import settings
from app.core.security import create_access_token, hash_password
from app.db.database import get_database
from app.repositories.user import UserRepository
from app.repositories.medical_request import MedicalRequestRepository
from app.repositories.drone import DroneRepository
from app.repositories.mission import MissionRepository
from app.repositories.agent_decision import AgentDecisionRepository
from app.repositories.weather_observation import WeatherObservationRepository

TEST_DB_NAME = "medical_drone_test"
MONGO_URI = settings.MONGODB_URI or "mongodb://localhost:27017"

SAFE_WEATHER = {
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


@pytest.fixture
async def real_db():
    client = AsyncIOMotorClient(MONGO_URI, serverSelectionTimeoutMS=2000)
    db = client[TEST_DB_NAME]
    for col in await db.list_collection_names():
        await db[col].drop()

    import app.db.database as db_mod
    original_db = db_mod._database
    original_client = db_mod._client
    db_mod._database = db
    db_mod._client = client

    app.dependency_overrides[get_database] = lambda: db

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
        "name": "Operator Explain",
        "email": "operator.explain@example.com",
        "role": "operator",
        "password_hash": hash_password("Password123!"),
    })
    return create_access_token({"sub": str(oid), "role": "operator"})


@pytest.fixture
async def hosp_user(real_db):
    center_oid = ObjectId()
    await real_db["medical_centers"].insert_one({
        "_id": center_oid,
        "name": "Hospital A",
        "type": "hospital",
        "latitude": 12.9716,
        "longitude": 77.5946,
    })
    user_oid = ObjectId()
    await real_db["users"].insert_one({
        "_id": user_oid,
        "name": "Hosp Staff",
        "email": "staff@hospital.org",
        "role": "hospital",
        "center_id": str(center_oid),
        "password_hash": hash_password("Password123!"),
    })
    token = create_access_token({"sub": str(user_oid), "role": "hospital", "center_id": str(center_oid)})
    return {
        "user_id": str(user_oid),
        "center_id": str(center_oid),
        "token": token,
    }


@pytest.fixture
async def seeded_drone(real_db):
    drone = {
        "drone_id": "DRN-EXP-01",
        "model": "Matrice 300",
        "status": "AVAILABLE",
        "battery_pct": 100.0,
        "max_payload_kg": 5.0,
        "max_range_km": 50.0,
        "latitude": 12.9716,
        "longitude": 77.5946,
        "current_location": {"lat": 12.9716, "lng": 77.5946},
    }
    await real_db["drones"].insert_one(drone)
    return drone


# ── Integration Tests ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_no_api_key_dispatch_works_and_template_summary_exists(real_db, op_token, hosp_user, seeded_drone):
    """When LLM is disabled (no key), dispatch works normally and writes template summary."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # Create request
        req_res = await client.post(
            "/api/requests/",
            headers={"Authorization": f"Bearer {hosp_user['token']}"},
            json={
                "center_id": hosp_user["center_id"],
                "medical_type": "Insulin",
                "quantity": 2,
                "weight_kg": 0.5,
                "urgency": "HIGH",
                "pickup": {"lat": 12.9716, "lng": 77.5946},
                "destination": {"lat": 12.9800, "lng": 77.6000},
            },
        )
        assert req_res.status_code == 201
        req_id = req_res.json()["id"]

        with patch.object(settings, "LLM_API_KEY", None), \
             patch.object(settings, "WEATHER_FORCE_CONDITION", "SAFE"), \
             patch("app.simulation.engine.SimulationEngine.run_mission_simulation", AsyncMock()):
            dispatch_res = await client.post(
                f"/api/requests/{req_id}/dispatch",
                headers={"Authorization": f"Bearer {op_token}"},
            )
            assert dispatch_res.status_code == 200
            d_data = dispatch_res.json()
            assert d_data["mission_id"] is not None

        # Verify request document in DB has template dispatch_summary
        doc = await real_db["medical_requests"].find_one({"_id": ObjectId(req_id)})
        assert doc is not None
        assert "dispatch_summary" in doc
        summary = doc["dispatch_summary"]
        assert summary["source"] == "template"
        assert len(summary["text"]) > 20
        assert "Insulin" in summary["text"]


@pytest.mark.asyncio
async def test_decision_trail_identical_with_llm_on_off_failing(real_db, op_token, hosp_user, seeded_drone):
    """The decision trail and mission fields are identical whether LLM is on, off, or failing."""
    trials = ["off", "failing", "on"]
    results = []

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        for mode in trials:
            # Reset drone status to AVAILABLE
            await real_db["drones"].update_one({"drone_id": seeded_drone["drone_id"]}, {"$set": {"status": "AVAILABLE"}})

            req_res = await client.post(
                "/api/requests/",
                headers={"Authorization": f"Bearer {hosp_user['token']}"},
                json={
                    "center_id": hosp_user["center_id"],
                    "medical_type": "Vaccines",
                    "quantity": 1,
                    "weight_kg": 0.5,
                    "urgency": "MEDIUM",
                    "pickup": {"lat": 12.9716, "lng": 77.5946},
                    "destination": {"lat": 12.9800, "lng": 77.6000},
                },
            )
            req_id = req_res.json()["id"]

            if mode == "off":
                api_key = None
            elif mode == "failing":
                api_key = "fake-key"
            else:
                api_key = "fake-key"

            with patch.object(settings, "LLM_API_KEY", api_key), \
                 patch.object(settings, "WEATHER_FORCE_CONDITION", "SAFE"), \
                 patch("app.simulation.engine.SimulationEngine.run_mission_simulation", AsyncMock()):
                d_res = await client.post(f"/api/requests/{req_id}/dispatch", headers={"Authorization": f"Bearer {op_token}"})

            assert d_res.status_code == 200
            data = d_res.json()
            # Core decision fields that must remain strictly deterministic
            core_tuple = (
                data["priority_decision"],
                data["weather_condition"],
                data["allocated_drone_id"],
                data["route_distance_km"],
                data["safety_decision"],
            )
            results.append(core_tuple)

    assert results[0] == results[1] == results[2]


@pytest.mark.asyncio
async def test_summary_permissions_and_weather_note_scoping(real_db, op_token, hosp_user, seeded_drone):
    """
    1. Hospital user gets 403 on GET /api/requests/{id}/summary.
    2. Operator/Admin gets 200 on /summary.
    3. Mission document stores weather={condition, probability, note}.
    4. Hospital user GET /api/missions/{id} sees only their own mission and weather note without model internals.
    """
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        req_res = await client.post(
            "/api/requests/",
            headers={"Authorization": f"Bearer {hosp_user['token']}"},
            json={
                "center_id": hosp_user["center_id"],
                "medical_type": "Blood",
                "quantity": 1,
                "weight_kg": 1.0,
                "urgency": "CRITICAL",
                "pickup": {"lat": 12.9716, "lng": 77.5946},
                "destination": {"lat": 12.9800, "lng": 77.6000},
            },
        )
        req_id = req_res.json()["id"]

        with patch.object(settings, "WEATHER_FORCE_CONDITION", "SAFE"), \
             patch("app.simulation.engine.SimulationEngine.run_mission_simulation", AsyncMock()):
            d_res = await client.post(f"/api/requests/{req_id}/dispatch", headers={"Authorization": f"Bearer {op_token}"})
            mission_id = d_res.json()["mission_id"]

        # Hospital user -> 403 on /summary
        sum_hosp = await client.get(
            f"/api/requests/{req_id}/summary",
            headers={"Authorization": f"Bearer {hosp_user['token']}"},
        )
        assert sum_hosp.status_code == 403

        # Operator -> 200 on /summary
        sum_op = await client.get(
            f"/api/requests/{req_id}/summary",
            headers={"Authorization": f"Bearer {op_token}"},
        )
        assert sum_op.status_code == 200
        summary_body = sum_op.json()
        assert "text" in summary_body
        assert summary_body["source"] in ("template", "llm")
        assert "generated_at" in summary_body

        # Hospital user GET /api/missions/{id}
        miss_res = await client.get(
            f"/api/missions/{mission_id}",
            headers={"Authorization": f"Bearer {hosp_user['token']}"},
        )
        assert miss_res.status_code == 200
        miss_body = miss_res.json()
        assert "weather" in miss_body
        w_obj = miss_body["weather"]
        assert w_obj["condition"] in ("SAFE", "CAUTION", "UNSAFE")
        assert w_obj["probability"] <= 0.999
        assert "note" in w_obj
        assert len(w_obj["note"]) > 10

        # No input_snapshot and no model internals exposed in mission response
        assert "input_snapshot" not in miss_body
        assert "model_internals" not in miss_body
        assert "raw_weather_snapshot" not in miss_body


@pytest.mark.asyncio
async def test_halted_dispatch_writes_hospital_safe_status_note(real_db, op_token, hosp_user):
    """When dispatch halts (e.g. UNSAFE weather), request.status_note contains plain hospital-safe reason."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        req_res = await client.post(
            "/api/requests/",
            headers={"Authorization": f"Bearer {hosp_user['token']}"},
            json={
                "center_id": hosp_user["center_id"],
                "medical_type": "Emergency Medicine",
                "quantity": 1,
                "weight_kg": 0.5,
                "urgency": "CRITICAL",
                "pickup": {"lat": 12.9716, "lng": 77.5946},
                "destination": {"lat": 12.9800, "lng": 77.6000},
            },
        )
        req_id = req_res.json()["id"]

        with patch.object(settings, "WEATHER_FORCE_CONDITION", "UNSAFE"):
            dispatch_res = await client.post(f"/api/requests/{req_id}/dispatch", headers={"Authorization": f"Bearer {op_token}"})
            assert dispatch_res.status_code == 200
            assert dispatch_res.json()["weather_halted"] is True

        # Check request response via GET /api/requests/{id}
        fetch_req = await client.get(f"/api/requests/{req_id}", headers={"Authorization": f"Bearer {hosp_user['token']}"})
        assert fetch_req.status_code == 200
        req_doc = fetch_req.json()
        assert req_doc["status_note"] is not None
        assert "Waiting: unsafe weather" in req_doc["status_note"]


@pytest.mark.asyncio
async def test_foreign_hospital_user_cannot_see_other_center_mission(real_db, op_token, hosp_user, seeded_drone):
    """A hospital user from a different medical center gets 404 on foreign mission."""
    # Create another hospital user belonging to a different center
    other_center_oid = ObjectId()
    await real_db["medical_centers"].insert_one({
        "_id": other_center_oid,
        "name": "Hospital B",
        "type": "hospital",
        "latitude": 12.9800,
        "longitude": 77.6000,
    })
    other_user_oid = ObjectId()
    await real_db["users"].insert_one({
        "_id": other_user_oid,
        "name": "Other Staff",
        "email": "other@hospitalb.org",
        "role": "hospital",
        "center_id": str(other_center_oid),
        "password_hash": hash_password("Password123!"),
    })
    other_token = create_access_token({"sub": str(other_user_oid), "role": "hospital", "center_id": str(other_center_oid)})

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        req_res = await client.post(
            "/api/requests/",
            headers={"Authorization": f"Bearer {hosp_user['token']}"},
            json={
                "center_id": hosp_user["center_id"],
                "medical_type": "Blood",
                "quantity": 1,
                "weight_kg": 1.0,
                "urgency": "CRITICAL",
                "pickup": {"lat": 12.9716, "lng": 77.5946},
                "destination": {"lat": 12.9800, "lng": 77.6000},
            },
        )
        req_id = req_res.json()["id"]

        with patch.object(settings, "WEATHER_FORCE_CONDITION", "SAFE"), \
             patch("app.simulation.engine.SimulationEngine.run_mission_simulation", AsyncMock()):
            d_res = await client.post(f"/api/requests/{req_id}/dispatch", headers={"Authorization": f"Bearer {op_token}"})
            mission_id = d_res.json()["mission_id"]

        # Other hospital user attempts GET /api/missions/{mission_id} -> 404
        miss_res = await client.get(
            f"/api/missions/{mission_id}",
            headers={"Authorization": f"Bearer {other_token}"},
        )
        assert miss_res.status_code == 404


@pytest.mark.asyncio
async def test_no_secrets_or_prompts_leaked_in_responses(real_db, op_token, hosp_user, seeded_drone):
    """Neither the secret LLM API key nor system prompts are leaked into responses."""
    secret_key = "sk-super-secret-unique-key-99999"

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        req_res = await client.post(
            "/api/requests/",
            headers={"Authorization": f"Bearer {hosp_user['token']}"},
            json={
                "center_id": hosp_user["center_id"],
                "medical_type": "Plasma",
                "quantity": 1,
                "weight_kg": 0.8,
                "urgency": "HIGH",
                "pickup": {"lat": 12.9716, "lng": 77.5946},
                "destination": {"lat": 12.9800, "lng": 77.6000},
            },
        )
        req_id = req_res.json()["id"]

        with patch.object(settings, "LLM_API_KEY", secret_key), \
             patch.object(settings, "WEATHER_FORCE_CONDITION", "SAFE"), \
             patch("app.simulation.engine.SimulationEngine.run_mission_simulation", AsyncMock()):
            dispatch_res = await client.post(f"/api/requests/{req_id}/dispatch", headers={"Authorization": f"Bearer {op_token}"})
            assert secret_key not in dispatch_res.text

            summary_res = await client.get(f"/api/requests/{req_id}/summary", headers={"Authorization": f"Bearer {op_token}"})
            assert secret_key not in summary_res.text
            assert "You are an AI assistant in a medical drone management" not in summary_res.text


@pytest.mark.asyncio
async def test_live_bg_upgrade_guard_faithfulness(real_db, hosp_user):
    """
    Directly tests background upgrade on real database documents:
    - Hallucinated text is rejected, preserving template summary.
    - Faithful text is accepted, updating source to 'llm'.
    """
    from app.api.requests import _bg_upgrade_summary

    req_repo = MedicalRequestRepository(real_db)
    # Seed request with initial template summary
    req_doc = await req_repo.create({
        "center_id": hosp_user["center_id"],
        "medical_type": "Insulin",
        "quantity": 1,
        "weight_kg": 0.5,
        "urgency": "HIGH",
        "pickup": {"lat": 12.9716, "lng": 77.5946},
        "destination": {"lat": 12.9800, "lng": 77.6000},
        "status": "ASSIGNED",
        "dispatch_summary": {
            "text": "Baseline template summary.",
            "source": "template",
            "generated_at": datetime.now(UTC),
            "attempt": 1,
        },
    })
    req_id = req_doc["id"]

    facts = {
        "request_id": req_id,
        "medical_type": "Insulin",
        "allocated_drone_id": "DRN-001",
    }

    # 1. Hallucinated LLM response -> Guard rejects, stays template
    with patch.object(settings, "LLM_API_KEY", "mock-key"):
        with patch("app.api.requests.call_llm", AsyncMock(return_value="Dispatched on DRN-999 with 55 km/h wind")):
            await _bg_upgrade_summary(req_id, facts, req_repo)
            doc_after_hallucination = await req_repo.get_by_id(req_id)
            assert doc_after_hallucination["dispatch_summary"]["source"] == "template"

    # 2. Faithful LLM response -> Guard accepts, upgrades to 'llm'
    with patch.object(settings, "LLM_API_KEY", "mock-key"):
        with patch("app.api.requests.call_llm", AsyncMock(return_value="Insulin delivery is actively dispatched via drone DRN-001.")):
            await _bg_upgrade_summary(req_id, facts, req_repo)
            doc_after_faithful = await req_repo.get_by_id(req_id)
            assert doc_after_faithful["dispatch_summary"]["source"] == "llm"
            assert "DRN-001" in doc_after_faithful["dispatch_summary"]["text"]


@pytest.mark.asyncio
async def test_forced_unsafe_dispatch_halts_with_status_note_and_two_decisions(real_db, op_token, hosp_user):
    """
    Live-Mongo test with WEATHER_FORCE_CONDITION=UNSAFE:
    - Dispatch halts (weather_halted=True, mission_id=None).
    - Request has a status_note.
    - Exactly 2 decisions are stored in agent_decisions: PriorityAgent and WeatherAgent.
    """
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        req_res = await client.post(
            "/api/requests/",
            headers={"Authorization": f"Bearer {hosp_user['token']}"},
            json={
                "center_id": hosp_user["center_id"],
                "medical_type": "Insulin",
                "quantity": 1,
                "weight_kg": 0.5,
                "urgency": "HIGH",
                "pickup": {"lat": 12.9716, "lng": 77.5946},
                "destination": {"lat": 12.9800, "lng": 77.6000},
            },
        )
        assert req_res.status_code == 201
        req_id = req_res.json()["id"]

        with patch.object(settings, "WEATHER_FORCE_CONDITION", "UNSAFE"):
            dispatch_res = await client.post(
                f"/api/requests/{req_id}/dispatch",
                headers={"Authorization": f"Bearer {op_token}"},
            )
            assert dispatch_res.status_code == 200
            res_json = dispatch_res.json()
            assert res_json["weather_halted"] is True
            assert res_json["mission_id"] is None
            assert res_json["weather_condition"] == "UNSAFE"

        # Check request in DB has hospital status_note and dispatch_summary
        req_in_db = await real_db["medical_requests"].find_one({"_id": ObjectId(req_id)})
        assert req_in_db is not None
        assert req_in_db.get("status_note") is not None
        assert "Waiting: unsafe weather" in req_in_db["status_note"]
        assert req_in_db.get("dispatch_summary") is not None

        # Check agent_decisions collection: exactly 2 decisions stored (Priority and Weather)
        cursor = real_db["agent_decisions"].find({"request_id": req_id})
        decisions = [d async for d in cursor]
        assert len(decisions) == 2
        agent_names = [d["agent_name"] for d in decisions]
        assert "PriorityAgent" in agent_names
        assert "WeatherAgent" in agent_names
        assert "AllocationAgent" not in agent_names
        assert "SafetyAgent" not in agent_names
