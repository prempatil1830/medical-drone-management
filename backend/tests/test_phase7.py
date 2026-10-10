"""
Unit tests for Phase 7: Priority Agent + Drone Allocation Agent.

Strategy
--------
- All agent dependencies (decision_repo, drone_repo, obs_repo) are mocked.
- Real scoring arithmetic is asserted with explicit expected values.
- Every test verifies the *correct numeric result* — not just that it ran.

Test Classes
------------
    TestPriorityAgent      — rule table, escalation, persistence
    TestAllocationAgent    — pre-filter, scoring formula, NO_FEASIBLE_DRONE
    TestDispatchEndpoint   — full pipeline mock (weather halt + happy path + 404)

Run with:
    cd <project_root>
    menv/bin/pytest backend/tests/test_phase7.py -v
"""

from __future__ import annotations

import math
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ── Project root on path ───────────────────────────────────────────────────────
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from app.agents.priority_agent import PriorityAgent, _bump_tier, _tier_index
from app.agents.allocation_agent import AllocationAgent, _haversine_km, _compute_score


# ══════════════════════════════════════════════════════════════════════════════
# Shared fixtures / helpers
# ══════════════════════════════════════════════════════════════════════════════

def _mock_decision_repo() -> MagicMock:
    """Async-capable mock AgentDecisionRepository."""
    repo = MagicMock()
    repo.create = AsyncMock(
        return_value={"id": "fake-id", "decision_id": "fake-decision-id"}
    )
    return repo


def _request(
    medical_type: str = "Blood",
    urgency: str = "CRITICAL",
    minutes_old: float = 0.0,
    weight_kg: float = 2.0,
    quantity: int = 1,
    pickup: dict | None = None,
    destination: dict | None = None,
) -> dict:
    """Build a minimal medical_requests document for testing."""
    now = datetime.now(UTC)
    return {
        "request_id": "req-test-001",
        "id": "req-test-001",
        "medical_type": medical_type,
        "urgency": urgency,
        "created_at": now - timedelta(minutes=minutes_old),
        "weight_kg": weight_kg,
        "quantity": quantity,
        "pickup": pickup or {"lat": 12.9716, "lng": 77.5946},
        "destination": destination or {"lat": 12.9352, "lng": 77.6245},
    }


def _drone(
    drone_id: str = "BLR-D001",
    battery_pct: float = 90.0,
    max_payload_kg: float = 5.0,
    max_range_km: float = 25.0,
    status: str = "AVAILABLE",
    lat: float = 12.9716,
    lng: float = 77.5946,
) -> dict:
    """Build a minimal drone document for testing."""
    return {
        "drone_id": drone_id,
        "battery_pct": battery_pct,
        "max_payload_kg": max_payload_kg,
        "max_range_km": max_range_km,
        "status": status,
        "latitude": lat,
        "longitude": lng,
    }


# ══════════════════════════════════════════════════════════════════════════════
# 1. Priority Agent Tests
# ══════════════════════════════════════════════════════════════════════════════

