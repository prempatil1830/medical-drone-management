"""
MedicalRequest repository — all MongoDB I/O for the medical_requests collection.
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

COLLECTION = "medical_requests"


def _doc_to_dict(doc: dict) -> dict:
    doc["id"] = str(doc.pop("_id"))
    return doc


class MedicalRequestRepository:
    def __init__(self, db: AsyncIOMotorDatabase):
        self._col = db[COLLECTION]

    # ── Read ──────────────────────────────────────────────────────────────────

    async def get_by_id(self, request_id: str) -> Optional[dict]:
        try:
            oid = ObjectId(request_id)
        except Exception:
            return None
        doc = await self._col.find_one({"_id": oid})
        return _doc_to_dict(doc) if doc else None

    async def list_requests(
        self,
        status: Optional[str] = None,
        center_id: Optional[str] = None,
        urgency: Optional[str] = None,
        skip: int = 0,
        limit: int = 50,
    ) -> list[dict]:
        """
        List medical requests with optional filters.

        Pagination parameters
        ---------------------
        skip  : number of documents to skip (offset).  Default 0.
        limit : max documents to return.  Hard-capped at 200 to prevent
                unbounded queries silently hammering the DB.
        """
        query: dict = {}
        if status:
            query["status"] = status
        if center_id:
            query["center_id"] = center_id
        if urgency:
            query["urgency"] = urgency

        # Hard cap — no single call should return more than 200 documents.
        safe_limit = min(limit, 200)

        cursor = self._col.find(query).skip(skip).limit(safe_limit)
        return [_doc_to_dict(doc) async for doc in cursor]

    # ── Write ─────────────────────────────────────────────────────────────────

    async def create(self, data: dict) -> dict:
        data.setdefault("request_id", str(uuid.uuid4()))
        data.setdefault("status", "PENDING")
        data.setdefault("created_at", datetime.now(UTC))

        result = await self._col.insert_one(data)
        log.info("medical_request_created", request_id=data["request_id"])
        doc = await self._col.find_one({"_id": result.inserted_id})
        return _doc_to_dict(doc)

    async def update_status(
        self,
        request_id: str,
        new_status: str,
        mission_id: Optional[str] = None,
        priority_tier: Optional[str] = None,
        priority_score: Optional[float] = None,
        assigned_drone_id: Optional[str] = None,
    ) -> bool:
        """Update request status, mission_id, priority metadata, and assigned drone."""
        query = {}
        try:
            query = {"_id": ObjectId(request_id)}
        except Exception:
            query = {"request_id": request_id}

        update_doc: dict = {"status": new_status}
        if mission_id is not None:
            update_doc["mission_id"] = mission_id
        if priority_tier is not None:
            update_doc["priority_tier"] = priority_tier
        if priority_score is not None:
            update_doc["priority_score"] = priority_score
        if assigned_drone_id is not None:
            update_doc["assigned_drone_id"] = assigned_drone_id

        result = await self._col.update_one(query, {"$set": update_doc})
        if result.matched_count > 0:
            log.info("medical_request_status_updated", request_id=request_id, status=new_status)
            return True
        return False

    # ── Indexes ───────────────────────────────────────────────────────────────

    async def ensure_indexes(self) -> None:
        await self._col.create_index("center_id")
        await self._col.create_index("status")
        await self._col.create_index("urgency")
        await self._col.create_index("created_at")
        log.info("medical_request_indexes_ensured")


def get_request_repo() -> MedicalRequestRepository:
    return MedicalRequestRepository(get_database())
