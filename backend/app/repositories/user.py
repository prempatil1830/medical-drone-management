"""
User repository — all MongoDB I/O for the users collection.

Uses Motor (async) exclusively.  Never returns password_hash to callers
outside this module; callers that need it must explicitly access the raw dict.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Optional

from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.db.database import get_database
from app.core.logging import get_logger

log = get_logger(__name__)

COLLECTION = "users"


def _doc_to_dict(doc: dict) -> dict:
    """Convert a raw Mongo document, normalising _id -> id (str)."""
    doc["id"] = str(doc.pop("_id"))
    return doc


class UserRepository:
    def __init__(self, db: AsyncIOMotorDatabase):
        self._col = db[COLLECTION]

    # ── Read ─────────────────────────────────────────────────────────────────

    async def get_by_email(self, email: str) -> Optional[dict]:
        """Return the raw document (including password_hash) or None."""
        doc = await self._col.find_one({"email": email})
        if doc:
            return _doc_to_dict(doc)
        return None

    async def get_by_id(self, user_id: str) -> Optional[dict]:
        """Return the raw document or None if not found / invalid ObjectId."""
        try:
            oid = ObjectId(user_id)
        except Exception:
            return None
        doc = await self._col.find_one({"_id": oid})
        if doc:
            return _doc_to_dict(doc)
        return None

    # ── Write ─────────────────────────────────────────────────────────────────

    async def create(self, user_data: dict) -> dict:
        """
        Insert a new user document.

        *user_data* must already have ``password_hash`` set and must NOT
        contain a plain ``password`` field.

        Returns the newly created document (with id as str).
        """
        user_data.setdefault("created_at", datetime.now(UTC))
        result = await self._col.insert_one(user_data)
        log.info("user_created", user_id=str(result.inserted_id))
        doc = await self._col.find_one({"_id": result.inserted_id})
        return _doc_to_dict(doc)

    async def update_center(self, user_id: str, center_id: str) -> Optional[dict]:
        """Update a user's assigned medical center."""
        try:
            oid = ObjectId(user_id)
        except Exception:
            return None
        await self._col.update_one({"_id": oid}, {"$set": {"center_id": center_id}})
        doc = await self._col.find_one({"_id": oid})
        return _doc_to_dict(doc) if doc else None

    # ── Indexes (call once at startup if desired) ─────────────────────────────

    async def ensure_indexes(self) -> None:
        """Create a unique index on email to prevent duplicate registrations."""
        await self._col.create_index("email", unique=True)
        log.info("user_indexes_ensured")


def get_user_repo() -> UserRepository:
    """FastAPI dependency: resolves a UserRepository bound to the live DB."""
    return UserRepository(get_database())