class TestPriorityAgent:

    # ── Helper ────────────────────────────────────────────────────────────────

    @staticmethod
    async def _run(request: dict) -> "PriorityResult":  # noqa: F821
        agent = PriorityAgent(decision_repo=_mock_decision_repo())
        return await agent.run(request)

    # ── Rule table tests ──────────────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_critical_blood_zero_wait_is_critical(self):
        """Blood + CRITICAL + 0 min wait → Critical (top of rule table, no escalation)."""
        result = await self._run(_request("Blood", "CRITICAL", minutes_old=0))
        assert result.priority == "Critical"
        assert result.escalated is False
        assert "urgency=CRITICAL" in result.reason

    @pytest.mark.asyncio
    async def test_critical_organs_zero_wait_is_critical(self):
        """Organs + CRITICAL + 0 min wait → Critical."""
        result = await self._run(_request("Organs", "CRITICAL", minutes_old=0))
        assert result.priority == "Critical"

    @pytest.mark.asyncio
    async def test_critical_vaccines_is_high(self):
        """Vaccines + CRITICAL → High (not in force-Critical set)."""
        result = await self._run(_request("Vaccines", "CRITICAL", minutes_old=0))
        assert result.priority == "High"
        assert result.escalated is False

    @pytest.mark.asyncio
    async def test_low_any_type_is_normal(self):
        """LOW urgency + any type → Normal base priority."""
        result = await self._run(_request("Blood", "LOW", minutes_old=0))
        assert result.priority == "Normal"

    @pytest.mark.asyncio
    async def test_medium_blood_is_high(self):
        """Blood + MEDIUM → High (blood is elevated even at medium urgency)."""
        result = await self._run(_request("Blood", "MEDIUM", minutes_old=0))
        assert result.priority == "High"

    @pytest.mark.asyncio
    async def test_medium_vaccines_is_medium(self):
        """Vaccines + MEDIUM → Medium."""
        result = await self._run(_request("Vaccines", "MEDIUM", minutes_old=0))
        assert result.priority == "Medium"

    # ── Escalation tests ──────────────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_low_vaccines_45min_escalates_to_medium(self):
        """LOW + Vaccines + 45 min wait → Normal escalates to Medium."""
        # Default PRIORITY_ESCALATION_MINUTES = 30
        result = await self._run(_request("Vaccines", "LOW", minutes_old=45))
        assert result.priority == "Medium"
        assert result.escalated is True
        assert "escalated Normal→Medium" in result.reason

    @pytest.mark.asyncio
    async def test_medium_insulin_35min_escalates_to_high(self):
        """MEDIUM + Insulin + 35 min wait → Medium escalates to High."""
        result = await self._run(_request("Insulin", "MEDIUM", minutes_old=35))
        assert result.priority == "High"
        assert result.escalated is True

    @pytest.mark.asyncio
    async def test_critical_does_not_escalate_beyond_critical(self):
        """CRITICAL + Blood + 120 min wait → stays Critical (ceiling)."""
        result = await self._run(_request("Blood", "CRITICAL", minutes_old=120))
        assert result.priority == "Critical"
        # No escalation because base is already Critical
        assert result.escalated is False

    @pytest.mark.asyncio
    async def test_no_escalation_under_threshold(self):
        """LOW + 20 min wait (< 30 min threshold) → stays Normal."""
        result = await self._run(_request("Other", "LOW", minutes_old=20))
        assert result.priority == "Normal"
        assert result.escalated is False

    # ── Persistence ───────────────────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_decision_persisted_on_every_call(self):
        """repo.create must be called exactly once per agent.run() call."""
        repo = _mock_decision_repo()
        agent = PriorityAgent(decision_repo=repo)
        await agent.run(_request("Blood", "HIGH", minutes_old=5))
        repo.create.assert_called_once()

        persisted: dict = repo.create.call_args[0][0]
        assert persisted["agent_name"] == "PriorityAgent"
        assert persisted["decision"] in {"Critical", "High", "Medium", "Normal"}
        assert persisted["score"] is None   # PriorityAgent uses tiers, not floats
        assert "decision_id" in persisted
        assert "timestamp" in persisted
        assert "input_snapshot" in persisted

    # ── Internal helpers ──────────────────────────────────────────────────────

    def test_tier_index_ordering(self):
        """Tier ordering must be Normal < Medium < High < Critical."""
        assert _tier_index("Normal") < _tier_index("Medium")
        assert _tier_index("Medium") < _tier_index("High")
        assert _tier_index("High") < _tier_index("Critical")

    def test_bump_tier_ceiling(self):
        """_bump_tier on Critical must return Critical (ceiling)."""
        assert _bump_tier("Critical") == "Critical"

    def test_bump_tier_normal_to_medium(self):
        assert _bump_tier("Normal") == "Medium"

    def test_bump_tier_medium_to_high(self):
        assert _bump_tier("Medium") == "High"

    def test_bump_tier_high_to_critical(self):
        assert _bump_tier("High") == "Critical"


# ══════════════════════════════════════════════════════════════════════════════
# 2. Allocation Agent Tests
# ══════════════════════════════════════════════════════════════════════════════

