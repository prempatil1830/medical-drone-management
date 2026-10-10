"""
Medical Missions endpoints — all routes require authentication.

Routes
------
GET    /api/missions/{id}             — get mission details
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.auth import get_current_user
from app.repositories.mission import MissionRepository, get_mission_repo
from app.repositories.medical_request import MedicalRequestRepository, get_request_repo
from app.schemas.mission import MissionResponse
from app.core.logging import get_logger

log = get_logger(__name__)

router = APIRouter(
    prefix="/missions",
    tags=["missions"],
    dependencies=[Depends(get_current_user)],
)


@router.get(
    "/{mission_id}",
    response_model=MissionResponse,
    summary="Get a mission by ID",
)
async def get_mission(
    mission_id: str,
    current_user: dict = Depends(get_current_user),
    repo: MissionRepository = Depends(get_mission_repo),
    req_repo: MedicalRequestRepository = Depends(get_request_repo),
) -> MissionResponse:
    doc = await repo.get_by_id(mission_id)
    if doc is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Mission '{mission_id}' not found.",
        )

    # Hospital users without a center_id must get 403 on every request and mission endpoint
    if current_user.get("role") in ("hospital", "hospital_admin"):
        user_center = current_user.get("center_id")
        if not user_center:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Hospital user has no medical center assigned.",
            )
        req = await req_repo.get_by_id(doc.get("request_id", ""))
        if req is None or req.get("center_id") != user_center:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Mission '{mission_id}' not found.",
            )

    return MissionResponse(**doc)

from pydantic import BaseModel
class MissionFailRequest(BaseModel):
    reason: str

@router.post(
    "/{mission_id}/fail",
    response_model=MissionResponse,
    summary="Fail a mission (fault injection, admin/operator only)",
)
async def fail_mission(
    mission_id: str,
    fail_in: MissionFailRequest,
    current_user: dict = Depends(get_current_user),
    repo: MissionRepository = Depends(get_mission_repo),
    req_repo: MedicalRequestRepository = Depends(get_request_repo),
) -> MissionResponse:
    from app.api.auth import require_role
    if current_user.get("role") not in ("admin", "operator"):
        raise HTTPException(status.HTTP_403_FORBIDDEN)
        
    doc = await repo.get_by_id(mission_id)
    if not doc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Mission not found")
        
    drone_id = doc.get("drone_id")
    request_id = doc.get("request_id")
    
    from app.db.database import get_database
    db = get_database()
    
    # Update mission
    await db["missions"].update_one(
        {"mission_id": mission_id},
        {"$set": {"status": "FAILED", "failure_reason": fail_in.reason}}
    )
    
    # Update request
    from bson import ObjectId
    try:
        await db["medical_requests"].update_one(
            {"_id": ObjectId(request_id)},
            {"$set": {"status": "FAILED", "failure_reason": fail_in.reason}}
        )
    except Exception:
        await db["medical_requests"].update_one(
            {"request_id": request_id},
            {"$set": {"status": "FAILED", "failure_reason": fail_in.reason}}
        )
        
    # Update drone
    await db["drones"].update_one(
        {"drone_id": drone_id},
        {"$set": {"status": "MAINTENANCE"}}
    )
    
    # Broadcast
    from app.websocket.manager import manager
    from datetime import datetime, UTC
    await manager.broadcast_to_mission(mission_id, {
        "mission_id": mission_id,
        "status": "FAILED",
        "failure_reason": fail_in.reason,
        "timestamp": datetime.now(UTC),
    })
    
    # Stop task if exists
    from app.simulation.engine import simulation_engine
    if mission_id in simulation_engine.active_tasks:
        simulation_engine.active_tasks[mission_id].cancel()
        
    updated = await repo.get_by_id(mission_id)
    return MissionResponse(**updated)
