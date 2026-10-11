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

from fastapi import APIRouter, Depends, HTTPException, Query, BackgroundTasks, status

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
from app.schemas.dispatch import DispatchResponse, AgentDecisionItem, DispatchSummaryResponse
from app.agents.priority_agent import PriorityAgent, classify_priority
from app.agents.allocation_agent import AllocationAgent
from app.agents.weather_agent import WeatherAgent
from app.agents.route_agent import RouteAgent
from app.agents.safety_agent import SafetyAgent
from app.simulation.engine import simulation_engine
from app.core.config import settings
from app.services.explain import (
    extract_dispatch_facts,
    build_template_summary,
    build_weather_note,
    refine_weather_note,
    call_llm,
    verify_grounding,
    generate_explanation,
    strip_markdown,
)
import asyncio
import uuid
from datetime import UTC, datetime
from typing import Any

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
    background_tasks: BackgroundTasks,
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

    # ── Auto-Dispatch: Immediately trigger AI agents and launch mission ──
    async def _auto_dispatch_task(req_id: str):
        try:
            from app.db.database import get_database
            from app.repositories.drone import DroneRepository
            from app.repositories.agent_decision import AgentDecisionRepository
            from app.repositories.weather_observation import WeatherObservationRepository
            from app.repositories.mission import MissionRepository
            
            db = get_database()
            bg_tasks = BackgroundTasks()
            await dispatch_request(
                request_id=req_id,
                background_tasks=bg_tasks,
                current_user={"role": "operator", "id": "system_auto_dispatcher", "email": "auto_dispatcher@aeromedical.com"},
                req_repo=req_repo,
                drone_repo=DroneRepository(db),
                decision_repo=AgentDecisionRepository(db),
                obs_repo=WeatherObservationRepository(db),
                mission_repo=MissionRepository(db),
            )
        except Exception as exc:
            log.warning("auto_dispatch_failed", request_id=req_id, error=str(exc))

    background_tasks.add_task(_auto_dispatch_task, created["request_id"])

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


# ── Agent Decisions ───────────────────────────────────────────────────────────


@router.get(
    "/{request_id}/decisions",
    response_model=list[AgentDecisionItem],
    summary="Get agent decisions for a request in execution order (operator/admin only)",
    dependencies=[Depends(require_role("operator", "admin"))],
)
async def get_request_decisions(
    request_id: str,
    req_repo: MedicalRequestRepository = Depends(get_request_repo),
    decision_repo: AgentDecisionRepository = Depends(get_agent_decision_repo),
) -> list[AgentDecisionItem]:
    """
    Returns the agent_decisions documents for that request in execution order
    (Priority, Weather, Allocation, Route, Safety): agent_name, decision, score, reason, timestamp.
    Does not return input_snapshot.
    """
    req = await req_repo.get_by_id(request_id)
    if req is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Request '{request_id}' not found.",
        )

    docs = await decision_repo.list_by_request(request_id)
    execution_order = {
        "PriorityAgent": 1,
        "WeatherAgent": 2,
        "AllocationAgent": 3,
        "RouteAgent": 4,
        "SafetyAgent": 5,
    }
    sorted_docs = sorted(
        docs,
        key=lambda d: (execution_order.get(d.get("agent_name"), 99), d.get("timestamp") or datetime.min),
    )
    return [
        AgentDecisionItem(
            agent_name=d.get("agent_name", ""),
            decision=d.get("decision", ""),
            score=d.get("score"),
            reason=d.get("reason"),
            timestamp=d.get("timestamp"),
        )
        for d in sorted_docs
    ]


@router.get(
    "/{request_id}/summary",
    response_model=DispatchSummaryResponse,
    summary="Get natural language dispatch explanation summary (operator/admin)",
    dependencies=[Depends(require_role("operator", "admin"))],
)
async def get_request_summary(
    request_id: str,
    req_repo: MedicalRequestRepository = Depends(get_request_repo),
) -> DispatchSummaryResponse:
    """
    Returns the latest dispatch explanation summary for a request.
    Restricted to operator and admin roles. Returns 404 if no summary exists.
    """
    req = await req_repo.get_by_id(request_id)
    if req is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Request '{request_id}' not found.",
        )

    summary = req.get("dispatch_summary")
    if not summary or not summary.get("text"):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No dispatch summary found for request '{request_id}'.",
        )

    return DispatchSummaryResponse(
        text=summary["text"],
        source=summary.get("source", "template"),
        generated_at=summary.get("generated_at") or datetime.now(UTC),
    )


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


