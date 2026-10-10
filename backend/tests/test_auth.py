"""
Unit tests for Phase 2: password hashing, JWT, and auth endpoint behaviour.

These tests are intentionally kept fast and dependency-light:
- Security tests (hash/JWT) are pure unit tests — no DB required.
- API tests use TestClient + a mocked UserRepository so no live Mongo is needed.

Run with:
    cd backend
    pytest tests/test_auth.py -v
"""

from __future__ import annotations

import time
from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from app.core.security import (
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)


# ══════════════════════════════════════════════════════════════════════════════
# 1. Password hashing tests
# ══════════════════════════════════════════════════════════════════════════════


class TestPasswordHashing:
    def test_round_trip_matches(self):
        """verify_password must return True for the original plain text."""
        plain = "s3cr3tP@ssw0rd"
        hashed = hash_password(plain)
        assert verify_password(plain, hashed) is True

    def test_wrong_password_does_not_match(self):
        """verify_password must return False for a different password."""
        hashed = hash_password("correct_password")
        assert verify_password("wrong_password", hashed) is False

    def test_hashes_are_unique(self):
        """Two hashes of the same password must differ (bcrypt salting)."""
        plain = "same_password"
        assert hash_password(plain) != hash_password(plain)

    def test_hash_is_not_plaintext(self):
        """The hash string must not contain the original password."""
        plain = "my_secret"
        hashed = hash_password(plain)
        assert plain not in hashed

    def test_empty_password_can_be_hashed(self):
        """Edge-case: empty string should still produce a valid hash."""
        hashed = hash_password("")
        assert verify_password("", hashed) is True
        assert verify_password("nonempty", hashed) is False


# ══════════════════════════════════════════════════════════════════════════════
# 2. JWT tests
# ══════════════════════════════════════════════════════════════════════════════


class TestJWT:
    def test_valid_token_decodes_correctly(self):
        """A freshly issued token must decode to the original payload."""
        payload = {"sub": "user123", "role": "hospital"}
        token = create_access_token(payload)
        decoded = decode_access_token(token)

        assert decoded is not None
        assert decoded["sub"] == "user123"
        assert decoded["role"] == "hospital"

    def test_expired_token_returns_none(self):
        """A token with a past expiry must return None."""
        token = create_access_token({"sub": "user123"}, expires_delta=timedelta(seconds=-1))
        result = decode_access_token(token)
        assert result is None

    def test_tampered_signature_returns_none(self):
        """Modifying any byte of the signature segment must return None."""
        token = create_access_token({"sub": "user123"})
        parts = token.split(".")
        # Flip the last character of the signature
        tampered_sig = parts[2][:-1] + ("A" if parts[2][-1] != "A" else "B")
        tampered_token = ".".join([parts[0], parts[1], tampered_sig])
        result = decode_access_token(tampered_token)
        assert result is None

    def test_tampered_payload_returns_none(self):
        """Modifying the payload segment without re-signing must return None."""
        import base64, json

        token = create_access_token({"sub": "user123"})
        header, _, sig = token.split(".")

        # Craft a fake payload with an elevated role
        fake_payload = {"sub": "user123", "role": "admin"}
        fake_b64 = base64.urlsafe_b64encode(
            json.dumps(fake_payload).encode()
        ).rstrip(b"=").decode()

        tampered = f"{header}.{fake_b64}.{sig}"
        assert decode_access_token(tampered) is None

    def test_custom_expiry(self):
        """Token with a 1-hour expiry must still be valid immediately after issuance."""
        token = create_access_token({"sub": "user123"}, expires_delta=timedelta(hours=1))
        decoded = decode_access_token(token)
        assert decoded is not None

    def test_malformed_token_returns_none(self):
        """Completely invalid strings must return None without raising."""
        assert decode_access_token("not.a.token") is None
        assert decode_access_token("") is None
        assert decode_access_token("eyJ.eyJ.bad") is None


# ══════════════════════════════════════════════════════════════════════════════
# 3. Auth API endpoint tests (using mocked repository)
# ══════════════════════════════════════════════════════════════════════════════


def _make_app_with_mock_repo(mock_repo):
    """
    Build a minimal FastAPI app that overrides the UserRepository dependency
    with a mock, so we can test route logic without a live MongoDB.
    """
    from fastapi import FastAPI
    from app.api.auth import router as auth_router
    from app.repositories.user import get_user_repo

    app = FastAPI()
    app.include_router(auth_router, prefix="/api")
    app.dependency_overrides[get_user_repo] = lambda: mock_repo
    return app


