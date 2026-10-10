"""
app/repositories/weather_observation.py — MongoDB I/O for weather_observations.

Document schema
---------------
{
    "_id":                  ObjectId,
    "observation_id":       str (UUID),
    "lat":                  float,
    "lng":                  float,
    "timestamp":            datetime (UTC),
    "raw_weather_snapshot": dict | None,
    "flight_condition":     "SAFE" | "CAUTION" | "UNSAFE",
    "probability":          float,
    "reason":               str | None   -- set only on API/mapping failure
}
"""

from __future__ import annotations

from typing import Optional

from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.db.database import get_database
from app.core.logging import get_logger

log = get_logger(__name__)

COLLECTION = "weather_observations"


def _doc_to_dict(doc: dict) -> dict:
    doc["id"] = str(doc.pop("_id"))
    return doc


class WeatherObservationRepository:
    def __init__(self, db: AsyncIOMotorDatabase) -> None:
        self._col = db[COLLECTION]

    # ── Write ─────────────────────────────────────────────────────────────────

    async def create(self, data: dict) -> dict:
        """Insert a weather observation document and return it with id as str."""
        result = await self._col.insert_one(data)
        log.info(
            "weather_observation_created",
            observation_id=data.get("observation_id"),
            flight_condition=data.get("flight_condition"),
        )
        doc = await self._col.find_one({"_id": result.inserted_id})
        return _doc_to_dict(doc)

    # ── Read ──────────────────────────────────────────────────────────────────

    async def get_by_id(self, observation_id: str) -> Optional[dict]:
        doc = await self._col.find_one({"observation_id": observation_id})
        return _doc_to_dict(doc) if doc else None

    async def list_recent(self, limit: int = 50) -> list[dict]:
        """Return most-recent observations, newest first."""
        cursor = self._col.find({}).sort("timestamp", -1).limit(limit)
        return [_doc_to_dict(doc) async for doc in cursor]

    # ── Indexes ───────────────────────────────────────────────────────────────

    async def ensure_indexes(self) -> None:
        await self._col.create_index("observation_id", unique=True, sparse=True)
        await self._col.create_index("timestamp")
        await self._col.create_index([("lat", 1), ("lng", 1)])
        log.info("weather_observation_indexes_ensured")


def get_weather_obs_repo() -> WeatherObservationRepository:
    return WeatherObservationRepository(get_database())
