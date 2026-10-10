"""
app/api/weather.py — Weather prediction endpoint (Phase 6).

Routes
------
POST /api/weather/predict  — fetch live weather, run ML prediction, persist observation.
                             Auth-protected.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, status

from app.api.auth import get_current_user, require_role
from app.agents.weather_agent import WeatherAgent
from app.repositories.weather_observation import (
    WeatherObservationRepository,
    get_weather_obs_repo,
)
from app.schemas.weather import WeatherPredictRequest, WeatherPredictResponse
from app.core.logging import get_logger

log = get_logger(__name__)

router = APIRouter(
    prefix="/weather",
    tags=["weather"],
    dependencies=[Depends(require_role("operator", "admin"))],
)


@router.post(
    "/predict",
    response_model=WeatherPredictResponse,
    status_code=status.HTTP_200_OK,
    summary="Predict flight condition from live weather data",
)
async def predict_weather(
    payload: WeatherPredictRequest,
    obs_repo: WeatherObservationRepository = Depends(get_weather_obs_repo),
) -> WeatherPredictResponse:
    """
    Fetch current weather for the given coordinates using the OpenWeatherMap
    API, run the flight-condition ML model, persist the observation, and
    return the prediction result.

    Always returns HTTP 200 — even when the weather API is unavailable.
    In that case, ``flight_condition`` is ``"UNSAFE"`` and ``reason``
    explains why (fail-closed: never assume it's safe to fly when weather
    data is missing).
    """
    log.info("weather_predict_request", lat=payload.lat, lng=payload.lng)

    agent = WeatherAgent()
    result = await agent.run(lat=payload.lat, lng=payload.lng, obs_repo=obs_repo)

    return WeatherPredictResponse(
        observation_id=result.observation_id,
        flight_condition=result.flight_condition,
        probability=result.probability,
        raw_weather_snapshot=result.raw_weather_snapshot,
        reason=result.reason,
    )
