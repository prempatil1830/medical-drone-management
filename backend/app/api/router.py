"""
Top-level API router.

All versioned / feature routers are registered here so that main.py
only needs to import and mount this single router.
"""

from fastapi import APIRouter

from app.api.health import router as health_router
from app.api.auth import router as auth_router
from app.api.medical_centers import router as medical_centers_router
from app.api.requests import router as requests_router
from app.api.drones import router as drones_router
from app.api.weather import router as weather_router
from app.api.missions import router as missions_router
from app.api.dashboard import router as dashboard_router
from app.api.users import router as users_router

api_router = APIRouter()

api_router.include_router(health_router)
api_router.include_router(auth_router)
api_router.include_router(medical_centers_router)
api_router.include_router(requests_router)
api_router.include_router(drones_router)
api_router.include_router(weather_router)
api_router.include_router(missions_router)
api_router.include_router(dashboard_router)
api_router.include_router(users_router)
