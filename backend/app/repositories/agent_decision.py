"""
app/repositories/agent_decision.py — MongoDB I/O for the agent_decisions collection.

Document schema (stored per agent call, including failures/rejections)
----------------------------------------------------------------------
{
    "_id":            ObjectId,
    "decision_id":    str (UUID4),
    "agent_name":     "PriorityAgent" | "AllocationAgent",
    "request_id":     str,
    "decision":       str,   # e.g. "Critical", drone_id, "NO_FEASIBLE_DRONE"
    "score":          float | None,  # None for PriorityAgent
    "reason":         str,
    "input_snapshot": dict,   # sanitised copy of inputs at call time
    "timestamp":      datetime (UTC),
}

This collection is append-only (decisions are never updated, only added).
It provides the full audit trail required for explainability.
"""

from __future__ import annotations

from typing import Optional

from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.db.database import get_database
from app.core.logging import get_logger

log = get_logger(__name__)

COLLECTION = "agent_decisions"


def _doc_to_dict(doc: dict) -> dict:
    if not doc:
        return {}
    doc = dict(doc)
    doc["id"] = str(doc.pop("_id", ""))
    return doc


class AgentDecisionRepository:
    def __init__(self, db: AsyncIOMotorDatabase) -> None:
        self._col = db[COLLECTION]

    # ── Write ─────────────────────────────────────────────────────────────────

    async def create(self, data: dict) -> dict:
        """Insert an agent decision document and return it with id as str."""
        result = await self._col.insert_one(data)
        log.info(
            "agent_decision_created",
            decision_id=data.get("decision_id"),
            agent_name=data.get("agent_name"),
            decision=data.get("decision"),
        )
        inserted_id = getattr(result, "inserted_id", None)
        doc = await self._col.find_one({"_id": inserted_id}) if inserted_id else None
        return _doc_to_dict(doc) if doc else data

    # ── Read ──────────────────────────────────────────────────────────────────

    async def get_by_decision_id(self, decision_id: str) -> Optional[dict]:
        doc = await self._col.find_one({"decision_id": decision_id})
        return _doc_to_dict(doc) if doc else None

    async def list_by_request(self, request_id: str) -> list[dict]:
        """Return all agent decisions for a given request, oldest first."""
        cursor = self._col.find({"request_id": request_id}).sort("timestamp", 1)
        res = [_doc_to_dict(doc) async for doc in cursor]
        return res

    async def list_recent(self, limit: int = 100) -> list[dict]:
        """Return most-recent decisions, newest first."""
        cursor = self._col.find({}).sort("timestamp", -1).limit(limit)
        return [_doc_to_dict(doc) async for doc in cursor]

    # ── Indexes ───────────────────────────────────────────────────────────────

    async def ensure_indexes(self) -> None:
        await self._col.create_index("decision_id", unique=True, sparse=True)
        await self._col.create_index("request_id")
        await self._col.create_index("agent_name")
        await self._col.create_index("timestamp")
        log.info("agent_decision_indexes_ensured")


def get_agent_decision_repo() -> AgentDecisionRepository:
    return AgentDecisionRepository(get_database())