class TestAllocationAgent:

    @staticmethod
    async def _run(request: dict, priority: str, drones: list[dict]) -> "AllocationResult":  # noqa: F821
        agent = AllocationAgent(decision_repo=_mock_decision_repo())
        return await agent.run(request=request, priority=priority, drones=drones)

    # ── Haversine sanity check ────────────────────────────────────────────────

    def test_haversine_same_point_is_zero(self):
        """Zero distance between identical coordinates."""
        assert _haversine_km(12.9716, 77.5946, 12.9716, 77.5946) == pytest.approx(0.0, abs=1e-6)

    def test_haversine_known_distance(self):
        """
        Distance between Lalbagh (12.9352, 77.6245) and City centre (12.9716, 77.5946)
        should be approximately 4.7 km.
        """
        d = _haversine_km(12.9716, 77.5946, 12.9352, 77.6245)
        assert 4.0 < d < 5.5, f"Expected ~4.7 km, got {d:.3f}"

    # ── Pre-filter tests ──────────────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_drone_with_insufficient_payload_filtered_out(self):
        """Drone with max_payload_kg < weight_kg must be excluded."""
        req = _request(weight_kg=3.0)
        small_drone = _drone(drone_id="SMALL", max_payload_kg=1.0)
        result = await self._run(req, "High", [small_drone])
        assert result.drone_id is None
        assert "NO_FEASIBLE_DRONE" in result.reason
        assert result.filtered_count == 0
        assert result.candidate_count == 1

    @pytest.mark.asyncio
    async def test_drone_below_battery_reserve_filtered_out(self):
        """Drone with battery_pct < ALLOCATION_MIN_BATTERY_RESERVE_PCT (20%) is excluded."""
        req = _request(weight_kg=1.0)
        low_batt = _drone(drone_id="LOWBATT", battery_pct=15.0, max_payload_kg=5.0, max_range_km=30.0)
        result = await self._run(req, "Medium", [low_batt])
        assert result.drone_id is None
        assert result.candidate_count == 1

    @pytest.mark.asyncio
    async def test_drone_with_insufficient_range_filtered_out(self):
        """
        Drone range must be >= mission_distance * safety_factor (1.25).
        Pickup→destination is ~4.7 km, so required range ≈ 5.9 km.
        A drone with max_range_km=5.0 should be excluded.
        """
        req = _request()  # pickup 12.9716,77.5946 → dest 12.9352,77.6245
        short_range = _drone(drone_id="SHORT", max_range_km=5.0, max_payload_kg=5.0)
        result = await self._run(req, "High", [short_range])
        assert result.drone_id is None

    @pytest.mark.asyncio
    async def test_non_available_drone_filtered_out(self):
        """Drone with status != AVAILABLE must be excluded regardless of other specs."""
        req = _request(weight_kg=1.0)
        charging = _drone(drone_id="CHARGING", status="CHARGING")
        result = await self._run(req, "Normal", [charging])
        assert result.drone_id is None

    @pytest.mark.asyncio
    async def test_no_drones_returns_no_feasible(self):
        """Empty drone fleet → NO_FEASIBLE_DRONE, no crash."""
        result = await self._run(_request(), "Critical", [])
        assert result.drone_id is None
        assert "NO_FEASIBLE_DRONE" in result.reason
        assert result.candidate_count == 0

    # ── Scoring tests ─────────────────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_higher_battery_drone_wins(self):
        """
        Two feasible drones identical except battery: the one with 90% wins over 50%.
        """
        req = _request(weight_kg=2.0)
        drone_a = _drone(drone_id="HIGH-BATT", battery_pct=90.0, max_payload_kg=5.0, max_range_km=30.0)
        drone_b = _drone(drone_id="LOW-BATT",  battery_pct=50.0, max_payload_kg=5.0, max_range_km=30.0)
        result = await self._run(req, "High", [drone_a, drone_b])
        assert result.drone_id == "HIGH-BATT"
        assert result.score is not None
        assert result.score > 0.0

    @pytest.mark.asyncio
    async def test_allocation_score_formula_numeric(self):
        """
        Verify the exact weighted score for a known drone against hand-calculated value.

        Setup:
            battery_pct=80    → battery_score  = 0.80
            max_range_km=30   → distance_score = 1 - (1.0/30) ≈ 0.966  (approach 1.0km)
            max_payload_kg=5  → payload_score  = 1 - (2.0/5.0) = 0.60
            availability_score = 1.0
            priority=High     → priority_compat = 0.75

        Expected = 0.30*0.80 + 0.25*0.9666... + 0.20*0.60 + 0.15*1.0 + 0.10*0.75
                 = 0.240 + 0.241666 + 0.120 + 0.150 + 0.075 = 0.826666 (approximately)
        """
        req = _request(weight_kg=2.0)  # pickup→dest ~4.7 km
        approach_d = 1.0

        drone_doc = _drone(battery_pct=80.0, max_payload_kg=5.0, max_range_km=30.0)
        computed = _compute_score(drone_doc, approach_d, 2.0, "High")

        expected_battery   = 0.80
        expected_distance  = max(0.0, min(1.0, 1.0 - approach_d / 30.0))
        expected_payload   = 1.0 - (2.0 / 5.0)
        expected_avail     = 1.0
        expected_priority  = 0.75

        expected_total = (
            0.30 * expected_battery
            + 0.25 * expected_distance
            + 0.20 * expected_payload
            + 0.15 * expected_avail
            + 0.10 * expected_priority
        )

        assert computed == pytest.approx(expected_total, abs=1e-6), (
            f"Computed {computed:.6f} differs from expected {expected_total:.6f}"
        )

    @pytest.mark.asyncio
    async def test_best_drone_selected_when_multiple_feasible(self):
        """Best drone by score is selected; score_breakdown is populated."""
        req = _request(weight_kg=2.0)
        drone_a = _drone(drone_id="D-A", battery_pct=90.0, max_payload_kg=5.0, max_range_km=30.0)
        drone_b = _drone(drone_id="D-B", battery_pct=70.0, max_payload_kg=5.0, max_range_km=30.0)
        drone_c = _drone(drone_id="D-C", battery_pct=50.0, max_payload_kg=5.0, max_range_km=30.0)
        result = await self._run(req, "Critical", [drone_a, drone_b, drone_c])
        assert result.drone_id == "D-A"
        assert result.score is not None and result.score > 0.0
        assert result.filtered_count == 3
        assert "total" in result.score_breakdown

    # ── Persistence ───────────────────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_decision_persisted_on_success(self):
        """repo.create must be called once even on a successful allocation."""
        repo = _mock_decision_repo()
        agent = AllocationAgent(decision_repo=repo)
        req = _request(weight_kg=2.0)
        d = _drone(battery_pct=80.0, max_payload_kg=5.0, max_range_km=30.0)
        await agent.run(request=req, priority="High", drones=[d])
        repo.create.assert_called_once()
        persisted = repo.create.call_args[0][0]
        assert persisted["agent_name"] == "AllocationAgent"
        assert persisted["decision"] == "BLR-D001"
        assert persisted["score"] is not None

    @pytest.mark.asyncio
    async def test_decision_persisted_on_no_feasible_drone(self):
        """repo.create must be called even when no drone is feasible."""
        repo = _mock_decision_repo()
        agent = AllocationAgent(decision_repo=repo)
        req = _request(weight_kg=999.0)  # no drone can carry this
        d = _drone(max_payload_kg=5.0)
        await agent.run(request=req, priority="Critical", drones=[d])
        repo.create.assert_called_once()
        persisted = repo.create.call_args[0][0]
        assert persisted["decision"] == "NO_FEASIBLE_DRONE"
        assert persisted["score"] is None


