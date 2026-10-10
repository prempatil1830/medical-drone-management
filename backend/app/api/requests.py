"""
Medical Requests endpoints — all routes require authentication.

Routes
------
POST   /api/requests                  — create a delivery request
GET    /api/requests                  — list with optional filters + pagination
GET    /api/requests/{id}             — get request details

Pagination
----------
GET /api/requests accepts ?skip=0&limit=50 query params.
limit is hard-capped at 200 inside the repository layer to prevent
unbounded queries.  If you need to fetch everything, page through with skip.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.auth import get_current_user, require_role
from app.core.logging import get_logger
from app.repositories.medical_center import MedicalCenterRepository, get_medical_center_repo
from app.repositories.medical_request import MedicalRequestRepository, get_request_repo
from app.repositories.drone import DroneRepository, get_drone_repo
from app.repositories.agent_decision import AgentDecisionRepository, get_agent_decision_repo
from app.repositories.weather_observation import WeatherObservationRepository, get_weather_obs_repo
from app.repositories.mission import MissionRepository, get_mission_repo
from app.schemas.medical_request import (
    MedicalRequestCreate,
    MedicalRequestResponse,
    RequestStatus,
    Urgency,
)
from app.schemas.dispatch import DispatchResponse
from app.agents.priority_agent import PriorityAgent, classify_priority
from app.agents.allocation_agent import AllocationAgent
from app.agents.weather_agent import WeatherAgent
from app.agents.route_agent import RouteAgent
from app.agents.safety_agent import SafetyAgent
from app.simulation.engine import simulation_engine
import asyncio

log = get_logger(__name__)

router = APIRouter(
    prefix="/requests",
    tags=["requests"],
    dependencies=[Depends(get_current_user)],
)


# ── Create ────────────────────────────────────────────────────────────────────


@router.post(
    "/",
    response_model=MedicalRequestResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a medical delivery request",
)
async def create_request(
    payload: MedicalRequestCreate,
    current_user: dict = Depends(get_current_user),
    req_repo: MedicalRequestRepository = Depends(get_request_repo),
    center_repo: MedicalCenterRepository = Depends(get_medical_center_repo),
) -> MedicalRequestResponse:
    """
    Create a new medical delivery request.

    Validates that ``center_id`` references an existing medical center
    before persisting.  Returns HTTP 422 if the center is not found.
    Hospital users can only create requests for their assigned center.
    """
    # Hospital user scoping check
    if current_user.get("role") in ("hospital", "hospital_admin"):
        user_center = current_user.get("center_id")
        if not user_center:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Hospital user has no medical center assigned.",
            )
        if payload.center_id != user_center:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Hospital users can only create requests for their assigned medical center '{user_center}'.",
            )

    center = await center_repo.get_by_id(payload.center_id)
    if center is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Medical center '{payload.center_id}' does not exist.",
        )

    doc = payload.model_dump(mode="json")
    # Flatten nested Coordinates dicts so Mongo stores them naturally
    doc["pickup"] = payload.pickup.model_dump()
    doc["destination"] = payload.destination.model_dump()

    # Priority computed and stored at creation (WITHOUT logging to agent_decisions)
    tier, score = classify_priority(doc)
    doc["priority_tier"] = tier
    doc["priority_score"] = score

    created = await req_repo.create(doc)
    log.info("api_request_created", request_id=created["request_id"])
    return _to_response(created)


# ── List ──────────────────────────────────────────────────────────────────────


@router.get(
    "/",
    response_model=list[MedicalRequestResponse],
    summary="List medical requests (filterable, paginated)",
)
async def list_requests(
    status_filter: Optional[RequestStatus] = Query(None, alias="status"),
    center_id: Optional[str] = Query(None),
    urgency: Optional[Urgency] = Query(None),
    skip: int = Query(0, ge=0, description="Number of records to skip"),
    limit: int = Query(50, ge=1, le=200, description="Max records to return (hard cap: 200)"),
    current_user: dict = Depends(get_current_user),
    repo: MedicalRequestRepository = Depends(get_request_repo),
) -> list[MedicalRequestResponse]:
    # Hospital users are strictly scoped to their own medical center (403 if unassigned)
    if current_user.get("role") in ("hospital", "hospital_admin"):
        user_center = current_user.get("center_id")
        if not user_center:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Hospital user has no medical center assigned.",
            )
        center_id = user_center

    docs = await repo.list_requests(
        status=status_filter.value if status_filter else None,
        center_id=center_id,
        urgency=urgency.value if urgency else None,
        skip=skip,
        limit=limit,
    )
    return [_to_response(d) for d in docs]


# ── Retrieve one ──────────────────────────────────────────────────────────────


@router.get(
    "/{request_id}",
    response_model=MedicalRequestResponse,
    summary="Get a medical request by ID",
)
async def get_request(
    request_id: str,
    current_user: dict = Depends(get_current_user),
    repo: MedicalRequestRepository = Depends(get_request_repo),
) -> MedicalRequestResponse:
    # Hospital users without a center_id must get 403 on every request endpoint
    if current_user.get("role") in ("hospital", "hospital_admin"):
        user_center = current_user.get("center_id")
        if not user_center:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Hospital user has no medical center assigned.",
            )

    doc = await repo.get_by_id(request_id)
    if doc is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Request '{request_id}' not found.",
        )

    # Hospital users can only read their own center's requests (other center returns 404)
    if current_user.get("role") in ("hospital", "hospital_admin"):
        user_center = current_user.get("center_id")
        if doc.get("center_id") != user_center:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Request '{request_id}' not found.",
            )

    return _to_response(doc)


# ── Helpers ───────────────────────────────────────────────────────────────────


def _to_response(doc: dict) -> MedicalRequestResponse:
    """Safely convert a raw Mongo document to MedicalRequestResponse."""
    from app.schemas.medical_request import Coordinates

    d = dict(doc)
    if "id" not in d and "_id" in d:
        d["id"] = str(d.pop("_id"))
    d["pickup"] = Coordinates(**d["pickup"])
    d["destination"] = Coordinates(**d["destination"])
    return MedicalRequestResponse(**d)


# ── Dispatch ──────────────────────────────────────────────────────────────────


@router.post(
    "/{request_id}/dispatch",
    response_model=DispatchResponse,
    status_code=status.HTTP_200_OK,
    summary="Dispatch a medical request through the full agent pipeline",
)
async def dispatch_request(
    request_id: str,
    current_user: dict = Depends(require_role("operator", "admin")),
    req_repo: MedicalRequestRepository = Depends(get_request_repo),
    drone_repo: DroneRepository = Depends(get_drone_repo),
    decision_repo: AgentDecisionRepository = Depends(get_agent_decision_repo),
    obs_repo: WeatherObservationRepository = Depends(get_weather_obs_repo),
    mission_repo: MissionRepository = Depends(get_mission_repo),
) -> DispatchResponse:
    """
    Run the full Phase 8 agent pipeline for a medical delivery request:

    1. **Priority Agent** — classify the request as Critical/High/Medium/Normal.
    2. **Weather Agent** — check flight conditions at the pickup coordinates.
    3. **Allocation Agent** — if weather is safe, select the best available drone.
    4. **Route Agent** — compute distance, ETA, and battery required.
    5. **Safety Agent** — final deterministic gate to re-check all constraints.
    6. **Mission Creation** — if all pass, create mission and update drone status.

    If the Weather Agent returns ``UNSAFE``, the pipeline halts and
    ``weather_halted=True`` is set.  The Allocation Agent is NOT called.
    If Safety Agent fails, it halts and returns the trail without mission creation.
    All agent decisions are persisted to the ``agent_decisions`` collection.
    """
    # ── Step 0: Fetch the request ─────────────────────────────────────────────
    doc = await req_repo.get_by_id(request_id)
    if doc is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Request '{request_id}' not found.",
        )

    log.info("dispatch_started", request_id=request_id)

    # ── Step 1: Priority Agent ────────────────────────────────────────────────
    priority_agent = PriorityAgent(decision_repo=decision_repo)
    priority_result = await priority_agent.run(request=doc)

    log.info(
        "dispatch_priority_done",
        request_id=request_id,
        priority=priority_result.priority,
    )

    # ── Step 2: Weather Agent (pickup coordinates) ────────────────────────────
    pickup = doc["pickup"]
    weather_agent = WeatherAgent()
    weather_result = await weather_agent.run(
        lat=float(pickup["lat"]),
        lng=float(pickup["lng"]),
        obs_repo=obs_repo,
    )

    log.info(
        "dispatch_weather_done",
        request_id=request_id,
        flight_condition=weather_result.flight_condition,
    )

    # ── Step 3: Halt if UNSAFE ────────────────────────────────────────────────
    if weather_result.flight_condition == "UNSAFE":
        halt_reason = (
            f"Dispatch halted — weather is UNSAFE at pickup coordinates "
            f"({pickup['lat']}, {pickup['lng']}). "
            f"Reason: {weather_result.reason or 'ML model classified conditions as UNSAFE'}."
        )
        log.warning("dispatch_halted_unsafe_weather", request_id=request_id)
        await req_repo.update_status(
            request_id,
            doc.get("status", "PENDING"),
            priority_tier=priority_result.priority,
            priority_score=priority_result.score,
        )
        return DispatchResponse(
            request_id=request_id,
            priority_decision=priority_result.priority,
            priority_reason=priority_result.reason,
            priority_decision_id=priority_result.decision_id,
            weather_condition=weather_result.flight_condition,
            weather_observation_id=weather_result.observation_id,
            weather_halted=True,
            allocated_drone_id=None,
            allocation_score=None,
            allocation_reason=halt_reason,
            allocation_decision_id=None,
            route_distance_km=None,
            route_eta_minutes=None,
            route_battery_required_pct=None,
            safety_decision=None,
            safety_reason=None,
            safety_decision_id=None,
            mission_id=None,
        )

    # ── Step 4: Allocation Agent ──────────────────────────────────────────────
    drones = await drone_repo.get_all()
    allocation_agent = AllocationAgent(decision_repo=decision_repo)
    allocation_result = await allocation_agent.run(
        request=doc,
        priority=priority_result.priority,
        drones=drones,
    )

    log.info(
        "dispatch_allocation_done",
        request_id=request_id,
        drone_id=allocation_result.drone_id,
        score=allocation_result.score,
    )

    # Halt if Allocation Agent found no feasible drone
    if allocation_result.drone_id is None:
        log.warning("dispatch_halted_no_drone", request_id=request_id)
        await req_repo.update_status(
            request_id,
            doc.get("status", "PENDING"),
            priority_tier=priority_result.priority,
            priority_score=priority_result.score,
        )
        return DispatchResponse(
            request_id=request_id,
            priority_decision=priority_result.priority,
            priority_reason=priority_result.reason,
            priority_decision_id=priority_result.decision_id,
            weather_condition=weather_result.flight_condition,
            weather_observation_id=weather_result.observation_id,
            weather_halted=False,
            allocated_drone_id=None,
            allocation_score=None,
            allocation_reason=allocation_result.reason,
            allocation_decision_id=allocation_result.decision_id,
            route_distance_km=None,
            route_eta_minutes=None,
            route_battery_required_pct=None,
            safety_decision=None,
            safety_reason=None,
            safety_decision_id=None,
            mission_id=None,
        )

    allocated_drone = await drone_repo.get_by_drone_id(allocation_result.drone_id)

    # ── Step 5: Route Agent ───────────────────────────────────────────────────
    route_agent = RouteAgent()
    route_result = route_agent.run(
        pickup=doc["pickup"],
        destination=doc["destination"],
        drone_location=allocated_drone,
    )

    # ── Step 6: Safety Agent ──────────────────────────────────────────────────
    safety_agent = SafetyAgent(decision_repo=decision_repo)
    safety_result = await safety_agent.run(
        request=doc,
        drone=allocated_drone,
        route_result=route_result,
        weather_condition=weather_result.flight_condition,
    )

    log.info(
        "dispatch_safety_done",
        request_id=request_id,
        decision=safety_result.decision,
    )

    # Halt if Safety Agent fails
    if safety_result.decision != "PASS":
        log.warning("dispatch_halted_safety", request_id=request_id, reason=safety_result.reason)
        await req_repo.update_status(
            request_id,
            doc.get("status", "PENDING"),
            priority_tier=priority_result.priority,
            priority_score=priority_result.score,
            assigned_drone_id=allocation_result.drone_id,
        )
        return DispatchResponse(
            request_id=request_id,
            priority_decision=priority_result.priority,
            priority_reason=priority_result.reason,
            priority_decision_id=priority_result.decision_id,
            weather_condition=weather_result.flight_condition,
            weather_observation_id=weather_result.observation_id,
            weather_halted=False,
            allocated_drone_id=allocation_result.drone_id,
            allocation_score=allocation_result.score,
            allocation_reason=allocation_result.reason,
            allocation_decision_id=allocation_result.decision_id,
            route_distance_km=route_result.distance_km,
            route_eta_minutes=route_result.eta_minutes,
            route_battery_required_pct=route_result.battery_required_pct,
            safety_decision=safety_result.decision,
            safety_reason=safety_result.reason,
            safety_decision_id=safety_result.decision_id,
            mission_id=None,
        )

    # ── Step 7: Mission Creation ──────────────────────────────────────────────
    mission_doc = {
        "request_id": request_id,
        "drone_id": allocated_drone["drone_id"],
        "route": route_result.route,
        "distance_km": route_result.distance_km,
        "eta_minutes": route_result.eta_minutes,
        "battery_required_pct": route_result.battery_required_pct,
    }
    mission = await mission_repo.create(mission_doc)
    await req_repo.update_status(
        request_id,
        "ASSIGNED",
        mission_id=mission["mission_id"],
        priority_tier=priority_result.priority,
        priority_score=priority_result.score,
        assigned_drone_id=allocated_drone["drone_id"],
    )
    await drone_repo.update_status(allocated_drone["drone_id"], "ASSIGNED")

    task = asyncio.create_task(simulation_engine.run_mission_simulation(mission["mission_id"]))
    simulation_engine.active_tasks[mission["mission_id"]] = task

    log.info("dispatch_success", request_id=request_id, mission_id=mission["mission_id"])

    return DispatchResponse(
        request_id=request_id,
        priority_decision=priority_result.priority,
        priority_score=priority_result.score,
        priority_reason=priority_result.reason,
        priority_decision_id=priority_result.decision_id,
        weather_condition=weather_result.flight_condition,
        weather_observation_id=weather_result.observation_id,
        weather_halted=False,
        allocated_drone_id=allocation_result.drone_id,
        allocation_score=allocation_result.score,
        allocation_reason=allocation_result.reason,
        allocation_decision_id=allocation_result.decision_id,
        route_distance_km=route_result.distance_km,
        route_eta_minutes=route_result.eta_minutes,
        route_battery_required_pct=route_result.battery_required_pct,
        safety_decision=safety_result.decision,
        safety_reason=safety_result.reason,
        safety_decision_id=safety_result.decision_id,
        mission_id=mission["mission_id"],
    )

