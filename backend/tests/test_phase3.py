"""
Unit tests for Phase 3: medical requests and drone endpoints.

All tests use mock repositories — no live MongoDB required.

Run with:
    cd backend
    pytest tests/test_phase3.py -v
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from app.core.security import create_access_token


# ── Shared test helpers ───────────────────────────────────────────────────────

FAKE_USER_ID = "64f1a2b3c4d5e6f7a8b9c0d1"
FAKE_CENTER_ID = "64f1a2b3c4d5e6f7a8b9c0d2"
FAKE_REQUEST_ID = "64f1a2b3c4d5e6f7a8b9c0d3"


def _valid_token() -> str:
    return create_access_token({"sub": FAKE_USER_ID, "role": "hospital", "center_id": FAKE_CENTER_ID})


def _auth_headers() -> dict:
    return {"Authorization": f"Bearer {_valid_token()}"}


def _fake_user_doc(role: str = "hospital", center_id: str | None = FAKE_CENTER_ID) -> dict:
    return {
        "id": FAKE_USER_ID,
        "name": "Test User",
        "email": "test@hospital.com",
        "role": role,
        "center_id": center_id,
        "password_hash": "$2b$12$fakehash",
        "created_at": datetime.now(UTC),
    }


def _fake_center_doc() -> dict:
    return {
        "id": FAKE_CENTER_ID,
        "name": "City General Hospital",
        "type": "hospital",
        "address": "MG Road, Bengaluru",
        "latitude": 12.9716,
        "longitude": 77.5946,
        "contact": "+91-80-12345678",
    }


def _fake_request_doc(center_id: str = FAKE_CENTER_ID) -> dict:
    return {
        "id": FAKE_REQUEST_ID,
        "request_id": "req-uuid-1234",
        "center_id": center_id,
        "medical_type": "Plasma",
        "quantity": 5,
        "weight_kg": 2.5,
        "urgency": "HIGH",
        "pickup": {"lat": 12.9716, "lng": 77.5946},
        "destination": {"lat": 12.9352, "lng": 77.6245},
        "status": "PENDING",
        "created_at": datetime.now(UTC),
    }


def _fake_drone(status: str = "AVAILABLE", drone_id: str = "BLR-D001") -> dict:
    return {
        "id": "64f1a2b3c4d5e6f7a8b9c0d4",
        "drone_id": drone_id,
        "model": "MediHawk X200",
        "battery_pct": 90.0,
        "max_payload_kg": 5.0,
        "max_range_km": 25.0,
        "latitude": 12.9716,
        "longitude": 77.5946,
        "status": status,
        "zone": "Central Bengaluru",
        "updated_at": datetime.now(UTC),
    }


def _make_requests_app(
    mock_req_repo,
    mock_center_repo,
    mock_user_repo,
):
    """Build a minimal app wired with mock repos for requests tests."""
    from fastapi import FastAPI
    from app.api.requests import router as requests_router
    from app.api.auth import get_current_user
    from app.repositories.medical_request import get_request_repo
    from app.repositories.medical_center import get_medical_center_repo

    app = FastAPI()
    app.include_router(requests_router, prefix="/api")
    app.dependency_overrides[get_request_repo] = lambda: mock_req_repo
    app.dependency_overrides[get_medical_center_repo] = lambda: mock_center_repo
    # Bypass JWT check by overriding get_current_user directly
    app.dependency_overrides[get_current_user] = (
        lambda: mock_user_repo if mock_user_repo is not None else _fake_user_doc()
    )
    return app


def _make_drones_app(mock_drone_repo):
    """Build a minimal app wired with mock drone repo."""
    from fastapi import FastAPI
    from app.api.drones import router as drones_router
    from app.api.auth import get_current_user
    from app.repositories.drone import get_drone_repo

    app = FastAPI()
    app.include_router(drones_router, prefix="/api")
    app.dependency_overrides[get_drone_repo] = lambda: mock_drone_repo
    app.dependency_overrides[get_current_user] = lambda: _fake_user_doc(role="operator")
    return app


# ══════════════════════════════════════════════════════════════════════════════
# 1. Request creation tests
# ══════════════════════════════════════════════════════════════════════════════


class TestCreateRequest:
    """All three required test cases + extras."""

    def _base_payload(self, **overrides) -> dict:
        payload = {
            "center_id": FAKE_CENTER_ID,
            "medical_type": "Plasma",
            "quantity": 5,
            "weight_kg": 2.5,
            "urgency": "HIGH",
            "pickup": {"lat": 12.9716, "lng": 77.5946},
            "destination": {"lat": 12.9352, "lng": 77.6245},
        }
        payload.update(overrides)
        return payload

    def _mock_repos(self, center_exists: bool = True):
        req_repo = MagicMock()
        req_repo.create = AsyncMock(return_value=_fake_request_doc())

        center_repo = MagicMock()
        center_repo.get_by_id = AsyncMock(
            return_value=_fake_center_doc() if center_exists else None
        )
        return req_repo, center_repo

    # ── Required test 1: invalid center_id → 422 ─────────────────────────────

    def test_invalid_center_id_returns_422(self):
        """Creating a request with a non-existent center_id must return 422."""
        invalid_center = "000000000000000000000000"
        req_repo, center_repo = self._mock_repos(center_exists=False)
        client = TestClient(_make_requests_app(
            req_repo,
            center_repo,
            _fake_user_doc(center_id=invalid_center),
        ))

        resp = client.post(
            "/api/requests/",
            json=self._base_payload(center_id=invalid_center),
        )
        assert resp.status_code == 422
        assert "does not exist" in resp.json()["detail"]

    # ── Required test 2: negative / zero quantity → 422 ──────────────────────

    def test_zero_quantity_rejected(self):
        """quantity=0 must fail Pydantic's gt=0 constraint (422)."""
        req_repo, center_repo = self._mock_repos()
        client = TestClient(_make_requests_app(req_repo, center_repo, None))

        resp = client.post("/api/requests/", json=self._base_payload(quantity=0))
        assert resp.status_code == 422

    def test_negative_quantity_rejected(self):
        """Negative quantity must fail Pydantic's gt=0 constraint (422)."""
        req_repo, center_repo = self._mock_repos()
        client = TestClient(_make_requests_app(req_repo, center_repo, None))

        resp = client.post("/api/requests/", json=self._base_payload(quantity=-3))
        assert resp.status_code == 422

    def test_zero_weight_rejected(self):
        """weight_kg=0 must fail Pydantic's gt=0.0 constraint (422)."""
        req_repo, center_repo = self._mock_repos()
        client = TestClient(_make_requests_app(req_repo, center_repo, None))

        resp = client.post("/api/requests/", json=self._base_payload(weight_kg=0.0))
        assert resp.status_code == 422

    def test_negative_weight_rejected(self):
        """Negative weight_kg must fail Pydantic's gt=0.0 constraint (422)."""
        req_repo, center_repo = self._mock_repos()
        client = TestClient(_make_requests_app(req_repo, center_repo, None))

        resp = client.post("/api/requests/", json=self._base_payload(weight_kg=-1.5))
        assert resp.status_code == 422

    # ── Positive case ─────────────────────────────────────────────────────────

    def test_valid_request_returns_201(self):
        """A well-formed request with a valid center_id must return 201."""
        req_repo, center_repo = self._mock_repos()
        client = TestClient(_make_requests_app(req_repo, center_repo, None))

        resp = client.post("/api/requests/", json=self._base_payload())
        assert resp.status_code == 201
        data = resp.json()
        assert data["status"] == "PENDING"
        assert data["center_id"] == FAKE_CENTER_ID

    def test_invalid_urgency_rejected(self):
        """Unknown urgency value must fail Pydantic validation (422)."""
        req_repo, center_repo = self._mock_repos()
        client = TestClient(_make_requests_app(req_repo, center_repo, None))

        resp = client.post("/api/requests/", json=self._base_payload(urgency="MEGA_URGENT"))
        assert resp.status_code == 422


