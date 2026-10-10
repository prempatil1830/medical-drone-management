"""
Security utilities: password hashing (bcrypt) and JWT management (PyJWT).

Public API
----------
hash_password(plain)         -> str           — bcrypt-hash a plaintext password
verify_password(plain, hash) -> bool          — constant-time comparison
create_access_token(data)    -> str           — signed JWT with expiry
decode_access_token(token)   -> dict | None   — decode/validate; None on failure
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, Optional

import bcrypt
import jwt

from app.core.config import settings
from app.core.logging import get_logger

log = get_logger(__name__)


# ── Password hashing ──────────────────────────────────────────────────────────


def hash_password(plain: str) -> str:
    """Return a bcrypt hash of *plain* as a UTF-8 string."""
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(plain.encode(), salt).decode()


def verify_password(plain: str, hashed: str) -> bool:
    """Return True if *plain* matches *hashed* (constant-time check)."""
    return bcrypt.checkpw(plain.encode(), hashed.encode())


# ── JWT ───────────────────────────────────────────────────────────────────────


def create_access_token(
    data: dict[str, Any],
    expires_delta: Optional[timedelta] = None,
) -> str:
    """
    Create a signed JWT.

    Parameters
    ----------
    data : dict
        Payload to embed (e.g. {"sub": user_id, "role": "hospital_admin"}).
    expires_delta : timedelta | None
        Override default expiry.  Defaults to settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES.

    Returns
    -------
    str
        Compact serialised JWT.
    """
    payload = data.copy()
    expire = datetime.now(UTC) + (
        expires_delta
        if expires_delta is not None
        else timedelta(minutes=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    payload["exp"] = expire
    payload["iat"] = datetime.now(UTC)

    token = jwt.encode(
        payload,
        settings.JWT_SECRET,
        algorithm=settings.JWT_ALGORITHM,
    )
    log.debug("access_token_created", subject=data.get("sub"))
    return token


def decode_access_token(token: str) -> Optional[dict[str, Any]]:
    """
    Validate and decode a JWT.

    Returns the payload dict on success, or None on any failure
    (expired, tampered signature, malformed, etc.).
    """
    try:
        payload = jwt.decode(
            token,
            settings.JWT_SECRET,
            algorithms=[settings.JWT_ALGORITHM],
        )
        return payload
    except jwt.ExpiredSignatureError:
        log.warning("jwt_expired")
        return None
    except jwt.InvalidTokenError as exc:
        log.warning("jwt_invalid", error=str(exc))
        return None