async def _bg_upgrade_summary(
    request_id: str,
    facts: dict[str, Any],
    req_repo: MedicalRequestRepository,
    mission_id: Optional[str] = None,
    mission_repo: Optional[MissionRepository] = None,
) -> None:
    """
    Background task: attempts LLM upgrade for dispatch summary and mission weather note.
    Strictly verifies grounding guard before writing.
    """
    if not settings.LLM_API_KEY:
        return

    try:
        template_text = build_template_summary(facts)
        llm_text = await call_llm(facts, template_text)
        if llm_text and verify_grounding(llm_text, facts, template_text=template_text):
            now = datetime.now(UTC)
            cleaned_text = strip_markdown(llm_text)
            upgraded = {
                "text": cleaned_text,
                "source": "llm",
                "generated_at": now,
                "attempt": 1,
            }
            await req_repo.update_dispatch_summary(request_id, upgraded)
            log.info("dispatch_summary_upgraded_to_llm", request_id=request_id)
        else:
            log.info("dispatch_summary_llm_discarded_or_empty", request_id=request_id)

        if mission_id and mission_repo and facts.get("weather"):
            template_note = build_weather_note(facts["weather"])
            refined_note = await refine_weather_note(facts["weather"])
            if refined_note != template_note:
                await mission_repo.update_weather_note(mission_id, refined_note)
                log.info("mission_weather_note_refined_by_llm", mission_id=mission_id)
    except Exception as exc:
        log.warning("bg_upgrade_summary_failed", request_id=request_id, error=str(exc))


# ── Dispatch ──────────────────────────────────────────────────────────────────


