"""
Drone repository — all MongoDB I/O for the drones collection.
"""

from __future__ import annotations

from typing import Optional

from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.db.database import get_database
from app.core.logging import get_logger

log = get_logger(__name__)

COLLECTION = "drones"


def _doc_to_dict(doc: dict) -> dict:
    doc["id"] = str(doc.pop("_id"))
    return doc


class DroneRepository:
    def __init__(self, db: AsyncIOMotorDatabase):
        self._col = db[COLLECTION]

    # ── Read ──────────────────────────────────────────────────────────────────

    async def get_all(self) -> list[dict]:
        cursor = self._col.find({})
        return [_doc_to_dict(doc) async for doc in cursor]

    async def get_available(self) -> list[dict]:
        """Return only drones whose status is AVAILABLE."""
        cursor = self._col.find({"status": "AVAILABLE"})
        return [_doc_to_dict(doc) async for doc in cursor]

    async def get_by_id(self, drone_id: str) -> Optional[dict]:
        try:
            oid = ObjectId(drone_id)
        except Exception:
            return None
        doc = await self._col.find_one({"_id": oid})
        return _doc_to_dict(doc) if doc else None

    async def get_by_drone_id(self, drone_id: str) -> Optional[dict]:
        """Fetch a drone by its human-readable ID (e.g. BLR-D001)."""
        doc = await self._col.find_one({"drone_id": drone_id})
        return _doc_to_dict(doc) if doc else None

    # ── Write ─────────────────────────────────────────────────────────────────

    async def create(self, drone_data: dict) -> dict:
        result = await self._col.insert_one(drone_data)
        log.info("drone_created", drone_id=drone_data.get("drone_id"))
        doc = await self._col.find_one({"_id": result.inserted_id})
        return _doc_to_dict(doc)

    async def update_status(self, drone_id: str, new_status: str) -> bool:
        """Update the status of a drone by its human-readable drone_id."""
        result = await self._col.update_one(
            {"drone_id": drone_id},
            {"$set": {"status": new_status}}
        )
        if result.modified_count > 0:
            log.info("drone_status_updated", drone_id=drone_id, new_status=new_status)
            return True
        return False

    async def release_drone(
        self,
        drone_id: str,
        latitude: float,
        longitude: float,
        battery_pct: float,
        new_status: str,
    ) -> bool:
        """Atomically update location, battery, and status after mission completion."""
        result = await self._col.update_one(
            {"drone_id": drone_id},
            {"$set": {
                "latitude": latitude,
                "longitude": longitude,
                "battery_pct": max(0.0, battery_pct),
                "status": new_status,
            }},
        )
        if result.modified_count > 0:
            log.info(
                "drone_released",
                drone_id=drone_id,
                status=new_status,
                battery_pct=round(battery_pct, 2),
            )
            return True
        return False

    # ── Indexes ───────────────────────────────────────────────────────────────

    async def ensure_indexes(self) -> None:
        await self._col.create_index("drone_id", unique=True)
        await self._col.create_index("status")
        await self._col.create_index("zone")
        log.info("drone_indexes_ensured")


def get_drone_repo() -> DroneRepository:
    return DroneRepository(get_database())