class TestRegisterEndpoint:
    def _mock_repo(self, existing_user=None):
        repo = MagicMock()
        repo.get_by_email = AsyncMock(return_value=existing_user)
        repo.create = AsyncMock(return_value={
            "id": "64f1a2b3c4d5e6f7a8b9c0d1",
            "name": "Test User",
            "email": "test@example.com",
            "role": "hospital",
            "created_at": "2026-01-01T00:00:00+00:00",
        })
        return repo

    def test_successful_registration(self):
        repo = self._mock_repo(existing_user=None)
        client = TestClient(_make_app_with_mock_repo(repo))
        resp = client.post("/api/auth/register", json={
            "name": "Test User",
            "email": "test@example.com",
            "password": "securePass1",
        })
        assert resp.status_code == 201
        data = resp.json()
        assert data["email"] == "test@example.com"
        assert data["role"] == "hospital"
        assert "password_hash" not in data
        assert "password" not in data

    def test_duplicate_email_returns_400(self):
        """Registering the same email twice must return HTTP 400."""
        existing = {
            "id": "64f1a2b3c4d5e6f7a8b9c0d1",
            "name": "Existing",
            "email": "dupe@example.com",
            "role": "hospital",
            "password_hash": "$2b$12$fakehash",
            "created_at": "2026-01-01T00:00:00+00:00",
        }
        repo = self._mock_repo(existing_user=existing)
        client = TestClient(_make_app_with_mock_repo(repo))
        resp = client.post("/api/auth/register", json={
            "name": "Another User",
            "email": "dupe@example.com",
            "password": "anotherPass1",
        })
        assert resp.status_code == 400
        assert "already exists" in resp.json()["detail"]

    def test_weak_password_rejected_by_schema(self):
        """Passwords shorter than 8 characters must fail Pydantic validation."""
        repo = self._mock_repo(existing_user=None)
        client = TestClient(_make_app_with_mock_repo(repo))
        resp = client.post("/api/auth/register", json={
            "name": "Test User",
            "email": "test@example.com",
            "password": "short",  # < 8 chars
        })
        assert resp.status_code == 422

    def test_client_supplied_role_is_ignored(self):
        """A client-supplied role is ignored; user is always registered as hospital."""
        repo = self._mock_repo(existing_user=None)
        client = TestClient(_make_app_with_mock_repo(repo))
        resp = client.post("/api/auth/register", json={
            "name": "Test User",
            "email": "test@example.com",
            "password": "securePass1",
            "role": "super_hacker",
        })
        assert resp.status_code == 201
        assert resp.json()["role"] == "hospital"


class TestLoginEndpoint:
    def _user_doc(self, plain_pw: str) -> dict:
        return {
            "id": "64f1a2b3c4d5e6f7a8b9c0d1",
            "name": "Test User",
            "email": "test@example.com",
            "role": "hospital",
            "password_hash": hash_password(plain_pw),
            "created_at": "2026-01-01T00:00:00+00:00",
        }

    def _mock_repo(self, user_doc):
        repo = MagicMock()
        repo.get_by_email = AsyncMock(return_value=user_doc)
        return repo

    def test_successful_login_returns_token(self):
        doc = self._user_doc("securePass1")
        repo = self._mock_repo(doc)
        client = TestClient(_make_app_with_mock_repo(repo))
        resp = client.post("/api/auth/login", json={
            "email": "test@example.com",
            "password": "securePass1",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert "access_token" in data
        assert data["token_type"] == "bearer"
        # Token must decode correctly
        payload = decode_access_token(data["access_token"])
        assert payload is not None
        assert payload["sub"] == doc["id"]

    def test_wrong_password_returns_401(self):
        doc = self._user_doc("correctPass1")
        repo = self._mock_repo(doc)
        client = TestClient(_make_app_with_mock_repo(repo))
        resp = client.post("/api/auth/login", json={
            "email": "test@example.com",
            "password": "wrongPass1",
        })
        assert resp.status_code == 401

    def test_unknown_email_returns_401(self):
        repo = self._mock_repo(user_doc=None)
        client = TestClient(_make_app_with_mock_repo(repo))
        resp = client.post("/api/auth/login", json={
            "email": "nobody@example.com",
            "password": "doesntMatter",
        })
        assert resp.status_code == 401
