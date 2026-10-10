"""
MedicalCenter repository — all MongoDB I/O for the medical_centers collection.
"""

from __future__ import annotations

from typing import Optional

from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.db.database import get_database
from app.core.logging import get_logger

log = get_logger(__name__)

COLLECTION = "medical_centers"


def _doc_to_dict(doc: dict) -> dict:
    doc["id"] = str(doc.pop("_id"))
    return doc


class MedicalCenterRepository:
    def __init__(self, db: AsyncIOMotorDatabase):
        self._col = db[COLLECTION]

    # ── Read ─────────────────────────────────────────────────────────────────

    async def get_by_id(self, center_id: str) -> Optional[dict]:
        try:
            oid = ObjectId(center_id)
        except Exception:
            return None
        doc = await self._col.find_one({"_id": oid})
        return _doc_to_dict(doc) if doc else None

    async def get_all(self) -> list[dict]:
        cursor = self._col.find({})
        return [_doc_to_dict(doc) async for doc in cursor]

    # ── Write ─────────────────────────────────────────────────────────────────

    async def create(self, center_data: dict) -> dict:
        result = await self._col.insert_one(center_data)
        log.info("medical_center_created", center_id=str(result.inserted_id))
        doc = await self._col.find_one({"_id": result.inserted_id})
        return _doc_to_dict(doc)

    async def update(self, center_id: str, update_data: dict) -> Optional[dict]:
        """Apply partial update.  Returns updated doc or None if not found."""
        try:
            oid = ObjectId(center_id)
        except Exception:
            return None
        result = await self._col.find_one_and_update(
            {"_id": oid},
            {"$set": update_data},
            return_document=True,  # motor uses True for ReturnDocument.AFTER
        )
        if result:
            log.info("medical_center_updated", center_id=center_id)
            return _doc_to_dict(result)
        return None

    async def delete(self, center_id: str) -> bool:
        """Delete by id.  Returns True if a document was deleted."""
        try:
            oid = ObjectId(center_id)
        except Exception:
            return False
        result = await self._col.delete_one({"_id": oid})
        deleted = result.deleted_count > 0
        if deleted:
            log.info("medical_center_deleted", center_id=center_id)
        return deleted


def get_medical_center_repo() -> MedicalCenterRepository:
    """FastAPI dependency: resolves a MedicalCenterRepository bound to the live DB."""
    return MedicalCenterRepository(get_database())
