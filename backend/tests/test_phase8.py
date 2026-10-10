"""
Tests for Phase 8: Route Agent, Safety Agent, and Mission Creation.
"""

from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient

from app.agents.route_agent import RouteAgent
from app.agents.safety_agent import SafetyAgent
from app.core.config import settings
from app.main import app

# ── Mock Repositories ─────────────────────────────────────────────────────────

class MockDecisionRepo:
    def __init__(self):
        self.decisions = []

    async def create(self, data: dict):
        self.decisions.append(data)
        return {"id": "mock-id", "decision_id": data["decision_id"]}


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def mock_decision_repo():
    return MockDecisionRepo()


@pytest.fixture
def base_request():
    return {
        "request_id": "req-123",
        "weight_kg": 2.0,
        "pickup": {"lat": 12.9716, "lng": 77.5946},
        "destination": {"lat": 12.9352, "lng": 77.6245}, # Koramangala (approx 5.18km)
    }


@pytest.fixture
def base_drone():
    return {
        "drone_id": "BLR-D001",
        "status": "AVAILABLE",
        "battery_pct": 100.0,
        "max_payload_kg": 5.0,
        "max_range_km": 25.0,
    }

# ── Route Agent Tests ─────────────────────────────────────────────────────────

class TestRouteAgent:
    def test_haversine_computation(self, base_request):
        agent = RouteAgent()
        res = agent.run(base_request["pickup"], base_request["destination"])
        
        # Lalbagh to Koramangala is approx 5.18km
        assert 5.0 < res.distance_km < 5.5
        
        # ETA calculation: 5.18 / 60 km/h = 0.086 hours = ~5.18 mins
        assert 5.0 < res.eta_minutes < 5.5
        
        # Battery required: 5.18 * 1.5% = 7.77%
        assert 7.0 < res.battery_required_pct < 8.5
        
        # Route points
        assert len(res.route) == 2
        assert res.route[0] == base_request["pickup"]
        assert res.route[1] == base_request["destination"]


# ── Safety Agent Tests ────────────────────────────────────────────────────────

@pytest.mark.asyncio
class TestSafetyAgent:
    async def test_safety_agent_pass(self, mock_decision_repo, base_request, base_drone):
        agent = SafetyAgent(decision_repo=mock_decision_repo)
        route_agent = RouteAgent()
        route_res = route_agent.run(base_request["pickup"], base_request["destination"])
        
        res = await agent.run(
            request=base_request,
            drone=base_drone,
            route_result=route_res,
            weather_condition="SAFE"
        )
        
        assert res.decision == "PASS"
        assert len(mock_decision_repo.decisions) == 1
        assert mock_decision_repo.decisions[0]["decision"] == "PASS"

    async def test_safety_agent_rejects_unsafe_weather(self, mock_decision_repo, base_request, base_drone):
        agent = SafetyAgent(decision_repo=mock_decision_repo)
        route_agent = RouteAgent()
        route_res = route_agent.run(base_request["pickup"], base_request["destination"])
        
        res = await agent.run(
            request=base_request,
            drone=base_drone,
            route_result=route_res,
            weather_condition="UNSAFE"
        )
        
        assert res.decision == "REJECT"
        assert "Weather is UNSAFE" in res.reason

    async def test_safety_agent_rejects_payload_exceeded(self, mock_decision_repo, base_request, base_drone):
        agent = SafetyAgent(decision_repo=mock_decision_repo)
        route_agent = RouteAgent()
        route_res = route_agent.run(base_request["pickup"], base_request["destination"])
        
        # Mutate drone to have lower payload than request
        base_drone["max_payload_kg"] = 1.0
        
        res = await agent.run(
            request=base_request,
            drone=base_drone,
            route_result=route_res,
            weather_condition="SAFE"
        )
        
        assert res.decision == "REJECT"
        assert "weight (2.0kg) exceeds drone capacity" in res.reason

    async def test_safety_agent_independent_battery_validation(self, mock_decision_repo, base_request, base_drone):
        agent = SafetyAgent(decision_repo=mock_decision_repo)
        route_agent = RouteAgent()
        route_res = route_agent.run(base_request["pickup"], base_request["destination"]) # Needs ~7.77% battery
        
        # Mutate drone battery to barely fail (needs 7.77%, reserve is 20%, drone has 27%)
        # Available is 27 - 20 = 7.0%, which is < 7.77%.
        base_drone["battery_pct"] = 27.0
        
        res = await agent.run(
            request=base_request,
            drone=base_drone,
            route_result=route_res,
            weather_condition="SAFE"
        )
        
        assert res.decision == "REQUEST_REALLOCATION"
        assert "Insufficient battery" in res.reason

    async def test_safety_agent_independent_status_validation(self, mock_decision_repo, base_request, base_drone):
        agent = SafetyAgent(decision_repo=mock_decision_repo)
        route_agent = RouteAgent()
        route_res = route_agent.run(base_request["pickup"], base_request["destination"])
        
        # Mutate drone status (e.g. race condition grabbed it)
        base_drone["status"] = "ASSIGNED"
        
        res = await agent.run(
            request=base_request,
            drone=base_drone,
            route_result=route_res,
            weather_condition="SAFE"
        )
        
        assert res.decision == "REQUEST_REALLOCATION"
        assert "no longer AVAILABLE" in res.reason

