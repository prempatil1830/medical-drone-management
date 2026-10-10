"""
Authentication endpoints and shared dependency.

Endpoints
---------
POST /api/auth/register   — create account, return UserResponse
POST /api/auth/login      — verify credentials, return JWT + UserResponse

Dependency
----------
get_current_user(token)   — validates Bearer JWT; raises HTTP 401 on failure.
                            Import this from other routers to protect endpoints.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer

from app.core.logging import get_logger
from app.core.security import create_access_token, decode_access_token, hash_password, verify_password
from app.repositories.user import UserRepository, get_user_repo
from app.schemas.user import LoginRequest, LoginResponse, UserCreate, UserResponse, UserRole

log = get_logger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])

# Token extraction: reads "Authorization: Bearer <token>" header
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")


# ── Shared dependency ────────────────────────────────────────────────────────


async def get_current_user(
    token: str = Depends(oauth2_scheme),
    repo: UserRepository = Depends(get_user_repo),
) -> dict:
    """
    Validate the Bearer JWT and return the authenticated user document.

    Raises HTTP 401 if the token is missing, expired, tampered, or the
    referenced user no longer exists.
    """
    credentials_exc = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    payload = decode_access_token(token)
    if payload is None:
        raise credentials_exc

    user_id: str | None = payload.get("sub")
    if user_id is None:
        raise credentials_exc

    user = await repo.get_by_id(user_id)
    if user is None:
        raise credentials_exc

    return user


def require_role(*allowed_roles: str | UserRole):
    """
    Dependency factory to enforce role-based access control (RBAC).

    Roles: hospital, operator, admin.
    Denies (403) unless the user's role is in allowed_set, including when role is None or missing.
    """
    allowed_set: set[str] = {
        r.value if isinstance(r, UserRole) else str(r)
        for r in allowed_roles
    }

    async def _role_checker(current_user: dict = Depends(get_current_user)) -> dict:
        user_role = current_user.get("role")
        # Fail-closed: deny if role is None, missing, or not in allowed set
        if not user_role or user_role not in allowed_set:
            log.warning("rbac_access_denied", user_role=user_role, allowed=list(allowed_set))
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Access denied. Required role: {', '.join(sorted(allowed_set))}. Current role: '{user_role}'.",
            )
        return current_user

    return _role_checker


# ── Registration ──────────────────────────────────────────────────────────────


@router.post(
    "/register",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new user",
)
async def register(
    payload: UserCreate,
    repo: UserRepository = Depends(get_user_repo),
) -> UserResponse:
    """
    Create a new user account.

    * Public registration creates ONLY 'hospital' users with center_id=None.
      Client-supplied elevated role or center_id are strictly ignored.
    * Email must be unique — returns ``400`` if already registered.
    * Password is bcrypt-hashed before storage; it is never echoed back.
    """
    existing = await repo.get_by_email(payload.email)
    if existing:
        log.warning("register_duplicate_email", email=payload.email)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="A user with this email already exists.",
        )

    # Public registration forces hospital role and center_id=None
    user_doc = {
        "name": payload.name,
        "email": payload.email,
        "role": UserRole.hospital.value,
        "center_id": None,
        "password_hash": hash_password(payload.password),
    }
    created = await repo.create(user_doc)
    log.info("user_registered", user_id=created["id"])
    return UserResponse(**created)


# ── Login ─────────────────────────────────────────────────────────────────────


@router.post(
    "/login",
    response_model=LoginResponse,
    summary="Obtain a JWT access token",
)
async def login(
    payload: LoginRequest,
    repo: UserRepository = Depends(get_user_repo),
) -> LoginResponse:
    """
    Verify email + password and return a signed JWT.

    Returns ``401`` for unknown email or wrong password (deliberately
    undifferentiated to prevent user enumeration).
    """
    invalid_exc = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid email or password.",
        headers={"WWW-Authenticate": "Bearer"},
    )

    user = await repo.get_by_email(payload.email)
    if user is None:
        raise invalid_exc

    if not verify_password(payload.password, user["password_hash"]):
        log.warning("login_bad_password", email=payload.email)
        raise invalid_exc

    token = create_access_token({"sub": user["id"], "role": user["role"]})
    log.info("user_logged_in", user_id=user["id"])

    return LoginResponse(
        access_token=token,
        user=UserResponse(**user),
    )
