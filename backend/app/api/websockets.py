"""
app/api/websockets.py — WebSocket router for live tracking.
"""

from __future__ import annotations

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends, status

from app.core.security import decode_access_token
from app.websocket.manager import manager
from app.repositories.mission import MissionRepository, get_mission_repo
from app.repositories.medical_request import MedicalRequestRepository, get_request_repo
from app.repositories.user import UserRepository, get_user_repo
from app.core.logging import get_logger

log = get_logger(__name__)

router = APIRouter(tags=["websockets"])


@router.websocket("/ws/missions/{mission_id}")
async def websocket_endpoint(
    websocket: WebSocket,
    mission_id: str,
    mission_repo: MissionRepository = Depends(get_mission_repo),
    req_repo: MedicalRequestRepository = Depends(get_request_repo),
    user_repo: UserRepository = Depends(get_user_repo),
):
    token = websocket.query_params.get("token")
    if not token:
        log.warning("websocket_rejected_no_token", mission_id=mission_id)
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    payload = decode_access_token(token)
    if payload is None or not payload.get("sub"):
        log.warning("websocket_rejected_invalid_token", mission_id=mission_id)
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    user = await user_repo.get_by_id(payload["sub"])
    if user is None:
        log.warning("websocket_rejected_user_not_found", mission_id=mission_id, user_id=payload.get("sub"))
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    # Verify mission exists first
    mission = await mission_repo.get_by_id(mission_id)
    if not mission:
        log.warning("websocket_connection_rejected_not_found", mission_id=mission_id)
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    # Ownership check: same as GET /api/missions/{id}
    user_role = user.get("role")
    if user_role in ("hospital", "hospital_admin"):
        user_center = user.get("center_id")
        if not user_center:
            log.warning("websocket_rejected_hospital_no_center", mission_id=mission_id, user_id=user.get("id"))
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return

        req = await req_repo.get_by_id(mission.get("request_id", ""))
        if req is None or req.get("center_id") != user_center:
            log.warning(
                "websocket_rejected_foreign_hospital",
                mission_id=mission_id,
                user_center=user_center,
                req_center=req.get("center_id") if req else None,
            )
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return
    elif user_role not in ("operator", "admin"):
        log.warning("websocket_rejected_unknown_role", mission_id=mission_id, role=user_role)
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    await manager.connect(websocket, mission_id)
    try:
        while True:
            # We don't expect messages from client, but we must read to detect disconnects
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket, mission_id)
    except Exception as exc:
        log.error("websocket_exception", mission_id=mission_id, error=str(exc))
        manager.disconnect(websocket, mission_id)
