"""
Health-check endpoint.

GET /api/health
    → 200 {"status": "ok",      "mongo": "connected"}   — Mongo reachable
    → 200 {"status": "degraded","mongo": "error: <msg>"} — Mongo unreachable

Always returns HTTP 200 so that load-balancers / orchestrators can distinguish
"app is alive but dependency is down" from "app is dead".
"""

from fastapi import APIRouter
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.db.database import get_database
from app.core.logging import get_logger

log = get_logger(__name__)

router = APIRouter(tags=["health"])


@router.get("/health", summary="Health check")
async def health_check() -> dict:
    mongo_status: str

    try:
        db: AsyncIOMotorDatabase = get_database()
        await db.command("ping")
        mongo_status = "connected"
        log.info("health_check_ok")
    except Exception as exc:
        mongo_status = f"error: {exc}"
        log.warning("health_check_degraded", error=str(exc))

    overall = "ok" if mongo_status == "connected" else "degraded"

    return {"status": overall, "mongo": mongo_status}
