"""
app/repositories/mission.py — MongoDB I/O for the missions collection.

Document schema:
{
    "_id":                  ObjectId,
    "mission_id":           str (UUID),
    "request_id":           str,
    "drone_id":             str,
    "route":                list[dict] (e.g. [{"lat":..., "lng":...}, ...]),
    "distance_km":          float,
    "eta_minutes":          float,
    "battery_required_pct": float,
    "status":               str ("ASSIGNED", "IN_PROGRESS", "COMPLETED", "FAILED"),
    "started_at":           datetime (UTC),
}
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Optional

from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.db.database import get_database
from app.core.logging import get_logger

log = get_logger(__name__)

COLLECTION = "missions"


def _doc_to_dict(doc: dict) -> dict:
    doc["id"] = str(doc.pop("_id"))
    return doc


class MissionRepository:
    def __init__(self, db: AsyncIOMotorDatabase) -> None:
        self._col = db[COLLECTION]

    # ── Write ─────────────────────────────────────────────────────────────────

    async def create(self, data: dict) -> dict:
        """Insert a mission document and return it."""
        data.setdefault("mission_id", str(uuid.uuid4()))
        data.setdefault("status", "ASSIGNED")
        data.setdefault("started_at", datetime.now(UTC))

        result = await self._col.insert_one(data)
        log.info(
            "mission_created",
            mission_id=data["mission_id"],
            request_id=data.get("request_id"),
            drone_id=data.get("drone_id"),
        )
        doc = await self._col.find_one({"_id": result.inserted_id})
        return _doc_to_dict(doc)

    # ── Read ──────────────────────────────────────────────────────────────────

    async def get_by_id(self, mission_id: str) -> Optional[dict]:
        """Fetch by human-readable mission_id or Mongo ObjectId string."""
        try:
            oid = ObjectId(mission_id)
            doc = await self._col.find_one({"_id": oid})
            if doc:
                return _doc_to_dict(doc)
        except Exception:
            pass
            
        doc = await self._col.find_one({"mission_id": mission_id})
        return _doc_to_dict(doc) if doc else None

    async def list_recent(self, limit: int = 100) -> list[dict]:
        """Return most-recent missions, newest first."""
        cursor = self._col.find({}).sort("started_at", -1).limit(limit)
        return [_doc_to_dict(doc) async for doc in cursor]

    async def update_weather_note(self, mission_id: str, note: str) -> bool:
        """Update the weather note on a mission document."""
        query = {}
        try:
            query = {"_id": ObjectId(mission_id)}
        except Exception:
            query = {"mission_id": mission_id}

        result = await self._col.update_one(query, {"$set": {"weather.note": note}})
        return result.matched_count > 0

    # ── Indexes ───────────────────────────────────────────────────────────────

    async def ensure_indexes(self) -> None:
        await self._col.create_index("mission_id", unique=True)
        await self._col.create_index("request_id")
        await self._col.create_index("drone_id")
        await self._col.create_index("status")
        await self._col.create_index("started_at")
        log.info("mission_indexes_ensured")


def get_mission_repo() -> MissionRepository:
    return MissionRepository(get_database())
