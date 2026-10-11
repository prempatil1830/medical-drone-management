"""
FastAPI application entrypoint.

Start the server:
    cd backend
    uvicorn app.main:app --reload
# Reload triggered by Antigravity on .env reload. v2
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.core.logging import configure_logging, get_logger
from app.db.database import connect_db, close_db
from app.api.router import api_router
from app.repositories.user import UserRepository
from app.repositories.medical_request import MedicalRequestRepository
from app.repositories.drone import DroneRepository
from app.repositories.weather_observation import WeatherObservationRepository
from app.repositories.agent_decision import AgentDecisionRepository
from app.repositories.mission import MissionRepository
from app.repositories.mission_tracking import MissionTrackingRepository
from app.api.websockets import router as ws_router

log = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # ── Startup ──────────────────────────────────────────────────────────────
    print(f"Using database: {settings.MONGODB_DATABASE}")
    configure_logging()
    log.info("application_startup", cors_origins=settings.CORS_ORIGINS)
    if settings.WEATHER_FORCE_CONDITION:
        log.warning(
            "weather_force_condition_active",
            forced_condition=settings.WEATHER_FORCE_CONDITION,
            message="WEATHER_FORCE_CONDITION is active! Real weather prediction is bypassed."
        )
    await connect_db()

    # Ensure DB indexes exist (idempotent)
    from app.db.database import get_database
    db = get_database()
    await UserRepository(db).ensure_indexes()
    await MedicalRequestRepository(db).ensure_indexes()
    await DroneRepository(db).ensure_indexes()
    await WeatherObservationRepository(db).ensure_indexes()
    await AgentDecisionRepository(db).ensure_indexes()
    await MissionRepository(db).ensure_indexes()
    await MissionTrackingRepository(db).ensure_indexes()
    
    # ── Handle Orphaned Missions on Restart ──────────────────────────────────
    from app.schemas.mission import MissionStatus, TERMINAL_MISSION_STATUSES
    from app.schemas.medical_request import RequestStatus
    from app.schemas.drone import DroneStatus
    from app.simulation.engine import simulation_engine
    
    orphans = await db["missions"].find({
        "status": {"$nin": list(TERMINAL_MISSION_STATUSES)}
    }).to_list(None)
    
    for orphan in orphans:
        m_id = orphan.get("mission_id")
        if not m_id:
            continue
        if m_id in simulation_engine.active_tasks and not simulation_engine.active_tasks[m_id].done():
            continue
            
        await db["missions"].update_one(
            {"mission_id": m_id},
            {"$set": {"status": MissionStatus.failed.value, "failure_reason": "server restarted"}}
        )
        
        req_id = orphan.get("request_id")
        if req_id:
            await MedicalRequestRepository(db).update_status(
                req_id, RequestStatus.failed.value, failure_reason="server restarted"
            )
            
        drone_id = orphan.get("drone_id")
        if drone_id:
            drone_repo = DroneRepository(db)
            drone = await drone_repo.get_by_drone_id(drone_id)
            last_lat = float(drone.get("latitude", 0.0)) if drone else 0.0
            last_lng = float(drone.get("longitude", 0.0)) if drone else 0.0
            last_batt = float(drone.get("battery_pct", 100.0)) if drone else 100.0
            
            last_track = await db["mission_tracking"].find_one(
                {"mission_id": m_id},
                sort=[("timestamp", -1)]
            )
            if last_track:
                last_lat = float(last_track.get("lat", last_lat))
                last_lng = float(last_track.get("lng", last_lng))
                last_batt = float(last_track.get("battery_pct", last_batt))
                
            reserve = settings.ALLOCATION_MIN_BATTERY_RESERVE_PCT
            new_drone_status = DroneStatus.available.value if last_batt >= reserve else DroneStatus.charging.value
            await drone_repo.release_drone(drone_id, last_lat, last_lng, last_batt, new_drone_status)
    
    # Start background recharge service
    from app.simulation.recharge import recharge_service
    recharge_service.start()

    yield  # application is running

    # ── Shutdown ─────────────────────────────────────────────────────────────
    log.info("application_shutdown")
    await recharge_service.stop()
    await close_db()


app = FastAPI(
    title="Medical Drone Delivery Management Platform",
    description="AI-powered medical drone delivery management and simulation.",
    version="0.1.0",
    lifespan=lifespan,
)

# ── CORS ─────────────────────────────────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Routes ───────────────────────────────────────────────────────────────────
app.include_router(api_router, prefix="/api")
app.include_router(ws_router)


# ── Database Error Handler ───────────────────────────────────────────────────
import pymongo.errors
from fastapi import Request, status
from fastapi.responses import JSONResponse


@app.exception_handler(pymongo.errors.PyMongoError)
async def pymongo_exception_handler(request: Request, exc: pymongo.errors.PyMongoError):
    log.error("database_unavailable", error=str(exc))
    return JSONResponse(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        content={"detail": "Service temporarily unavailable"},
    )
