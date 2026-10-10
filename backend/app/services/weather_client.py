"""
app/services/weather_client.py - Async WeatherAPI.com client.

Returns a WeatherAPIResult dataclass — NEVER raises an exception.
All failure modes (timeout, non-200, malformed payload, missing key) are
converted to WeatherAPIResult(ok=False, error="<reason>") so that the
Weather Agent remains the single decision point for failure handling.

Endpoint used: GET https://api.weatherapi.com/v1/current.json?key=<key>&q=<lat>,<lon>&aqi=no
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

import httpx

from app.core.config import settings
from app.core.logging import get_logger

log = get_logger(__name__)

# Seconds before we give up waiting for the API response.
WEATHER_API_TIMEOUT_SECONDS: float = 5.0

# Required top-level keys in a valid weatherapi.com /current.json response.
# Any absent key triggers an error result rather than a KeyError crash.
_REQUIRED_KEYS: tuple[str, ...] = ("current", "location")


@dataclass
class WeatherAPIResult:
    """
    Typed carrier for a weatherapi.com API call outcome.

    Attributes
    ----------
    ok    : True when the API returned a usable payload, False on any failure.
    data  : Raw (unprocessed) weatherapi.com JSON dict.  Present only when ok=True.
    error : Human-readable failure reason.               Present only when ok=False.
    """

    ok: bool
    data: Optional[dict[str, Any]] = None
    error: Optional[str] = None


class WeatherClient:
    """
    Thin async wrapper around the WeatherAPI.com /current.json endpoint.

    Usage
    -----
    result = await WeatherClient().fetch(lat=12.97, lng=77.59)
    if result.ok:
        raw = result.data   # keys: "location", "current"
    else:
        reason = result.error
    """

    def __init__(
        self,
        api_key: str = "",
        base_url: str = "",
        timeout: float = WEATHER_API_TIMEOUT_SECONDS,
    ) -> None:
        # Fall back to settings so callers can use the default singleton easily.
        self._api_key = api_key or settings.WEATHER_API_KEY
        self._base_url = (base_url or settings.WEATHER_API_BASE_URL).rstrip("/")
        self._timeout = timeout

    async def fetch(self, lat: float, lng: float) -> WeatherAPIResult:
        """
        Fetch current weather conditions for the given coordinates.

        Parameters
        ----------
        lat : float   Latitude  (-90 to 90)
        lng : float   Longitude (-180 to 180)

        Returns
        -------
        WeatherAPIResult — always; never raises.
        """
        if not self._api_key:
            log.warning("weather_client_no_api_key")
            return WeatherAPIResult(
                ok=False,
                error="WEATHER_API_KEY is not configured.",
            )

        url = f"{self._base_url}/current.json"
        params = {"key": self._api_key, "q": f"{lat},{lng}", "aqi": "no"}

        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.get(url, params=params)
        except httpx.TimeoutException as exc:
            log.warning("weather_client_timeout", lat=lat, lng=lng, error=str(exc))
            return WeatherAPIResult(
                ok=False,
                error=f"Weather API request timed out after {self._timeout}s.",
            )
        except httpx.RequestError as exc:
            log.warning("weather_client_request_error", lat=lat, lng=lng, error=str(exc))
            return WeatherAPIResult(
                ok=False,
                error=f"Weather API network error: {exc}",
            )

        if response.status_code != 200:
            log.warning(
                "weather_client_non_200",
                lat=lat,
                lng=lng,
                status=response.status_code,
            )
            return WeatherAPIResult(
                ok=False,
                error=(
                    f"Weather API returned HTTP {response.status_code}: "
                    f"{response.text[:200]}"
                ),
            )

        try:
            payload: dict = response.json()
        except Exception as exc:
            log.warning("weather_client_json_parse_error", lat=lat, lng=lng, error=str(exc))
            return WeatherAPIResult(
                ok=False,
                error=f"Weather API returned non-JSON response: {exc}",
            )

        # Validate that required top-level keys are present.
        missing = [k for k in _REQUIRED_KEYS if k not in payload]
        if missing:
            log.warning(
                "weather_client_missing_fields",
                lat=lat,
                lng=lng,
                missing=missing,
            )
            return WeatherAPIResult(
                ok=False,
                error=f"Weather API response missing required fields: {missing}",
            )

        # Validate that the "current" sub-block has the fields we rely on.
        current = payload.get("current", {})
        missing_current = [
            k for k in ("temp_c", "humidity", "pressure_mb", "wind_kph", "cloud", "vis_km")
            if k not in current
        ]
        if missing_current:
            log.warning(
                "weather_client_missing_current_fields",
                lat=lat,
                lng=lng,
                missing=missing_current,
            )
            return WeatherAPIResult(
                ok=False,
                error=f"Weather API 'current' block missing fields: {missing_current}",
            )

        log.info("weather_client_fetch_ok", lat=lat, lng=lng)
        return WeatherAPIResult(ok=True, data=payload)