# ── End-to-End Pipeline Tests ─────────────────────────────────────────────────

def mock_get_current_user():
    return {"user_id": "test_user", "role": "operator"}

@pytest.mark.asyncio
class TestDispatchEndpointPhase8:
    async def test_dispatch_success_creates_mission(self):
        # Setup request mock
        req_mock = AsyncMock()
        from datetime import datetime, UTC
        req_mock.get_by_id.return_value = {
            "request_id": "req-full-test",
            "medical_type": "Blood",
            "urgency": "CRITICAL",
            "created_at": datetime.now(UTC),
            "pickup": {"lat": 12.9716, "lng": 77.5946},
            "destination": {"lat": 12.9352, "lng": 77.6245},
            "weight_kg": 2.0,
            "quantity": 1
        }
        
        # Setup drone mock
        drone_mock = AsyncMock()
        drone_data = {
            "drone_id": "BLR-D999",
            "status": "AVAILABLE",
            "battery_pct": 100.0,
            "max_payload_kg": 5.0,
            "max_range_km": 25.0,
            "latitude": 12.9716,
            "longitude": 77.5946,
        }
        drone_mock.get_all.return_value = [drone_data]
        drone_mock.get_by_drone_id.return_value = drone_data
        drone_mock.update_status = AsyncMock()
        
        # Setup decision mock
        dec_mock = AsyncMock()
        dec_mock.create.return_value = {"id": "1", "decision_id": "dec-1"}
        
        # Setup weather mock
        obs_mock = AsyncMock()
        
        # Setup mission mock
        mis_mock = AsyncMock()
        mis_mock.create.return_value = {"mission_id": "miss-999"}

        from app.repositories.medical_request import get_request_repo
        from app.repositories.drone import get_drone_repo
        from app.repositories.agent_decision import get_agent_decision_repo
        from app.repositories.weather_observation import get_weather_obs_repo
        from app.repositories.mission import get_mission_repo
        from app.api.auth import get_current_user

        app.dependency_overrides[get_request_repo] = lambda: req_mock
        app.dependency_overrides[get_drone_repo] = lambda: drone_mock
        app.dependency_overrides[get_agent_decision_repo] = lambda: dec_mock
        app.dependency_overrides[get_weather_obs_repo] = lambda: obs_mock
        app.dependency_overrides[get_mission_repo] = lambda: mis_mock
        app.dependency_overrides[get_current_user] = mock_get_current_user

        with patch("app.agents.weather_agent.WeatherAgent.run", new_callable=AsyncMock) as weather_run:
            weather_run.return_value = type("obj", (object,), {
                "flight_condition": "SAFE",
                "reason": "Clear skies",
                "observation_id": "obs-1"
            })

            from httpx import ASGITransport
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                response = await ac.post("/api/requests/req-full-test/dispatch")
                
            assert response.status_code == 200
            data = response.json()
            
            # Verify full trail
            assert data["priority_decision"] == "Critical"
            assert data["weather_condition"] == "SAFE"
            assert data["allocated_drone_id"] == "BLR-D999"
            assert data["route_distance_km"] > 0
            assert data["safety_decision"] == "PASS"
            assert data["mission_id"] == "miss-999"
            
            # Verify drone status was updated
            drone_mock.update_status.assert_called_once_with("BLR-D999", "ASSIGNED")
            
            # Verify mission was created
            mis_mock.create.assert_called_once()
            created_mission_doc = mis_mock.create.call_args[0][0]
            assert created_mission_doc["request_id"] == "req-full-test"
            assert created_mission_doc["drone_id"] == "BLR-D999"

            app.dependency_overrides.clear()
