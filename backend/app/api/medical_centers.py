"""
Medical Centers CRUD endpoints — all routes require authentication.

Routes
------
GET    /api/medical-centers          — list all centers
POST   /api/medical-centers          — create a center
GET    /api/medical-centers/{id}     — retrieve one center
PUT    /api/medical-centers/{id}     — full update
DELETE /api/medical-centers/{id}     — remove a center
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.auth import get_current_user, require_role
from app.core.logging import get_logger
from app.repositories.medical_center import MedicalCenterRepository, get_medical_center_repo
from app.schemas.medical_center import (
    MedicalCenterCreate,
    MedicalCenterResponse,
    MedicalCenterUpdate,
)

log = get_logger(__name__)

router = APIRouter(
    prefix="/medical-centers",
    tags=["medical-centers"],
    dependencies=[Depends(get_current_user)],  # all routes require auth
)


# ── List ──────────────────────────────────────────────────────────────────────


@router.get(
    "/",
    response_model=list[MedicalCenterResponse],
    summary="List medical centers (scoped for hospital users)",
)
async def list_centers(
    current_user: dict = Depends(get_current_user),
    repo: MedicalCenterRepository = Depends(get_medical_center_repo),
) -> list[MedicalCenterResponse]:
    if current_user.get("role") in ("hospital", "hospital_admin"):
        user_center = current_user.get("center_id")
        if not user_center:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Hospital user has no medical center assigned.",
            )
        center = await repo.get_by_id(user_center)
        return [MedicalCenterResponse(**center)] if center else []

    centers = await repo.get_all()
    return [MedicalCenterResponse(**c) for c in centers]


# ── Create ────────────────────────────────────────────────────────────────────


@router.post(
    "/",
    response_model=MedicalCenterResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new medical center (Admin only)",
    dependencies=[Depends(require_role("admin"))],
)
async def create_center(
    payload: MedicalCenterCreate,
    repo: MedicalCenterRepository = Depends(get_medical_center_repo),
) -> MedicalCenterResponse:
    created = await repo.create(payload.model_dump())
    log.info("api_medical_center_created", center_id=created["id"])
    return MedicalCenterResponse(**created)


# ── Retrieve ──────────────────────────────────────────────────────────────────


@router.get(
    "/{center_id}",
    response_model=MedicalCenterResponse,
    summary="Retrieve a medical center by ID",
)
async def get_center(
    center_id: str,
    current_user: dict = Depends(get_current_user),
    repo: MedicalCenterRepository = Depends(get_medical_center_repo),
) -> MedicalCenterResponse:
    if current_user.get("role") in ("hospital", "hospital_admin"):
        user_center = current_user.get("center_id")
        if not user_center:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Hospital user has no medical center assigned.",
            )
        if center_id != user_center:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Medical center '{center_id}' not found.",
            )

    center = await repo.get_by_id(center_id)
    if center is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Medical center '{center_id}' not found.",
        )
    return MedicalCenterResponse(**center)


# ── Update (full) ─────────────────────────────────────────────────────────────


@router.put(
    "/{center_id}",
    response_model=MedicalCenterResponse,
    summary="Update a medical center (Admin only)",
    dependencies=[Depends(require_role("admin"))],
)
async def update_center(
    center_id: str,
    payload: MedicalCenterUpdate,
    repo: MedicalCenterRepository = Depends(get_medical_center_repo),
) -> MedicalCenterResponse:
    update_fields = payload.model_dump(exclude_none=True)
    if not update_fields:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="No fields provided for update.",
        )

    updated = await repo.update(center_id, update_fields)
    if updated is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Medical center '{center_id}' not found.",
        )
    return MedicalCenterResponse(**updated)


# ── Delete ────────────────────────────────────────────────────────────────────


@router.delete(
    "/{center_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a medical center (Admin only)",
    dependencies=[Depends(require_role("admin"))],
)
async def delete_center(
    center_id: str,
    repo: MedicalCenterRepository = Depends(get_medical_center_repo),
) -> None:
    deleted = await repo.delete(center_id)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Medical center '{center_id}' not found.",
        )