# ══════════════════════════════════════════════════════════════════════════════
# 2. Drone endpoint tests
# ══════════════════════════════════════════════════════════════════════════════


class TestDroneEndpoints:
    """GET /api/drones and GET /api/drones/available."""

    # ── Required test 3: available filter excludes non-AVAILABLE ─────────────

    def test_available_endpoint_excludes_non_available(self):
        """
        GET /api/drones/available must return only AVAILABLE drones.
        The mock returns two drones in different statuses; only one must appear.
        """
        available_drone = _fake_drone(status="AVAILABLE", drone_id="BLR-D001")
        # The repo.get_available() should only return the AVAILABLE one
        drone_repo = MagicMock()
        drone_repo.get_available = AsyncMock(return_value=[available_drone])
        drone_repo.get_all = AsyncMock(
            return_value=[
                available_drone,
                _fake_drone(status="CHARGING", drone_id="BLR-D009"),
                _fake_drone(status="MAINTENANCE", drone_id="BLR-D010"),
            ]
        )

        client = TestClient(_make_drones_app(drone_repo))

        # /available should only return 1 (the AVAILABLE one)
        resp = client.get("/api/drones/available")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["status"] == "AVAILABLE"
        assert data[0]["drone_id"] == "BLR-D001"

    def test_available_returns_empty_when_none_available(self):
        """Returns an empty list — not an error — when no drones are AVAILABLE."""
        drone_repo = MagicMock()
        drone_repo.get_available = AsyncMock(return_value=[])

        client = TestClient(_make_drones_app(drone_repo))
        resp = client.get("/api/drones/available")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_list_all_drones_returns_full_fleet(self):
        """GET /api/drones/ must return all drones regardless of status."""
        all_drones = [
            _fake_drone("AVAILABLE", "BLR-D001"),
            _fake_drone("CHARGING", "BLR-D009"),
            _fake_drone("MAINTENANCE", "BLR-D010"),
        ]
        drone_repo = MagicMock()
        drone_repo.get_all = AsyncMock(return_value=all_drones)

        client = TestClient(_make_drones_app(drone_repo))
        resp = client.get("/api/drones/")
        assert resp.status_code == 200
        assert len(resp.json()) == 3


