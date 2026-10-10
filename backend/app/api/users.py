"""
app/api/users.py — User management endpoints (Admin only).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.auth import require_role
from app.core.logging import get_logger
from app.repositories.medical_center import MedicalCenterRepository, get_medical_center_repo
from app.repositories.user import UserRepository, get_user_repo
from app.schemas.user import UpdateUserCenterRequest, UserResponse

log = get_logger(__name__)

router = APIRouter(
    prefix="/users",
    tags=["users"],
    dependencies=[Depends(require_role("admin"))],
)


@router.patch(
    "/{user_id}/center",
    response_model=UserResponse,
    summary="Assign a medical center to a user (Admin only)",
)
async def update_user_center(
    user_id: str,
    payload: UpdateUserCenterRequest,
    user_repo: UserRepository = Depends(get_user_repo),
    center_repo: MedicalCenterRepository = Depends(get_medical_center_repo),
) -> UserResponse:
    """Assign or update a user's medical center ID."""
    center = await center_repo.get_by_id(payload.center_id)
    if center is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Medical center '{payload.center_id}' not found.",
        )

    updated = await user_repo.update_center(user_id, payload.center_id)
    if updated is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"User '{user_id}' not found.",
        )

    log.info("user_center_updated", user_id=user_id, center_id=payload.center_id)
    return UserResponse(**updated)
