"""
app/agents/weather_agent.py - Weather Agent for Phase 6.

Responsibilities
----------------
1. Call WeatherClient to fetch raw weatherapi.com conditions for a lat/lng.
2. Map the raw weatherapi.com fields to the exact feature dict that
   ml/predict.py's predict_flight_condition() expects.
3. Call predict_flight_condition() — the single source of ML truth.
4. Persist a weather_observation document.
5. Return a WeatherAgentResult.

Failure semantics
-----------------
The agent ALWAYS fails closed: if weather data is unavailable for ANY reason
(API down, timeout, malformed payload, missing fields), the returned
flight_condition is "UNSAFE" rather than an optimistic default.
A drone must never be assumed safe to fly when weather is unknown.
"""

from __future__ import annotations

import sys
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Optional

# Add project root to sys.path so ml/ is importable when uvicorn runs from backend/.
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from ml.predict import predict_flight_condition, WeatherInputSchema  # noqa: E402

from app.core.logging import get_logger
from app.services.weather_client import WeatherClient, WeatherAPIResult

log = get_logger(__name__)

# ── ML field names (single source of truth pulled from the schema) ────────────
_EXPECTED_ML_FIELDS: frozenset[str] = frozenset(WeatherInputSchema.model_fields.keys())


# ── Result dataclass ──────────────────────────────────────────────────────────


@dataclass
class WeatherAgentResult:
    """
    Outcome of a Weather Agent run.

    Attributes
    ----------
    flight_condition    : "SAFE" | "CAUTION" | "UNSAFE"
    probability         : Model confidence in [0, 1].  0.0 on failure.
    raw_weather_snapshot: Raw weatherapi.com JSON dict, or None on API failure.
    observation_id      : UUID of the persisted weather_observations document.
    reason              : Human-readable explanation — set only on failure.
    """

    flight_condition: str
    probability: float
    raw_weather_snapshot: Optional[dict[str, Any]]
    observation_id: str
    reason: Optional[str] = None


# ── weatherapi.com → ML feature mapping ─────────────────────────────────────


def map_weatherapi_to_ml_features(raw: dict[str, Any]) -> dict[str, Any]:
    """
    Convert a raw weatherapi.com /current.json response dict to the exact
    feature dictionary that predict_flight_condition() expects.

    All 13 fields required by WeatherInputSchema are produced here.
    Raises KeyError / ValueError if any non-optional field is absent.

    Field-by-field mapping
    ----------------------
    current.temp_c              → temperature_c       (direct, already Celsius)
    current.humidity            → humidity_pct         (direct)
    current.precip_mm           → precipitation_mm     (0.0 if absent)
    current.wind_kph            → wind_speed_kmh       (direct, already km/h)
    current.gust_kph (opt)      → wind_gust_kmh        (fallback to wind_speed_kmh)
    current.wind_degree         → wind_direction_deg   (direct)
    current.vis_km              → visibility_km        (direct)
    current.pressure_mb         → pressure_hpa         (direct, mb == hPa)
    current.cloud               → cloud_cover_pct      (direct)
    current.dewpoint_c (opt)    → dew_point_c          (Magnus approx fallback)
    current.uv                  → uv_index             (direct)
    current.condition.text      → weather_condition    (direct string)
    Derived from precip > 0     → rain_event           (int 0 or 1)
    """
    current = raw["current"]

    temperature_c: float = float(current["temp_c"])
    humidity_pct: float = float(current["humidity"])
    pressure_hpa: float = float(current["pressure_mb"])

    # precip_mm may be absent on some plans; default to 0.0
    precipitation_mm: float = float(current.get("precip_mm", 0.0))

    wind_speed_kmh: float = float(current["wind_kph"])

    gust_kph = current.get("gust_kph")
    wind_gust_kmh: float = float(gust_kph) if gust_kph is not None else wind_speed_kmh

    wind_direction_deg: float = float(current.get("wind_degree", 0.0))
    visibility_km: float = float(current["vis_km"])
    cloud_cover_pct: float = float(current["cloud"])

    # WeatherAPI.com provides dew point directly; fall back to Magnus approx.
    dew_point_raw = current.get("dewpoint_c")
    dew_point_c: float = (
        float(dew_point_raw)
        if dew_point_raw is not None
        else temperature_c - ((100.0 - humidity_pct) / 5.0)
    )

    # UV index is provided directly by weatherapi.com.
    uv_index: float = float(current.get("uv", 0.0))

    condition = current.get("condition", {})
    weather_condition: str = str(condition.get("text", "Unknown"))
    rain_event: int = 1 if precipitation_mm > 0.0 else 0

    mapped = {
        "temperature_c": temperature_c,
        "humidity_pct": humidity_pct,
        "precipitation_mm": precipitation_mm,
        "wind_speed_kmh": wind_speed_kmh,
        "wind_gust_kmh": wind_gust_kmh,
        "wind_direction_deg": wind_direction_deg,
        "visibility_km": visibility_km,
        "pressure_hpa": pressure_hpa,
        "cloud_cover_pct": cloud_cover_pct,
        "dew_point_c": dew_point_c,
        "uv_index": uv_index,
        "weather_condition": weather_condition,
        "rain_event": rain_event,
    }

    # Loud consistency check: every field the ML schema expects must be present.
    missing = _EXPECTED_ML_FIELDS - mapped.keys()
    if missing:
        raise ValueError(
            f"Feature mapping is incomplete — missing ML fields: {sorted(missing)}"
        )
    extra = mapped.keys() - _EXPECTED_ML_FIELDS
    if extra:
        raise ValueError(
            f"Feature mapping produced unexpected fields: {sorted(extra)}"
        )

    return mapped


