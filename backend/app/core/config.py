from pathlib import Path
from typing import Annotated, List
from pydantic import AnyUrl, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict, NoDecode

# Always resolve backend/.env relative to this config file
_BACKEND_DIR = Path(__file__).resolve().parent.parent.parent
_ENV_FILE = _BACKEND_DIR / ".env"


class Settings(BaseSettings):
    """
    Application settings loaded from environment variables / .env file.
    All values are read-only after startup.
    """

    model_config = SettingsConfigDict(
        env_file=str(_ENV_FILE),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── MongoDB ──────────────────────────────────────────────────────────────
    MONGODB_URI: str = "mongodb://localhost:27017"
    MONGODB_DATABASE: str = "medical_drone_db"

    # ── Auth ─────────────────────────────────────────────────────────────────
    JWT_SECRET: str = "changeme"
    JWT_ALGORITHM: str = "HS256"
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = 1440  # 24 hours

    # ── Weather API ──────────────────────────────────────────────────────────
    WEATHER_API_KEY: str = ""
    WEATHER_API_BASE_URL: str = "https://api.weatherapi.com/v1"
    WEATHER_FORCE_CONDITION: str = ""  # Dev-only: SAFE, CAUTION, or UNSAFE

    # ── Map provider ─────────────────────────────────────────────────────────
    MAP_PROVIDER_KEY: str = ""

    # ── ML model ─────────────────────────────────────────────────────────────
    MODEL_PATH: str = "models/"

    # ── LLM Explanation Service ──────────────────────────────────────────────
    LLM_PROVIDER: str = "groq"
    LLM_API_KEY: str = ""
    LLM_MODEL: str = "openai/gpt-oss-120b"
    LLM_TIMEOUT_SECONDS: float = 5.0

    # ── Phase 7: Priority Agent ───────────────────────────────────────────────
    # Number of minutes a request must wait before its priority tier escalates
    # by one level (Normal→Medium→High→Critical; Critical stays Critical).
    PRIORITY_ESCALATION_MINUTES: int = 30
    # Comma-separated MedicalType values that are ALWAYS forced to Critical
    # priority when urgency is CRITICAL, regardless of other factors.
    PRIORITY_CRITICAL_FORCE_TYPES: str = "Blood,Organs,Emergency Medicine"

    # ── Phase 7: Allocation Agent ─────────────────────────────────────────────
    # Drone's max_range_km must be >= mission_distance * this factor.
    ALLOCATION_SAFETY_FACTOR: float = 1.25
    # Drone's battery_pct must be >= this value to be considered (percentage).
    ALLOCATION_MIN_BATTERY_RESERVE_PCT: float = 20.0
    # Recharge rate when drone is in CHARGING status (percent per minute).
    DRONE_RECHARGE_RATE_PCT_PER_MIN: float = 1.0
    # Battery percentage at which a charging drone becomes AVAILABLE again.
    DRONE_AVAILABLE_AT_PCT: float = 80.0

    # ── Phase 8: Route & Safety Agents ────────────────────────────────────────
    # Average cruise speed of the drone in km/h used for ETA calculation
    ROUTE_DRONE_CRUISE_SPEED_KMH: float = 60.0
    # Battery percentage consumed per kilometre of flight
    ROUTE_BATTERY_CONSUMPTION_PER_KM: float = 1.5

    # ── Phase 9: Simulation Engine ────────────────────────────────────────────
    # Time in seconds between simulation updates
    SIMULATION_TICK_INTERVAL_SEC: float = 1.0
    # Speed multiplier (e.g. 20 means time advances 20x faster)
    SIMULATION_SPEED_MULTIPLIER: float = 20.0

    # ── CORS ─────────────────────────────────────────────────────────────────
    # Accept either a JSON list or a comma-separated string from the env var.
    CORS_ORIGINS: Annotated[List[str], NoDecode] = ["http://localhost:5173", "http://localhost:3000"]

    @field_validator("CORS_ORIGINS", mode="before")
    @classmethod
    def parse_cors_origins(cls, v):
        if isinstance(v, str):
            return [origin.strip() for origin in v.split(",") if origin.strip()]
        return v


# Module-level singleton — import this everywhere instead of instantiating Settings().
settings = Settings()