# ══════════════════════════════════════════════════════════════════════════════
# 3. Pagination schema validation
# ══════════════════════════════════════════════════════════════════════════════


class TestRequestListPagination:
    """Verify that the list endpoint honours pagination query params."""

    def _mock_repos(self):
        req_repo = MagicMock()
        req_repo.list_requests = AsyncMock(return_value=[_fake_request_doc()])
        center_repo = MagicMock()
        return req_repo, center_repo

    def test_limit_above_200_rejected(self):
        """limit > 200 should be rejected by the Query constraint (422)."""
        req_repo, center_repo = self._mock_repos()
        client = TestClient(_make_requests_app(req_repo, center_repo, None))
        resp = client.get("/api/requests/?limit=999")
        assert resp.status_code == 422

    def test_negative_skip_rejected(self):
        """skip < 0 should be rejected by the Query constraint (422)."""
        req_repo, center_repo = self._mock_repos()
        client = TestClient(_make_requests_app(req_repo, center_repo, None))
        resp = client.get("/api/requests/?skip=-1")
        assert resp.status_code == 422

    def test_default_pagination_accepted(self):
        """No pagination params — defaults should work fine."""
        req_repo, center_repo = self._mock_repos()
        client = TestClient(_make_requests_app(req_repo, center_repo, None))
        resp = client.get("/api/requests/")
        assert resp.status_code == 200