# ── Weather Agent ─────────────────────────────────────────────────────────────


class WeatherAgent:
    """
    Orchestrates a single weather-to-prediction pipeline run.

    Parameters
    ----------
    client : WeatherClient instance (injectable for testing).
    """

    def __init__(self, client: Optional[WeatherClient] = None) -> None:
        self._client = client or WeatherClient()

    async def run(
        self,
        lat: float,
        lng: float,
        obs_repo: Any,  # WeatherObservationRepository — typed loosely to avoid circular import
    ) -> WeatherAgentResult:
        """
        Fetch weather, predict flight condition, persist observation, return result.

        Always returns a WeatherAgentResult — never raises.
        On any failure the flight_condition is "UNSAFE".
        """
        observation_id = str(uuid.uuid4())
        now = datetime.now(UTC)

        # ── Dev-only Demo Switch: WEATHER_FORCE_CONDITION ─────────────────────
        from app.core.config import settings
        force_cond = (settings.WEATHER_FORCE_CONDITION or "").strip().upper()
        if force_cond in ("SAFE", "CAUTION", "UNSAFE"):
            forced_reason = "Forced by WEATHER_FORCE_CONDITION (demo)"
            prob = 1.0 if force_cond == "SAFE" else (0.75 if force_cond == "CAUTION" else 0.0)
            log.warning("weather_agent_condition_forced", condition=force_cond, lat=lat, lng=lng)
            await self._persist(
                obs_repo=obs_repo,
                observation_id=observation_id,
                lat=lat,
                lng=lng,
                timestamp=now,
                raw_snapshot={"demo_forced": True},
                flight_condition=force_cond,
                probability=prob,
                reason=forced_reason,
            )
            return WeatherAgentResult(
                flight_condition=force_cond,
                probability=prob,
                raw_weather_snapshot={"demo_forced": True},
                observation_id=observation_id,
                reason=forced_reason,
            )

        # ── Step 1: Fetch from OWM ────────────────────────────────────────────
        api_result: WeatherAPIResult = await self._client.fetch(lat=lat, lng=lng)

        if not api_result.ok:
            log.warning(
                "weather_agent_api_failure",
                lat=lat,
                lng=lng,
                reason=api_result.error,
            )
            await self._persist(
                obs_repo=obs_repo,
                observation_id=observation_id,
                lat=lat,
                lng=lng,
                timestamp=now,
                raw_snapshot=None,
                flight_condition="UNSAFE",
                probability=0.0,
                reason=api_result.error,
            )
            return WeatherAgentResult(
                flight_condition="UNSAFE",
                probability=0.0,
                raw_weather_snapshot=None,
                observation_id=observation_id,
                reason=api_result.error,
            )

        raw: dict = api_result.data  # type: ignore[assignment]

        # ── Step 2: Map weatherapi.com fields → ML feature dict ───────────────
        try:
            ml_features = map_weatherapi_to_ml_features(raw)
        except Exception as exc:
            reason = f"Feature mapping failed: {exc}"
            log.warning("weather_agent_mapping_failure", lat=lat, lng=lng, error=str(exc))
            await self._persist(
                obs_repo=obs_repo,
                observation_id=observation_id,
                lat=lat,
                lng=lng,
                timestamp=now,
                raw_snapshot=raw,
                flight_condition="UNSAFE",
                probability=0.0,
                reason=reason,
            )
            return WeatherAgentResult(
                flight_condition="UNSAFE",
                probability=0.0,
                raw_weather_snapshot=raw,
                observation_id=observation_id,
                reason=reason,
            )

        # ── Step 3: Run ML prediction ─────────────────────────────────────────
        try:
            prediction = predict_flight_condition(ml_features)
        except Exception as exc:
            reason = f"ML prediction failed: {exc}"
            log.warning("weather_agent_ml_failure", lat=lat, lng=lng, error=str(exc))
            await self._persist(
                obs_repo=obs_repo,
                observation_id=observation_id,
                lat=lat,
                lng=lng,
                timestamp=now,
                raw_snapshot=raw,
                flight_condition="UNSAFE",
                probability=0.0,
                reason=reason,
            )
            return WeatherAgentResult(
                flight_condition="UNSAFE",
                probability=0.0,
                raw_weather_snapshot=raw,
                observation_id=observation_id,
                reason=reason,
            )

        flight_condition: str = prediction["flight_condition"]
        probability: float = prediction["probability"]

        log.info(
            "weather_agent_prediction_ok",
            lat=lat,
            lng=lng,
            flight_condition=flight_condition,
            probability=round(probability, 4),
        )

        # ── Step 4: Persist observation ───────────────────────────────────────
        await self._persist(
            obs_repo=obs_repo,
            observation_id=observation_id,
            lat=lat,
            lng=lng,
            timestamp=now,
            raw_snapshot=raw,
            flight_condition=flight_condition,
            probability=probability,
            reason=None,
        )

        return WeatherAgentResult(
            flight_condition=flight_condition,
            probability=probability,
            raw_weather_snapshot=raw,
            observation_id=observation_id,
            reason=None,
        )

    # ── Private helpers ───────────────────────────────────────────────────────

    @staticmethod
    async def _persist(
        obs_repo: Any,
        observation_id: str,
        lat: float,
        lng: float,
        timestamp: datetime,
        raw_snapshot: Optional[dict],
        flight_condition: str,
        probability: float,
        reason: Optional[str],
    ) -> None:
        """Write an observation doc. Log but swallow any storage error."""
        try:
            doc = {
                "observation_id": observation_id,
                "lat": lat,
                "lng": lng,
                "timestamp": timestamp,
                "raw_weather_snapshot": raw_snapshot,
                "flight_condition": flight_condition,
                "probability": probability,
                "reason": reason,
            }
            await obs_repo.create(doc)
        except Exception as exc:
            log.error(
                "weather_agent_persist_error",
                observation_id=observation_id,
                error=str(exc),
            )
