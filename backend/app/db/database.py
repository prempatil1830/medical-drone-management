"""
MongoDB connection management using Motor (async driver).

Lifecycle:
    connect_db()  → called in FastAPI lifespan startup
    close_db()    → called in FastAPI lifespan shutdown
    get_database() → dependency / helper used by repositories

The client and database objects are stored as module-level singletons so that
Motor's internal connection pool is reused across requests.
"""

from __future__ import annotations

from typing import Optional

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase

from app.core.config import settings
from app.core.logging import get_logger

log = get_logger(__name__)

_client: Optional[AsyncIOMotorClient] = None
_database: Optional[AsyncIOMotorDatabase] = None


async def connect_db() -> None:
    """Open the Motor client and verify connectivity with a server ping."""
    global _client, _database

    log.info("db_connecting", uri=settings.MONGODB_URI, database=settings.MONGODB_DATABASE)

    _client = AsyncIOMotorClient(
        settings.MONGODB_URI,
        serverSelectionTimeoutMS=5_000,  # fail fast on bad URI
    )
    _database = _client[settings.MONGODB_DATABASE]

    # Verify the connection is actually usable at startup.
    await _client.admin.command("ping")
    log.info("db_connected", database=settings.MONGODB_DATABASE)


async def close_db() -> None:
    """Cleanly close the Motor connection pool."""
    global _client, _database

    if _client is not None:
        _client.close()
        _client = None
        _database = None
        log.info("db_disconnected")


def get_database() -> AsyncIOMotorDatabase:
    """
    Return the active database instance.

    Raises RuntimeError if called before connect_db() has succeeded.
    Intended for use in FastAPI dependency injection:

        db: AsyncIOMotorDatabase = Depends(get_database)
    """
    if _database is None:
        raise RuntimeError(
            "Database is not initialised. Ensure connect_db() ran during startup."
        )
    return _database
