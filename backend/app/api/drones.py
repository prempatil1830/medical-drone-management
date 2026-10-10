"""
Drone fleet endpoints — all routes require authentication.

Routes
------
GET /api/drones            — list entire fleet
GET /api/drones/available  — list only AVAILABLE drones

Note: drone creation is handled by the seed script, not a public API endpoint.
Phase 5+ will add status-update endpoints when dispatch logic is introduced.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.auth import get_current_user, require_role
from app.core.logging import get_logger
from app.repositories.drone import DroneRepository, get_drone_repo
from app.schemas.drone import DroneResponse, DroneStatusUpdate

log = get_logger(__name__)

router = APIRouter(
    prefix="/drones",
    tags=["drones"],
    dependencies=[Depends(require_role("operator", "admin"))],
)


# ── List all ──────────────────────────────────────────────────────────────────


@router.get(
    "/",
    response_model=list[DroneResponse],
    summary="List all drones in the fleet",
)
async def list_drones(
    repo: DroneRepository = Depends(get_drone_repo),
) -> list[DroneResponse]:
    drones = await repo.get_all()
    return [DroneResponse(**d) for d in drones]


# ── Available only ────────────────────────────────────────────────────────────


@router.get(
    "/available",
    response_model=list[DroneResponse],
    summary="List only available (ready-to-dispatch) drones",
)
async def list_available_drones(
    repo: DroneRepository = Depends(get_drone_repo),
) -> list[DroneResponse]:
    """Returns drones whose status is exactly ``AVAILABLE``."""
    drones = await repo.get_available()
    return [DroneResponse(**d) for d in drones]

@router.patch(
    "/{drone_id}/status",
    response_model=DroneResponse,
    summary="Update drone status (admin only)",
    dependencies=[Depends(require_role("admin"))],
)
async def update_drone_status(
    drone_id: str,
    update_in: DroneStatusUpdate,
    repo: DroneRepository = Depends(get_drone_repo),
) -> DroneResponse:
    from app.schemas.drone import DroneStatusUpdate
    drone = await repo.get_by_drone_id(drone_id)
    if not drone:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Drone not found")
        
    current_status = drone["status"]
    new_status = update_in.status.value
    
    # Valid transitions:
    # MAINTENANCE -> AVAILABLE, CHARGING, OFFLINE
    # OFFLINE -> AVAILABLE, MAINTENANCE
    # CHARGING -> AVAILABLE
    valid = False
    if current_status == "MAINTENANCE" and new_status in ("AVAILABLE", "CHARGING", "OFFLINE"):
        valid = True
    elif current_status == "OFFLINE" and new_status in ("AVAILABLE", "MAINTENANCE"):
        valid = True
    elif current_status == "CHARGING" and new_status in ("AVAILABLE", "MAINTENANCE"):
        valid = True
        
    if not valid:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, 
            f"Invalid transition from {current_status} to {new_status}"
        )
        
    await repo.update_status(drone_id, new_status)
    updated = await repo.get_by_drone_id(drone_id)
    return DroneResponse(**updated)
