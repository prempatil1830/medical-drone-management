"""
app/api/dashboard.py — Dashboard analytics and statistics endpoint.
Operator and Admin only. Pure MongoDB aggregation, no LLM.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, status
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.api.auth import require_role
from app.core.logging import get_logger
from app.db.database import get_database
from app.schemas.dashboard import DashboardStatsResponse

log = get_logger(__name__)

router = APIRouter(
    prefix="/dashboard",
    tags=["dashboard"],
    dependencies=[Depends(require_role("operator", "admin"))],
)


@router.get(
    "/stats",
    response_model=DashboardStatsResponse,
    status_code=status.HTTP_200_OK,
    summary="Get operational dashboard statistics via MongoDB aggregation",
)
async def get_dashboard_stats(
    db: AsyncIOMotorDatabase = Depends(get_database),
) -> DashboardStatsResponse:
    """
    Compute operational metrics via MongoDB aggregation:
    - delivered, failed, active missions
    - average ETA in minutes
    - drone utilization (% not AVAILABLE)
    - average response time (request created_at to mission started_at) for Critical and High requests
    """
    mission_pipeline = [
        {
            "$facet": {
                "status_counts": [
                    {
                        "$group": {
                            "_id": "$status",
                            "count": {"$sum": 1},
                        }
                    }
                ],
                "avg_eta": [
                    {
                        "$group": {
                            "_id": None,
                            "avg_eta": {"$avg": "$eta_minutes"},
                        }
                    }
                ],
                "response_time": [
                    {
                        "$lookup": {
                            "from": "medical_requests",
                            "let": {"m_req_id": "$request_id"},
                            "pipeline": [
                                {
                                    "$match": {
                                        "$expr": {
                                            "$and": [
                                                {
                                                    "$or": [
                                                        {"$eq": ["$request_id", "$$m_req_id"]},
                                                        {"$eq": [{"$toString": "$_id"}, "$$m_req_id"]},
                                                    ]
                                                },
                                                {
                                                    "$in": [
                                                        "$priority_tier",
                                                        ["Critical", "High"],
                                                    ]
                                                },
                                            ]
                                        }
                                    }
                                }
                            ],
                            "as": "matched_req",
                        }
                    },
                    {"$unwind": "$matched_req"},
                    {
                        "$project": {
                            "diff_seconds": {
                                "$divide": [
                                    {"$subtract": ["$started_at", "$matched_req.created_at"]},
                                    1000.0,
                                ]
                            }
                        }
                    },
                    {
                        "$group": {
                            "_id": None,
                            "avg_response_time": {"$avg": "$diff_seconds"},
                        }
                    },
                ],
            }
        }
    ]

    drone_pipeline = [
        {
            "$facet": {
                "operational": [
                    {"$match": {"status": {"$ne": "MAINTENANCE"}}},
                    {"$count": "count"},
                ],
                "busy": [
                    {
                        "$match": {
                            "status": {
                                "$in": [
                                    "ASSIGNED",
                                    "IN_FLIGHT",
                                    "IN_TRANSIT",
                                    "IN_MISSION",
                                ]
                            }
                        }
                    },
                    {"$count": "count"},
                ],
            }
        }
    ]

    mission_res = await db["missions"].aggregate(mission_pipeline).to_list(length=1)
    drone_res = await db["drones"].aggregate(drone_pipeline).to_list(length=1)

    delivered = 0
    failed = 0
    active = 0
    average_eta = 0.0
    average_response_time = 0.0

    active_statuses = {
        "ASSIGNED",
        "TRAVELLING_TO_PICKUP",
        "PACKAGE_COLLECTED",
        "IN_TRANSIT",
        "APPROACHING_DESTINATION",
    }

    if mission_res:
        facet_data = mission_res[0]
        for sc in facet_data.get("status_counts", []):
            st = sc.get("_id")
            cnt = sc.get("count", 0)
            if st == "DELIVERED":
                delivered += cnt
            elif st == "FAILED":
                failed += cnt
            if st in active_statuses:
                active += cnt

        avg_eta_list = facet_data.get("avg_eta", [])
        if avg_eta_list and avg_eta_list[0].get("avg_eta") is not None:
            average_eta = round(float(avg_eta_list[0]["avg_eta"]), 2)

        resp_time_list = facet_data.get("response_time", [])
        if resp_time_list and resp_time_list[0].get("avg_response_time") is not None:
            average_response_time = round(float(resp_time_list[0]["avg_response_time"]), 2)

    drone_utilization = 0.0
    if drone_res:
        d_facet = drone_res[0]
        operational_list = d_facet.get("operational", [])
        busy_list = d_facet.get("busy", [])

        operational_drones = operational_list[0]["count"] if operational_list else 0
        busy_drones = busy_list[0]["count"] if busy_list else 0

        if operational_drones > 0:
            drone_utilization = round((busy_drones / operational_drones) * 100.0, 2)

    log.info(
        "dashboard_stats_computed",
        delivered=delivered,
        failed=failed,
        active=active,
        average_eta=average_eta,
        drone_utilization=drone_utilization,
        average_response_time=average_response_time,
    )

    return DashboardStatsResponse(
        delivered=delivered,
        failed=failed,
        active=active,
        average_eta=average_eta,
        drone_utilization=drone_utilization,
        average_response_time=average_response_time,
    )
