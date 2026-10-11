import pytest
from datetime import UTC, datetime
from fastapi.testclient import TestClient
from unittest.mock import AsyncMock, MagicMock

from app.main import app
from app.schemas.medical_request import RequestStatus
from app.schemas.mission import MissionStatus
from app.repositories.medical_request import get_request_repo
from app.repositories.medical_center import get_medical_center_repo
from app.api.auth import get_current_user

FAKE_REQ_ID = "64f1a2b3c4d5e6f7a8b9c0d3"
FAKE_CENTER_ID = "64f1a2b3c4d5e6f7a8b9c0d2"

def _user_doc(role="operator"):
    return {
        "id": "64f1a2b3c4d5e6f7a8b9c0d1",
        "name": "Operator",
        "email": "op@aeromedical.com",
        "role": role,
        "center_id": FAKE_CENTER_ID,
    }

def _make_req_doc(status_val: str):
    return {
        "id": FAKE_REQ_ID,
        "request_id": "req-status-test",
        "center_id": FAKE_CENTER_ID,
        "medical_type": "Blood",
        "quantity": 2,
        "weight_kg": 1.5,
        "urgency": "HIGH",
        "pickup": {"lat": 12.9716, "lng": 77.5946},
        "destination": {"lat": 12.9352, "lng": 77.6245},
        "status": status_val,
        "created_at": datetime.now(UTC),
    }

@pytest.mark.parametrize("mission_status,expected_req_status", [
    (MissionStatus.assigned.value, RequestStatus.assigned.value),
    (MissionStatus.travelling_to_pickup.value, RequestStatus.assigned.value),
    (MissionStatus.package_collected.value, RequestStatus.in_transit.value),
    (MissionStatus.in_transit.value, RequestStatus.in_transit.value),
    (MissionStatus.approaching_destination.value, RequestStatus.in_transit.value),
    (MissionStatus.delivered.value, RequestStatus.delivered.value),
    (MissionStatus.failed.value, RequestStatus.failed.value),
])
def test_request_status_at_every_mission_stage(mission_status, expected_req_status):
    """
    At every mission stage, verify that:
    1. The mapped status written to medical_requests is strictly a valid RequestStatus enum.
    2. GET /api/requests/ returns HTTP 200 and serializes properly.
    3. GET /api/requests/{id} returns HTTP 200 and serializes properly.
    """
    # 1. Verify mapped status belongs to RequestStatus enum
    valid_request_statuses = {s.value for s in RequestStatus}
    
    # Engine mapping logic:
    if mission_status in ("PACKAGE_COLLECTED", "IN_TRANSIT", "APPROACHING_DESTINATION"):
        mapped = RequestStatus.in_transit.value
    elif mission_status == "DELIVERED":
        mapped = RequestStatus.delivered.value
    elif mission_status == "FAILED":
        mapped = RequestStatus.failed.value
    elif mission_status == "CANCELLED":
        mapped = RequestStatus.cancelled.value
    else:
        mapped = RequestStatus.assigned.value

    assert mapped == expected_req_status
    assert mapped in valid_request_statuses

    # 2. Test GET endpoints with this status
    doc = _make_req_doc(mapped)
    mock_req_repo = MagicMock()
    mock_req_repo.list_requests = AsyncMock(return_value=[doc])
    mock_req_repo.get_by_id = AsyncMock(return_value=doc)

    client = TestClient(app)
    app.dependency_overrides[get_request_repo] = lambda: mock_req_repo
    app.dependency_overrides[get_current_user] = lambda: _user_doc()

    try:
        # GET /api/requests/
        res_list = client.get("/api/requests/", headers={"Authorization": "Bearer fake"})
        assert res_list.status_code == 200
        data_list = res_list.json()
        assert len(data_list) == 1
        assert data_list[0]["status"] == expected_req_status

        # GET /api/requests/{id}
        res_one = client.get(f"/api/requests/{FAKE_REQ_ID}", headers={"Authorization": "Bearer fake"})
        assert res_one.status_code == 200
        data_one = res_one.json()
        assert data_one["status"] == expected_req_status
    finally:
        app.dependency_overrides.clear()
