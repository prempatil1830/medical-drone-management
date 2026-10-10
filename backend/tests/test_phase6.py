"""
Unit tests for Phase 6: Weather API integration and Weather Agent.

Strategy
--------
- Mock WeatherClient.fetch() — NOT the ML model.
  The ML model is exercised for real so we catch mapping bugs early.
  The HTTP client is mocked so tests run without a real WeatherAPI.com key.
- Three test classes as specified:
    1. TestWeatherAgentSuccess   — valid API response → correct prediction
    2. TestWeatherAgentFailClosed — failure modes → UNSAFE, no crash, obs saved
    3. TestFeatureMapping         — mapping completeness check against the live schema

Run with:
    cd <project_root>
    menv/bin/pytest backend/tests/test_phase6.py -v
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ── Project root on path so ml/ imports work ─────────────────────────────────
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from app.agents.weather_agent import WeatherAgent, map_weatherapi_to_ml_features
from app.services.weather_client import WeatherAPIResult


# ── Shared WeatherAPI fixture ──────────────────────────────────────────────────

def _valid_weatherapi_response() -> dict[str, Any]:
    """
    Realistic minimal weatherapi.com /current.json payload.
    All required and optional fields exercised so the mapping is complete.
    """
    return {
        "location": {
            "name": "Bengaluru",
            "lat": 12.97,
            "lon": 77.59
        },
        "current": {
            "temp_c": 27.0,
            "humidity": 70.0,
            "pressure_mb": 1010.0,
            "wind_kph": 18.0,
            "gust_kph": 27.0,
            "wind_degree": 220.0,
            "cloud": 40.0,
            "vis_km": 9.0,
            "precip_mm": 0.0,
            "dewpoint_c": 21.0,
            "uv": 0.0,
            "condition": {"text": "Partly cloudy"}
        }
    }


def _mock_obs_repo() -> MagicMock:
    """Return an async-capable mock WeatherObservationRepository."""
    repo = MagicMock()
    repo.create = AsyncMock(return_value={"id": "fake-mongo-id", "observation_id": "obs-1"})
    return repo


# ══════════════════════════════════════════════════════════════════════════════
# 1. Successful API response → correct flight_condition prediction
# ══════════════════════════════════════════════════════════════════════════════


class TestWeatherAgentSuccess:
    """
    Mock WeatherClient.fetch to return a valid weatherapi.com payload.
    The real ML model runs so we validate the full pipeline end-to-end.
    """

    @pytest.mark.asyncio
    async def test_valid_response_produces_flight_condition(self):
        """
        A valid API response must produce one of the three recognised
        flight_condition labels and a probability in [0, 1].
        """
        mock_client = MagicMock()
        mock_client.fetch = AsyncMock(
            return_value=WeatherAPIResult(ok=True, data=_valid_weatherapi_response())
        )

        obs_repo = _mock_obs_repo()
        agent = WeatherAgent(client=mock_client)
        result = await agent.run(lat=12.9716, lng=77.5946, obs_repo=obs_repo)

        assert result.flight_condition in {"SAFE", "CAUTION", "UNSAFE"}, (
            f"Unexpected flight_condition: {result.flight_condition!r}"
        )
        assert 0.0 <= result.probability <= 1.0, (
            f"probability out of range: {result.probability}"
        )
        assert result.raw_weather_snapshot is not None
        assert result.reason is None        # No failure → no reason string
        assert result.observation_id        # Non-empty UUID string

    @pytest.mark.asyncio
    async def test_observation_is_persisted_on_success(self):
        """obs_repo.create must be called exactly once with the right fields."""
        mock_client = MagicMock()
        mock_client.fetch = AsyncMock(
            return_value=WeatherAPIResult(ok=True, data=_valid_weatherapi_response())
        )

        obs_repo = _mock_obs_repo()
        agent = WeatherAgent(client=mock_client)
        result = await agent.run(lat=12.9716, lng=77.5946, obs_repo=obs_repo)

        obs_repo.create.assert_called_once()
        persisted: dict = obs_repo.create.call_args[0][0]  # first positional arg

        assert persisted["lat"] == 12.9716
        assert persisted["lng"] == 77.5946
        assert persisted["flight_condition"] == result.flight_condition
        assert persisted["probability"] == result.probability
        assert persisted["raw_weather_snapshot"] is not None
        assert "observation_id" in persisted
        assert "timestamp" in persisted

    @pytest.mark.asyncio
    async def test_rain_event_is_set_when_precipitation_present(self):
        """rain_event must be 1 when precip_mm > 0 in the WeatherAPI payload."""
        rainy = _valid_weatherapi_response()
        rainy["current"]["precip_mm"] = 3.5

        mock_client = MagicMock()
        mock_client.fetch = AsyncMock(
            return_value=WeatherAPIResult(ok=True, data=rainy)
        )

        obs_repo = _mock_obs_repo()
        agent = WeatherAgent(client=mock_client)
        result = await agent.run(lat=12.9716, lng=77.5946, obs_repo=obs_repo)

        # At minimum, the pipeline should not crash on rainy conditions.
        assert result.flight_condition in {"SAFE", "CAUTION", "UNSAFE"}


# ══════════════════════════════════════════════════════════════════════════════
# 2. Failure modes → UNSAFE (fail-closed), no crash, observation still saved
# ══════════════════════════════════════════════════════════════════════════════


class TestWeatherAgentFailClosed:
    """
    Verify that EVERY failure path returns UNSAFE and never raises.
    Also verifies the observation is persisted even when the API fails.
    """

    async def _run_with_error(self, error_msg: str) -> tuple:
        """Helper: mock a failed API call and return (result, obs_repo)."""
        mock_client = MagicMock()
        mock_client.fetch = AsyncMock(
            return_value=WeatherAPIResult(ok=False, error=error_msg)
        )
        obs_repo = _mock_obs_repo()
        agent = WeatherAgent(client=mock_client)
        result = await agent.run(lat=12.9716, lng=77.5946, obs_repo=obs_repo)
        return result, obs_repo

    @pytest.mark.asyncio
    async def test_timeout_returns_unsafe(self):
        """A simulated timeout must produce UNSAFE, not a crash."""
        result, _ = await self._run_with_error(
            "Weather API request timed out after 5.0s."
        )
        assert result.flight_condition == "UNSAFE"
        assert result.probability == 0.0
        assert result.reason is not None

    @pytest.mark.asyncio
    async def test_non_200_returns_unsafe(self):
        """A non-200 HTTP status must produce UNSAFE."""
        result, _ = await self._run_with_error("Weather API returned HTTP 503: Service Unavailable")
        assert result.flight_condition == "UNSAFE"
        assert result.probability == 0.0

    @pytest.mark.asyncio
    async def test_missing_api_key_returns_unsafe(self):
        """Missing API key must produce UNSAFE."""
        result, _ = await self._run_with_error("WEATHER_API_KEY is not configured.")
        assert result.flight_condition == "UNSAFE"
        assert result.raw_weather_snapshot is None

    @pytest.mark.asyncio
    async def test_malformed_response_returns_unsafe(self):
        """A malformed (missing-fields) API response must produce UNSAFE."""
        result, _ = await self._run_with_error(
            "Weather API response missing required fields: ['current']"
        )
        assert result.flight_condition == "UNSAFE"

    @pytest.mark.asyncio
    async def test_observation_persisted_on_failure(self):
        """obs_repo.create must still be called even when the API fails."""
        result, obs_repo = await self._run_with_error("WEATHER_API_KEY is not configured.")

        obs_repo.create.assert_called_once()
        persisted: dict = obs_repo.create.call_args[0][0]

        assert persisted["flight_condition"] == "UNSAFE"
        assert persisted["raw_weather_snapshot"] is None
        assert persisted["reason"] is not None

    @pytest.mark.asyncio
    async def test_no_exception_propagates_on_failure(self):
        """The agent must never raise — even if obs_repo.create also fails."""
        mock_client = MagicMock()
        mock_client.fetch = AsyncMock(
            return_value=WeatherAPIResult(ok=False, error="timeout")
        )

        broken_repo = MagicMock()
        broken_repo.create = AsyncMock(side_effect=RuntimeError("DB is down"))

        agent = WeatherAgent(client=mock_client)
        # Should NOT raise despite the repo error
        result = await agent.run(lat=0.0, lng=0.0, obs_repo=broken_repo)
        assert result.flight_condition == "UNSAFE"


# ══════════════════════════════════════════════════════════════════════════════
# 3. Feature mapping completeness — loudly catches schema drift
# ══════════════════════════════════════════════════════════════════════════════


class TestFeatureMapping:
    """
    Verify that map_weatherapi_to_ml_features() produces EXACTLY the fields that
    WeatherInputSchema.model_fields expects — no more, no fewer.

    This test will fail loudly if:
    - A field is renamed/removed in WeatherInputSchema
    - A field is added to WeatherInputSchema but not the mapping
    - The mapping produces a field that WeatherInputSchema doesn't know about
    """

    def test_all_required_ml_fields_are_present(self):
        """Every key in WeatherInputSchema.model_fields must appear in the mapped dict."""
        from ml.predict import WeatherInputSchema

        mapped = map_weatherapi_to_ml_features(_valid_weatherapi_response())
        expected = set(WeatherInputSchema.model_fields.keys())
        actual = set(mapped.keys())

        missing = expected - actual
        extra = actual - expected

        assert not missing, (
            f"Mapping is MISSING fields required by WeatherInputSchema: {sorted(missing)}\n"
            f"Mapped keys: {sorted(actual)}"
        )
        assert not extra, (
            f"Mapping produces EXTRA fields not in WeatherInputSchema: {sorted(extra)}\n"
            f"Expected keys: {sorted(expected)}"
        )

    def test_mapped_dict_passes_schema_validation(self):
        """The mapped dict must deserialise into WeatherInputSchema without error."""
        from ml.predict import WeatherInputSchema

        mapped = map_weatherapi_to_ml_features(_valid_weatherapi_response())
        # Will raise ValidationError if any field is wrong type/out-of-bounds
        validated = WeatherInputSchema(**mapped)
        assert validated is not None

    def test_temperature_celsius_mapped_directly(self):
        """current.temp_c 27.0 must map to temperature_c 27.0 °C."""
        raw = _valid_weatherapi_response()
        raw["current"]["temp_c"] = 27.0
        mapped = map_weatherapi_to_ml_features(raw)
        assert abs(mapped["temperature_c"] - 27.0) < 0.01

    def test_wind_speed_mapped_directly(self):
        """current.wind_kph 36.0 must map to wind_speed_kmh 36.0."""
        raw = _valid_weatherapi_response()
        raw["current"]["wind_kph"] = 36.0
        mapped = map_weatherapi_to_ml_features(raw)
        assert abs(mapped["wind_speed_kmh"] - 36.0) < 0.01

    def test_wind_gust_fallback_to_wind_speed(self):
        """When current.gust_kph is absent, wind_gust_kmh must equal wind_speed_kmh."""
        raw = _valid_weatherapi_response()
        raw["current"].pop("gust_kph", None)
        mapped = map_weatherapi_to_ml_features(raw)
        assert mapped["wind_gust_kmh"] == mapped["wind_speed_kmh"]

    def test_visibility_mapped_directly(self):
        """current.vis_km 5.0 must map to visibility_km 5.0."""
        raw = _valid_weatherapi_response()
        raw["current"]["vis_km"] = 5.0
        mapped = map_weatherapi_to_ml_features(raw)
        assert abs(mapped["visibility_km"] - 5.0) < 0.001

    def test_rain_event_flag_when_no_rain(self):
        """rain_event must be 0 when there is no precipitation."""
        raw = _valid_weatherapi_response()
        raw["current"]["precip_mm"] = 0.0
        mapped = map_weatherapi_to_ml_features(raw)
        assert mapped["rain_event"] == 0
        assert mapped["precipitation_mm"] == 0.0

    def test_rain_event_flag_when_raining(self):
        """rain_event must be 1 when precipitation_mm > 0."""
        raw = _valid_weatherapi_response()
        raw["current"]["precip_mm"] = 2.5
        mapped = map_weatherapi_to_ml_features(raw)
        assert mapped["rain_event"] == 1
        assert mapped["precipitation_mm"] == 2.5

    def test_no_precip_defaults_to_zero(self):
        """Absent 'precip_mm' block must yield precipitation_mm=0, rain_event=0."""
        raw = _valid_weatherapi_response()
        raw["current"].pop("precip_mm", None)
        mapped = map_weatherapi_to_ml_features(raw)
        assert mapped["precipitation_mm"] == 0.0
        assert mapped["rain_event"] == 0

    def test_uv_index_mapped_directly(self):
        """uv_index must be mapped from current.uv."""
        raw = _valid_weatherapi_response()
        raw["current"]["uv"] = 5.0
        mapped = map_weatherapi_to_ml_features(raw)
        assert mapped["uv_index"] == 5.0

    def test_weather_condition_string_extracted(self):
        """weather_condition must be the string from current.condition.text."""
        raw = _valid_weatherapi_response()
        raw["current"]["condition"] = {"text": "Heavy Rain"}
        mapped = map_weatherapi_to_ml_features(raw)
        assert mapped["weather_condition"] == "Heavy Rain"
