"""
Unit tests for Small Fixes and Explanation Service (Grounding Guard & LLM client).
Never deletes or overwrites existing tests.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch, MagicMock
import pytest

from app.agents.priority_agent import PriorityAgent, classify_priority
from app.agents.weather_agent import WeatherAgent
from app.schemas.medical_request import MedicalType, Urgency
from app.core.config import settings
from app.services.explain import (
    extract_dispatch_facts,
    build_template_summary,
    build_weather_note,
    verify_grounding,
    call_llm,
    generate_explanation,
    get_system_prompt,
)


# ── Fix 0a: Priority Reason Enum .value ────────────────────────────────────────

@pytest.mark.asyncio
async def test_priority_agent_reason_uses_enum_value_not_repr():
    """Priority reason strings must print the enum .value ('Emergency Medicine'), not enum repr."""
    decision_repo = MagicMock()
    decision_repo.create = AsyncMock()
    agent = PriorityAgent(decision_repo=decision_repo)

    req = {
        "request_id": "REQ-ENUM-TEST",
        "medical_type": MedicalType.EMERGENCY_MEDICINE,
        "urgency": Urgency.critical,
        "quantity": 1,
        "weight_kg": 1.5,
    }

    result = await agent.run(req)

    # Must contain the human-friendly .value strings
    assert "Emergency Medicine" in result.reason
    assert "Critical" in result.reason
    # Must NOT contain enum repr syntax
    assert "MedicalType." not in result.reason
    assert "Urgency." not in result.reason


# ── Fix 0b: WEATHER_FORCE_CONDITION demo switch ────────────────────────────────

@pytest.mark.asyncio
@pytest.mark.parametrize("forced_cond", ["SAFE", "CAUTION", "UNSAFE"])
async def test_weather_agent_force_condition_switch(forced_cond):
    """When WEATHER_FORCE_CONDITION is set, model is skipped and forced condition returned."""
    agent = WeatherAgent()
    obs_repo = MagicMock()
    obs_repo.create = AsyncMock(return_value={"observation_id": "OBS-FORCED"})

    with patch.object(settings, "WEATHER_FORCE_CONDITION", forced_cond):
        with patch("app.agents.weather_agent.predict_flight_condition") as mock_predict:
            result = await agent.run(lat=12.9716, lng=77.5946, obs_repo=obs_repo)
            assert result.flight_condition == forced_cond
            assert result.reason == "Forced by WEATHER_FORCE_CONDITION (demo)"
            mock_predict.assert_not_called()


# ── Explanation Service Facts & Sanitization ──────────────────────────────────

def test_extract_dispatch_facts_excludes_user_pii():
    """Facts extraction must strictly avoid user names, emails, or personal identifiers."""
    req_doc = {
        "request_id": "REQ-12345",
        "user_name": "Dr. John Doe",
        "user_email": "john.doe@hospital.org",
        "medical_type": "Vaccine",
        "urgency": "High",
        "quantity": 5,
        "weight_kg": 2.0,
    }
    decisions = [
        {"agent_name": "PriorityAgent", "decision": "High", "score": 0.8, "reason": "High urgency Vaccine"},
    ]
    facts = extract_dispatch_facts(request=req_doc, decisions=decisions)

    facts_str = str(facts).lower()
    assert "john" not in facts_str
    assert "doe" not in facts_str
    assert "email" not in facts_str
    assert facts["request_id"] == "REQ-12345"
    assert facts["medical_type"] == "Vaccine"


# ── Grounding Guard ───────────────────────────────────────────────────────────

def test_grounding_guard_accepts_faithful_text():
    """Grounding Guard accepts text using only facts, simple roundings, or percentages."""
    facts = {
        "request_id": "REQ-101",
        "allocated_drone_id": "DRN-001",
        "route": {"distance_km": 14.2, "eta_minutes": 18.0, "battery_required_pct": 28.5},
        "weather": {"condition": "SAFE", "probability": 0.95},
    }
    # Faithful text with valid roundings and references
    faithful_text = (
        "Drone DRN-001 was selected for request REQ-101 under SAFE weather (95% confidence). "
        "The flight spans 14.2 km with an ETA of 18 minutes using 28.5% battery."
    )
    assert verify_grounding(faithful_text, facts) is True


def test_grounding_guard_discards_invented_numbers_and_wind():
    """Grounding Guard discards invented facts like 'wind 42 km/h' or ungrounded numbers."""
    facts = {
        "request_id": "REQ-101",
        "allocated_drone_id": "DRN-001",
        "route": {"distance_km": 14.2, "eta_minutes": 18.0, "battery_required_pct": 28.5},
        "weather": {"condition": "SAFE", "probability": 0.95},
    }
    # LLM hallucinates 42 km/h wind speed not present in facts
    hallucinated_text = (
        "Drone DRN-001 is dispatched for REQ-101 in SAFE weather with wind 42 km/h. "
        "Distance is 14.2 km."
    )
    assert verify_grounding(hallucinated_text, facts) is False


def test_grounding_guard_discards_invented_ids():
    """Grounding Guard discards unknown or invented drone/mission/request identifiers."""
    facts = {
        "request_id": "REQ-101",
        "allocated_drone_id": "DRN-001",
    }
    # Invented drone ID DRN-999
    hallucinated_id_text = "Dispatched via drone DRN-999 for request REQ-101."
    assert verify_grounding(hallucinated_id_text, facts) is False


# ── LLM Client Fail-safe & Timeout ────────────────────────────────────────────

@pytest.mark.asyncio
async def test_llm_client_timeout_or_error_falls_back_to_template():
    """If LLM client times out or raises an exception, template summary is preserved."""
    facts = {
        "request_id": "REQ-101",
        "medical_type": "Insulin",
        "urgency": "High",
        "decisions": [{"agent_name": "PriorityAgent", "decision": "High", "reason": "Insulin delivery"}],
    }

    with patch.object(settings, "LLM_API_KEY", "mock-key"):
        with patch("httpx.AsyncClient.post", side_effect=asyncio.TimeoutError("Call timed out")):
            explanation = await generate_explanation(facts)
            assert explanation["source"] == "template"
            assert "Insulin" in explanation["text"]


@pytest.mark.asyncio
async def test_no_api_key_returns_template_summary():
    """When LLM_API_KEY is empty, LLM is bypassed cleanly with source == 'template'."""
    facts = {
        "request_id": "REQ-202",
        "medical_type": "Blood",
        "urgency": "Critical",
        "decisions": [{"agent_name": "PriorityAgent", "decision": "Critical", "reason": "Blood delivery"}],
    }

    with patch.object(settings, "LLM_API_KEY", None):
        explanation = await generate_explanation(facts)
        assert explanation["source"] == "template"
        assert "Blood" in explanation["text"]
        assert explanation["attempt"] == 1


@pytest.mark.asyncio
async def test_llm_accepted_when_faithful():
    """When LLM returns faithful text passing grounding guard, source == 'llm'."""
    facts = {
        "request_id": "REQ-303",
        "medical_type": "Antivenom",
        "urgency": "Critical",
        "allocated_drone_id": "DRN-002",
        "decisions": [
            {"agent_name": "PriorityAgent", "decision": "Critical", "reason": "Antivenom delivery"},
            {"agent_name": "AllocationAgent", "decision": "DRN-002", "reason": "Available drone"},
        ],
    }

    mock_llm_response = {
        "choices": [{
            "message": {
                "content": "Request REQ-303 for Antivenom was designated Critical priority, and drone DRN-002 has been allocated."
            }
        }]
    }

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json = MagicMock(return_value=mock_llm_response)

    with patch.object(settings, "LLM_API_KEY", "mock-key"):
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock_resp):
            explanation = await generate_explanation(facts)
            assert explanation["source"] == "llm"
            assert "DRN-002" in explanation["text"]


# ── Guard Hardening: Number words & Qualitative terms ─────────────────────────

def test_guard_hardening_seven_candidate_drones_discarded():
    """'seven candidate drones' when facts say 3 -> discarded."""
    facts = {
        "request_id": "REQ-101",
        "candidate_count": 3,
        "allocated_drone_id": "DRN-001",
    }
    llm_text = "The system considered seven candidate drones and chose DRN-001 for REQ-101."
    assert verify_grounding(llm_text, facts) is False


def test_guard_hardening_strong_winds_discarded_when_not_in_facts():
    """'despite strong winds' when facts mention no wind -> discarded."""
    facts = {
        "request_id": "REQ-101",
        "allocated_drone_id": "DRN-001",
        "weather": {"condition": "SAFE"},
    }
    llm_text = "Dispatched drone DRN-001 for REQ-101 despite strong winds."
    assert verify_grounding(llm_text, facts) is False


def test_guard_hardening_three_candidate_drones_accepted():
    """'three candidate drones' when facts say 3 -> accepted."""
    facts = {
        "request_id": "REQ-101",
        "candidate_count": 3,
        "allocated_drone_id": "DRN-001",
    }
    llm_text = "Drone DRN-001 was selected from three candidate drones for REQ-101."
    assert verify_grounding(llm_text, facts) is True


@pytest.mark.asyncio
async def test_weather_agent_unset_force_condition_restores_model():
    """Unset WEATHER_FORCE_CONDITION restores the model prediction path."""
    agent = WeatherAgent()
    obs_repo = MagicMock()
    obs_repo.create = AsyncMock(return_value={"observation_id": "OBS-NORMAL"})

    mock_client = MagicMock()
    from app.services.weather_client import WeatherAPIResult
    mock_client.fetch = AsyncMock(return_value=WeatherAPIResult(
        ok=True,
        data={
            "location": {"name": "Bengaluru", "lat": 12.9716, "lon": 77.5946},
            "current": {
                "temp_c": 22.0, "wind_kph": 10.0, "wind_gust_kph": 12.0,
                "precip_mm": 0.0, "vis_km": 10.0, "humidity": 50, "cloud": 20,
                "pressure_mb": 1013.0, "condition": {"text": "Clear"},
            },
        },
    ))
    agent._client = mock_client

    with patch.object(settings, "WEATHER_FORCE_CONDITION", ""):
        with patch("app.agents.weather_agent.predict_flight_condition") as mock_predict:
            mock_predict.return_value = {
                "flight_condition": "SAFE",
                "probability": 0.95,
            }
            result = await agent.run(lat=12.9716, lng=77.5946, obs_repo=obs_repo)
            assert result.flight_condition == "SAFE"
            assert result.reason != "Forced by WEATHER_FORCE_CONDITION (demo)"
            mock_predict.assert_called_once()


@pytest.mark.asyncio
async def test_summary_provenance_stored_text_matches_accepted_reply_or_template():
    """
    Asserts stored text == the accepted LLM reply (markdown stripped) when source == 'llm'
    and == the template when source == 'template'.
    """
    from app.services.explain import strip_markdown

    facts = {
        "request_id": "REQ-777",
        "medical_type": "Insulin",
        "urgency": "HIGH",
        "allocated_drone_id": "DRN-005",
        "candidate_count": 5,
        "weather": {"condition": "SAFE", "probability": 0.999},
        "route": {"distance_km": 2.5, "eta_minutes": 2.5, "battery_required_pct": 3.0},
    }
    template = build_template_summary(facts)

    # 1. Source 'llm': accepted LLM reply with markdown stripped
    raw_llm_markdown = "Priority is **High** for **Insulin**. Drone **DRN-005** selected from 5 candidates. Weather is **SAFE**."
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json = MagicMock(return_value={"choices": [{"message": {"content": raw_llm_markdown}}]})

    with patch.object(settings, "LLM_API_KEY", "mock-key"):
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock_resp):
            res_llm = await generate_explanation(facts)
            assert res_llm["source"] == "llm"
            expected_stripped = strip_markdown(raw_llm_markdown)
            assert res_llm["text"] == expected_stripped
            assert "**" not in res_llm["text"]

    # 2. Source 'template': when LLM rejected by guard or disabled
    hallucinated_llm = "Selected drone DRN-999 with 88 km/h storm wind."
    mock_resp_bad = MagicMock()
    mock_resp_bad.status_code = 200
    mock_resp_bad.json = MagicMock(return_value={"choices": [{"message": {"content": hallucinated_llm}}]})

    with patch.object(settings, "LLM_API_KEY", "mock-key"):
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock_resp_bad):
            res_template = await generate_explanation(facts)
            assert res_template["source"] == "template"
            assert res_template["text"] == template


def test_template_wording_weather_forced():
    """
    When weather is forced (e.g. Forced by WEATHER_FORCE_CONDITION (demo)),
    template must NOT print 'with 0.0% confidence'.
    It must print: 'Weather could not be evaluated by the model (<reason>), so the flight was treated as UNSAFE.'
    """
    reason = "Forced by WEATHER_FORCE_CONDITION (demo)"
    facts = {
        "medical_type": "Insulin",
        "urgency": "HIGH",
        "weather": {
            "condition": "UNSAFE",
            "probability": 0.0,
            "reason": reason,
        },
    }
    summary = build_template_summary(facts)
    assert "0.0% confidence" not in summary
    assert f"Weather could not be evaluated by the model ({reason}), so the flight was treated as UNSAFE." in summary
    assert "treated as UNSAFE" in summary


def test_template_wording_weather_api_failure():
    """
    When weather evaluation fails closed due to an API failure or missing probability,
    template must NOT print 'with 0.0% confidence'.
    It must print: 'Weather could not be evaluated by the model (<reason>), so the flight was treated as UNSAFE.'
    """
    reason = "WeatherAPI HTTP 503 Service Unavailable"
    facts = {
        "medical_type": "Blood (O-)",
        "urgency": "CRITICAL",
        "weather": {
            "condition": "UNSAFE",
            "probability": None,
            "reason": reason,
        },
    }
    summary = build_template_summary(facts)
    assert "confidence" not in summary
    assert f"Weather could not be evaluated by the model ({reason}), so the flight was treated as UNSAFE." in summary
    assert "treated as UNSAFE" in summary