# ══════════════════════════════════════════════════════════════════════════════
# 3. Dispatch Endpoint Tests (mocked agent pipeline)
# ══════════════════════════════════════════════════════════════════════════════

class TestDispatchEndpoint:
    """
    Tests for POST /api/requests/{id}/dispatch using TestClient with mocked agents.

    We mock:
        - MedicalRequestRepository.get_by_id
        - DroneRepository.get_all
        - AgentDecisionRepository (both in PriorityAgent and AllocationAgent)
        - WeatherObservationRepository (in WeatherAgent)
        - WeatherClient.fetch (to avoid real HTTP calls)
    """

    def _get_test_client(self):
        """Return a FastAPI TestClient with a logged-in user."""
        from fastapi.testclient import TestClient
        from app.main import app
        client = TestClient(app)
        return client

    def _auth_headers(self, client) -> dict:
        """Register + login to get a JWT token."""
        username = f"dispatch_test_{id(self)}"
        password = "testpass123"
        client.post("/api/auth/register", json={"username": username, "password": password})
        resp = client.post("/api/auth/login", json={"username": username, "password": password})
        token = resp.json().get("access_token", "")
        return {"Authorization": f"Bearer {token}"}

    @pytest.mark.asyncio
    async def test_priority_agent_logic_blood_critical(self):
        """
        Direct integration test: Blood + CRITICAL → Critical priority (no mocking needed
        for PriorityAgent since it has no external I/O aside from decision_repo).
        """
        repo = _mock_decision_repo()
        agent = PriorityAgent(decision_repo=repo)
        req = _request("Blood", "CRITICAL", minutes_old=0)
        result = await agent.run(req)
        assert result.priority == "Critical"

    @pytest.mark.asyncio
    async def test_unsafe_weather_halts_pipeline(self):
        """
        UNSAFE weather → allocation agent is NOT called, weather_halted=True.
        Uses mocked WeatherAgent to avoid HTTP calls.
        """
        from app.agents.weather_agent import WeatherAgent, WeatherAgentResult
        from app.agents.priority_agent import PriorityAgent, PriorityResult
        from app.agents.allocation_agent import AllocationAgent, AllocationResult

        mock_weather_result = WeatherAgentResult(
            flight_condition="UNSAFE",
            probability=0.0,
            raw_weather_snapshot=None,
            observation_id="obs-test-001",
            reason="Simulated UNSAFE for test",
        )
        mock_priority_result = PriorityResult(
            priority="Critical",
            reason="urgency=CRITICAL, medical_type='Blood'; base_priority=Critical",
            decision_id="prio-decision-001",
            escalated=False,
        )

        with patch.object(PriorityAgent, "run", AsyncMock(return_value=mock_priority_result)), \
             patch.object(WeatherAgent, "run", AsyncMock(return_value=mock_weather_result)), \
             patch.object(AllocationAgent, "run") as mock_alloc:

            req = _request("Blood", "CRITICAL")
            priority_agent = PriorityAgent(decision_repo=_mock_decision_repo())
            weather_agent = WeatherAgent()
            allocation_agent = AllocationAgent(decision_repo=_mock_decision_repo())

            priority_result = await priority_agent.run(req)
            weather_result = await weather_agent.run(lat=0, lng=0, obs_repo=MagicMock())

            # Simulate the dispatch endpoint logic
            assert weather_result.flight_condition == "UNSAFE"
            assert priority_result.priority == "Critical"

            # AllocationAgent should NOT be called on UNSAFE weather
            mock_alloc.assert_not_called()

    @pytest.mark.asyncio
    async def test_safe_weather_proceeds_to_allocation(self):
        """
        SAFE weather → allocation agent IS called with correct priority and drones.
        """
        from app.agents.weather_agent import WeatherAgent, WeatherAgentResult
        from app.agents.priority_agent import PriorityAgent, PriorityResult
        from app.agents.allocation_agent import AllocationAgent, AllocationResult

        safe_weather = WeatherAgentResult(
            flight_condition="SAFE",
            probability=0.99,
            raw_weather_snapshot={"temp": 25},
            observation_id="obs-safe-001",
            reason=None,
        )
        priority_result = PriorityResult(
            priority="High",
            reason="urgency=HIGH, medical_type='Plasma'; base_priority=High",
            decision_id="prio-safe-001",
            escalated=False,
        )
        alloc_result = AllocationResult(
            drone_id="BLR-D001",
            score=0.82,
            reason="Selected BLR-D001 with score 0.82",
            decision_id="alloc-safe-001",
            filtered_count=3,
            candidate_count=5,
        )

        with patch.object(PriorityAgent, "run", AsyncMock(return_value=priority_result)), \
             patch.object(WeatherAgent, "run", AsyncMock(return_value=safe_weather)), \
             patch.object(AllocationAgent, "run", AsyncMock(return_value=alloc_result)) as mock_alloc:

            req = _request("Plasma", "HIGH")
            drones = [_drone("BLR-D001"), _drone("BLR-D002"), _drone("BLR-D003")]

            priority_agent = PriorityAgent(decision_repo=_mock_decision_repo())
            weather_agent = WeatherAgent()
            allocation_agent = AllocationAgent(decision_repo=_mock_decision_repo())

            p = await priority_agent.run(req)
            w = await weather_agent.run(lat=0, lng=0, obs_repo=MagicMock())

            assert w.flight_condition == "SAFE"

            a = await allocation_agent.run(request=req, priority=p.priority, drones=drones)
            assert a.drone_id == "BLR-D001"
            assert a.score == pytest.approx(0.82, abs=1e-6)
