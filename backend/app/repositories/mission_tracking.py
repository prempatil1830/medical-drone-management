"""
app/repositories/mission_tracking.py — MongoDB I/O for the mission_trackings collection.

Document schema:
{
    "_id":                   ObjectId,
    "mission_id":            str,
    "timestamp":             datetime (UTC),
    "lat":                   float,
    "lng":                   float,
    "battery_pct":           float,
    "remaining_distance_km": float,
    "eta_minutes":           float,
    "status":                str,
}
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Optional

from motor.motor_asyncio import AsyncIOMotorDatabase

from app.db.database import get_database
from app.core.logging import get_logger

log = get_logger(__name__)

COLLECTION = "mission_trackings"


def _doc_to_dict(doc: dict) -> dict:
    doc["id"] = str(doc.pop("_id"))
    return doc


class MissionTrackingRepository:
    def __init__(self, db: AsyncIOMotorDatabase) -> None:
        self._col = db[COLLECTION]

    async def create(self, data: dict) -> dict:
        """Insert a tracking log and return it."""
        if "timestamp" not in data:
            data["timestamp"] = datetime.now(UTC)

        result = await self._col.insert_one(data)
        doc = await self._col.find_one({"_id": result.inserted_id})
        return _doc_to_dict(doc)

    async def get_by_mission(self, mission_id: str, limit: int = 500) -> list[dict]:
        """Fetch tracking logs for a mission, sorted by timestamp oldest first."""
        cursor = self._col.find({"mission_id": mission_id}).sort("timestamp", 1).limit(limit)
        return [_doc_to_dict(doc) async for doc in cursor]

    async def get_latest(self, mission_id: str) -> Optional[dict]:
        """Fetch the most recent tracking log for a mission."""
        doc = await self._col.find_one({"mission_id": mission_id}, sort=[("timestamp", -1)])
        return _doc_to_dict(doc) if doc else None

    async def ensure_indexes(self) -> None:
        await self._col.create_index("mission_id")
        await self._col.create_index("timestamp")
        log.info("mission_tracking_indexes_ensured")


def get_mission_tracking_repo() -> MissionTrackingRepository:
    return MissionTrackingRepository(get_database())