@router.post(
    "/{request_id}/dispatch",
    response_model=DispatchResponse,
    status_code=status.HTTP_200_OK,
    summary="Dispatch a medical request through the full agent pipeline",
)
async def dispatch_request(
    request_id: str,
    background_tasks: BackgroundTasks,
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

    # Log Weather Agent decision to agent_decisions
    weather_prob = getattr(weather_result, "probability", 1.0)
    weather_decision_id = str(uuid.uuid4())
    try:
        await decision_repo.create({
            "decision_id": weather_decision_id,
            "agent_name": "WeatherAgent",
            "request_id": request_id,
            "decision": weather_result.flight_condition,
            "probability": weather_prob,
            "score": weather_prob,
            "reason": getattr(weather_result, "reason", None) or f"Weather classified as {weather_result.flight_condition}",
            "input_snapshot": {
                "pickup": pickup,
                "raw_weather_snapshot": getattr(weather_result, "raw_weather_snapshot", None),
            },
            "timestamp": datetime.now(UTC),
        })
    except Exception as exc:
        log.error("weather_decision_log_error", error=str(exc))

    # ── Step 3: Halt if UNSAFE ────────────────────────────────────────────────
    if weather_result.flight_condition == "UNSAFE":
        halt_reason = (
            f"Dispatch halted — weather is UNSAFE at pickup coordinates "
            f"({pickup['lat']}, {pickup['lng']}). "
            f"Reason: {weather_result.reason or 'ML model classified conditions as UNSAFE'}."
        )
        log.warning("dispatch_halted_unsafe_weather", request_id=request_id)

        weather_obs_dict = {
            "flight_condition": weather_result.flight_condition,
            "probability": weather_prob,
            "raw_weather_snapshot": getattr(weather_result, "raw_weather_snapshot", None),
            "reason": getattr(weather_result, "reason", None),
        }
        decisions_trail = [
            {
                "agent_name": "PriorityAgent",
                "decision": priority_result.priority,
                "score": priority_result.score,
                "reason": priority_result.reason,
            },
            {
                "agent_name": "WeatherAgent",
                "decision": weather_result.flight_condition,
                "score": weather_prob,
                "reason": getattr(weather_result, "reason", None),
            },
        ]
        facts = extract_dispatch_facts(
            request=doc,
            decisions=decisions_trail,
            weather_obs=weather_obs_dict,
        )
        template_summary = build_template_summary(facts)
        summary_obj = {
            "text": template_summary,
            "source": "template",
            "generated_at": datetime.now(UTC),
            "attempt": 1,
        }
        status_note = "Waiting: unsafe weather conditions at pickup."

        await req_repo.update_status(
            request_id,
            doc.get("status", "PENDING"),
            priority_tier=priority_result.priority,
            priority_score=priority_result.score,
            status_note=status_note,
            dispatch_summary=summary_obj,
        )
        background_tasks.add_task(_bg_upgrade_summary, request_id, facts, req_repo)

        return DispatchResponse(
            request_id=request_id,
            priority_decision=priority_result.priority,
            priority_score=priority_result.score,
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

        weather_obs_dict = {
            "flight_condition": weather_result.flight_condition,
            "probability": weather_prob,
            "raw_weather_snapshot": getattr(weather_result, "raw_weather_snapshot", None),
            "reason": getattr(weather_result, "reason", None),
        }
        decisions_trail = [
            {
                "agent_name": "PriorityAgent",
                "decision": priority_result.priority,
                "score": priority_result.score,
                "reason": priority_result.reason,
            },
            {
                "agent_name": "WeatherAgent",
                "decision": weather_result.flight_condition,
                "score": weather_prob,
                "reason": getattr(weather_result, "reason", None),
            },
            {
                "agent_name": "AllocationAgent",
                "decision": None,
                "score": None,
                "reason": allocation_result.reason,
            },
        ]
        facts = extract_dispatch_facts(
            request=doc,
            decisions=decisions_trail,
            weather_obs=weather_obs_dict,
            candidate_count=0,
        )
        template_summary = build_template_summary(facts)
        summary_obj = {
            "text": template_summary,
            "source": "template",
            "generated_at": datetime.now(UTC),
            "attempt": 1,
        }
        status_note = "Waiting: no drone available right now."

        await req_repo.update_status(
            request_id,
            doc.get("status", "PENDING"),
            priority_tier=priority_result.priority,
            priority_score=priority_result.score,
            status_note=status_note,
            dispatch_summary=summary_obj,
        )
        background_tasks.add_task(_bg_upgrade_summary, request_id, facts, req_repo)

        return DispatchResponse(
            request_id=request_id,
            priority_decision=priority_result.priority,
            priority_score=priority_result.score,
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

    # ── Ranked Candidates Loop: Retry on Claim Loss ───────────────────────────
    candidates = getattr(allocation_result, "ranked_candidates", [])
    if not candidates:
        allocated_drone = await drone_repo.get_by_drone_id(allocation_result.drone_id)
        if allocated_drone:
            candidates = [{
                "drone_id": allocation_result.drone_id,
                "score": allocation_result.score,
                "drone": allocated_drone,
            }]

    route_agent = RouteAgent()
    safety_agent = SafetyAgent(decision_repo=decision_repo)

    assigned_drone = None
    selected_drone_doc = None
    selected_route_result = None
    selected_safety_result = None
    last_safety_fail = None

    for candidate in candidates:
        cand_drone_id = candidate["drone_id"]
        cand_drone = candidate.get("drone")
        if not cand_drone or not isinstance(cand_drone, dict):
            cand_drone = await drone_repo.get_by_drone_id(cand_drone_id)
        if not cand_drone:
            continue

        # ── Step 5: Route Agent ───────────────────────────────────────────────
        cand_route_result = route_agent.run(
            pickup=doc["pickup"],
            destination=doc["destination"],
            drone_location=cand_drone,
        )

        # Log Route Agent decision to agent_decisions
        route_decision_id = str(uuid.uuid4())
        try:
            await decision_repo.create({
                "decision_id": route_decision_id,
                "agent_name": "RouteAgent",
                "request_id": request_id,
                "decision": "ROUTE_COMPUTED",
                "score": None,
                "reason": f"Computed route for {cand_drone_id}: distance {cand_route_result.distance_km:.2f} km, ETA {cand_route_result.eta_minutes:.1f} min, battery required {cand_route_result.battery_required_pct:.1f}%",
                "input_snapshot": {
                    "pickup": doc["pickup"],
                    "destination": doc["destination"],
                    "drone_id": cand_drone_id,
                    "distance_km": cand_route_result.distance_km,
                    "eta_minutes": cand_route_result.eta_minutes,
                    "battery_required_pct": cand_route_result.battery_required_pct,
                },
                "timestamp": datetime.now(UTC),
            })
        except Exception as exc:
            log.error("route_decision_log_error", error=str(exc))

        # ── Step 6: Safety Agent ──────────────────────────────────────────────
        cand_safety_result = await safety_agent.run(
            request=doc,
            drone=cand_drone,
            route_result=cand_route_result,
            weather_condition=weather_result.flight_condition,
        )

        if cand_safety_result.decision != "PASS":
            log.warning("dispatch_candidate_safety_failed", drone_id=cand_drone_id, reason=cand_safety_result.reason)
            last_safety_fail = (cand_drone, cand_route_result, cand_safety_result)
            continue

        # ── Step 7: Atomic Drone Assignment ───────────────────────────────────
        claim = await drone_repo.assign_drone(cand_drone_id)
        if not claim:
            log.warning("dispatch_race_drone_claim_lost_retrying", drone_id=cand_drone_id, request_id=request_id)
            continue

        # Claim succeeded!
        assigned_drone = claim
        selected_drone_doc = cand_drone
        selected_route_result = cand_route_result
        selected_safety_result = cand_safety_result
        break

    if not assigned_drone or not selected_drone_doc:
        weather_obs_dict = {
            "flight_condition": weather_result.flight_condition,
            "probability": weather_prob,
            "raw_weather_snapshot": getattr(weather_result, "raw_weather_snapshot", None),
            "reason": getattr(weather_result, "reason", None),
        }
        decisions_trail = [
            {
                "agent_name": "PriorityAgent",
                "decision": priority_result.priority,
                "score": priority_result.score,
                "reason": priority_result.reason,
            },
            {
                "agent_name": "WeatherAgent",
                "decision": weather_result.flight_condition,
                "score": weather_prob,
                "reason": getattr(weather_result, "reason", None),
            },
            {
                "agent_name": "AllocationAgent",
                "decision": allocation_result.drone_id,
                "score": allocation_result.score,
                "reason": allocation_result.reason,
            },
        ]

        # None of the feasible candidates could be claimed or passed safety
        if last_safety_fail and len(candidates) == 1:
            # Single candidate that failed safety
            s_drone, s_route, s_safety = last_safety_fail
            log.warning("dispatch_halted_safety", request_id=request_id, reason=s_safety.reason)

            decisions_trail.append({
                "agent_name": "SafetyAgent",
                "decision": s_safety.decision,
                "score": None,
                "reason": s_safety.reason,
            })
            facts = extract_dispatch_facts(
                request=doc,
                decisions=decisions_trail,
                weather_obs=weather_obs_dict,
                candidate_count=len(candidates),
                route_result=s_route,
                safety_result=s_safety,
            )
            template_summary = build_template_summary(facts)
            summary_obj = {
                "text": template_summary,
                "source": "template",
                "generated_at": datetime.now(UTC),
                "attempt": 1,
            }
            status_note = "Waiting: safety constraints not met."

            await req_repo.update_status(
                request_id,
                doc.get("status", "PENDING"),
                priority_tier=priority_result.priority,
                priority_score=priority_result.score,
                assigned_drone_id=s_drone["drone_id"],
                status_note=status_note,
                dispatch_summary=summary_obj,
            )
            background_tasks.add_task(_bg_upgrade_summary, request_id, facts, req_repo)

            return DispatchResponse(
                request_id=request_id,
                priority_decision=priority_result.priority,
                priority_score=priority_result.score,
                priority_reason=priority_result.reason,
                priority_decision_id=priority_result.decision_id,
                weather_condition=weather_result.flight_condition,
                weather_observation_id=weather_result.observation_id,
                weather_halted=False,
                allocated_drone_id=s_drone["drone_id"],
                allocation_score=allocation_result.score,
                allocation_reason=allocation_result.reason,
                allocation_decision_id=allocation_result.decision_id,
                route_distance_km=s_route.distance_km,
                route_eta_minutes=s_route.eta_minutes,
                route_battery_required_pct=s_route.battery_required_pct,
                safety_decision=s_safety.decision,
                safety_reason=s_safety.reason,
                safety_decision_id=s_safety.decision_id,
                mission_id=None,
            )

        log.warning("dispatch_halted_no_drone_available", request_id=request_id)
        facts = extract_dispatch_facts(
            request=doc,
            decisions=decisions_trail,
            weather_obs=weather_obs_dict,
            candidate_count=len(candidates),
        )
        template_summary = build_template_summary(facts)
        summary_obj = {
            "text": template_summary,
            "source": "template",
            "generated_at": datetime.now(UTC),
            "attempt": 1,
        }
        status_note = "Waiting: no drone available right now."

        await req_repo.update_status(
            request_id,
            doc.get("status", "PENDING"),
            priority_tier=priority_result.priority,
            priority_score=priority_result.score,
            status_note=status_note,
            dispatch_summary=summary_obj,
        )
        background_tasks.add_task(_bg_upgrade_summary, request_id, facts, req_repo)

        return DispatchResponse(
            request_id=request_id,
            priority_decision=priority_result.priority,
            priority_score=priority_result.score,
            priority_reason=priority_result.reason,
            priority_decision_id=priority_result.decision_id,
            weather_condition=weather_result.flight_condition,
            weather_observation_id=weather_result.observation_id,
            weather_halted=False,
            allocated_drone_id=None,
            allocation_score=None,
            allocation_reason="NO_FEASIBLE_DRONE — all candidates were claimed or unavailable.",
            allocation_decision_id=allocation_result.decision_id,
            route_distance_km=None,
            route_eta_minutes=None,
            route_battery_required_pct=None,
            safety_decision=None,
            safety_reason=None,
            safety_decision_id=None,
            mission_id=None,
        )

    # ── Step 8: Mission Creation with Compensation ────────────────────────────
    weather_obs_dict = {
        "flight_condition": weather_result.flight_condition,
        "probability": weather_prob,
        "raw_weather_snapshot": getattr(weather_result, "raw_weather_snapshot", None),
        "reason": getattr(weather_result, "reason", None),
    }
    weather_note = build_weather_note(weather_obs_dict)
    weather_data = {
        "condition": weather_result.flight_condition,
        "probability": min(0.999, round(float(weather_prob), 4)) if weather_prob is not None else None,
        "note": weather_note,
    }

    try:
        await drone_repo.update_status(selected_drone_doc["drone_id"], "ASSIGNED")
        mission_doc = {
            "request_id": request_id,
            "drone_id": selected_drone_doc["drone_id"],
            "route": selected_route_result.route,
            "distance_km": selected_route_result.distance_km,
            "eta_minutes": selected_route_result.eta_minutes,
            "battery_required_pct": selected_route_result.battery_required_pct,
            "weather": weather_data,
        }
        mission = await mission_repo.create(mission_doc)

        decisions_trail = [
            {
                "agent_name": "PriorityAgent",
                "decision": priority_result.priority,
                "score": priority_result.score,
                "reason": priority_result.reason,
            },
            {
                "agent_name": "WeatherAgent",
                "decision": weather_result.flight_condition,
                "score": weather_prob,
                "reason": getattr(weather_result, "reason", None),
            },
            {
                "agent_name": "AllocationAgent",
                "decision": selected_drone_doc["drone_id"],
                "score": allocation_result.score,
                "reason": allocation_result.reason,
            },
            {
                "agent_name": "RouteAgent",
                "decision": "ROUTE_COMPUTED",
                "score": None,
                "reason": f"Distance {selected_route_result.distance_km:.2f} km",
            },
            {
                "agent_name": "SafetyAgent",
                "decision": selected_safety_result.decision,
                "score": None,
                "reason": selected_safety_result.reason,
            },
        ]
        facts = extract_dispatch_facts(
            request=doc,
            decisions=decisions_trail,
            weather_obs=weather_obs_dict,
            candidate_count=len(candidates),
            route_result=selected_route_result,
            safety_result=selected_safety_result,
            mission=mission,
        )
        template_summary = build_template_summary(facts)
        summary_obj = {
            "text": template_summary,
            "source": "template",
            "generated_at": datetime.now(UTC),
            "attempt": 1,
        }

        await req_repo.update_status(
            request_id,
            "ASSIGNED",
            mission_id=mission["mission_id"],
            priority_tier=priority_result.priority,
            priority_score=priority_result.score,
            assigned_drone_id=selected_drone_doc["drone_id"],
            dispatch_summary=summary_obj,
        )
        background_tasks.add_task(
            _bg_upgrade_summary,
            request_id,
            facts,
            req_repo,
            mission["mission_id"],
            mission_repo,
        )
    except HTTPException:
        raise
    except Exception as exc:
        log.error("mission_creation_failed_compensating", drone_id=selected_drone_doc["drone_id"], error=str(exc))
        # Compensation: release drone back to AVAILABLE and keep request PENDING
        await drone_repo.update_status(selected_drone_doc["drone_id"], "AVAILABLE")
        await req_repo.update_status(
            request_id,
            "PENDING",
            priority_tier=priority_result.priority,
            priority_score=priority_result.score,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create mission",
        )

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
        allocated_drone_id=selected_drone_doc["drone_id"],
        allocation_score=allocation_result.score,
        allocation_reason=allocation_result.reason,
        allocation_decision_id=allocation_result.decision_id,
        route_distance_km=selected_route_result.distance_km,
        route_eta_minutes=selected_route_result.eta_minutes,
        route_battery_required_pct=selected_route_result.battery_required_pct,
        safety_decision=selected_safety_result.decision,
        safety_reason=selected_safety_result.reason,
        safety_decision_id=selected_safety_result.decision_id,
        mission_id=mission["mission_id"],
    )

