#!/usr/bin/env python3
"""
scripts/seed_users.py — Create operator or admin users from CLI args or environment variables.

Never hardcodes credentials.

Usage:
    # Using CLI arguments:
    python scripts/seed_users.py --email admin@example.com --password secretpass --name "System Admin" --role admin

    # Using environment variables:
    SEED_USER_EMAIL=operator@example.com SEED_USER_PASSWORD=secretpass SEED_USER_ROLE=operator python scripts/seed_users.py
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

# Add project root and backend directory to path
backend_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(backend_dir))

from app.core.security import hash_password
from app.db.database import close_db, connect_db, get_database
from app.repositories.user import UserRepository
from app.schemas.user import UserRole


async def seed_user(
    email: str,
    password: str,
    name: str,
    role: str,
    center_id: str | None = None,
) -> dict:
    if role not in ("operator", "admin", "hospital", "hospital_admin", "system_admin"):
        raise ValueError(f"Invalid role: {role}. Allowed roles: operator, admin, hospital.")

    await connect_db()
    try:
        db = get_database()
        repo = UserRepository(db)
        await repo.ensure_indexes()

        existing = await repo.get_by_email(email)
        pwd_hash = hash_password(password)

        if existing:
            # Update role and password
            await repo._col.update_one(
                {"_id": existing["_id"]},
                {"$set": {"name": name, "role": role, "password_hash": pwd_hash, "center_id": center_id}},
            )
            print(f"Updated existing user '{email}' with role '{role}'.")
            return existing
        else:
            user_doc = {
                "name": name,
                "email": email,
                "role": role,
                "center_id": center_id,
                "password_hash": pwd_hash,
            }
            created = await repo.create(user_doc)
            print(f"Created new user '{email}' (ID: {created['id']}) with role '{role}'.")
            return created
    finally:
        await close_db()


def main():
    parser = argparse.ArgumentParser(description="Seed operator or admin users into MongoDB.")
    parser.add_argument(
        "--email",
        default=os.getenv("SEED_USER_EMAIL") or os.getenv("ADMIN_EMAIL"),
        help="User email address (env: SEED_USER_EMAIL or ADMIN_EMAIL)",
    )
    parser.add_argument(
        "--password",
        default=os.getenv("SEED_USER_PASSWORD") or os.getenv("ADMIN_PASSWORD"),
        help="User password (env: SEED_USER_PASSWORD or ADMIN_PASSWORD)",
    )
    parser.add_argument(
        "--name",
        default=os.getenv("SEED_USER_NAME") or os.getenv("ADMIN_NAME") or "Platform Operator",
        help="User full name (env: SEED_USER_NAME or ADMIN_NAME)",
    )
    parser.add_argument(
        "--role",
        default=os.getenv("SEED_USER_ROLE") or os.getenv("ADMIN_ROLE") or "operator",
        choices=["operator", "admin", "hospital", "hospital_admin", "system_admin"],
        help="User role (env: SEED_USER_ROLE or ADMIN_ROLE, default: operator)",
    )
    parser.add_argument(
        "--center-id",
        default=os.getenv("SEED_USER_CENTER_ID"),
        help="Medical Center ID (for hospital users, optional)",
    )

    args = parser.parse_args()

    if not args.email or not args.password:
        parser.error(
            "Both --email and --password (or env vars SEED_USER_EMAIL and SEED_USER_PASSWORD) are required."
        )

    asyncio.run(
        seed_user(
            email=args.email,
            password=args.password,
            name=args.name,
            role=args.role,
            center_id=args.center_id,
        )
    )


if __name__ == "__main__":
    main()
