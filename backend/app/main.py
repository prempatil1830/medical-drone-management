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
from app.repositories.mission_tracking import MissionTrackingRepository
from app.api.websockets import router as ws_router

log = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # ── Startup ──────────────────────────────────────────────────────────────
    configure_logging()
    log.info("application_startup", cors_origins=settings.CORS_ORIGINS)
    await connect_db()

    # Ensure DB indexes exist (idempotent)
    from app.db.database import get_database
    db = get_database()
    await UserRepository(db).ensure_indexes()
    await MedicalRequestRepository(db).ensure_indexes()
    await DroneRepository(db).ensure_indexes()
    await WeatherObservationRepository(db).ensure_indexes()
    await AgentDecisionRepository(db).ensure_indexes()
    await MissionTrackingRepository(db).ensure_indexes()
    
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
