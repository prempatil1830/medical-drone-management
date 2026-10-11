#!/usr/bin/env python3
"""
scripts/migrate_roles.py — Migration script for legacy user roles.

Usage:
    # Dry run (default):
    python scripts/migrate_roles.py

    # Apply migrations (maps hospital_admin -> hospital; system_admin -> admin for allowed emails):
    python scripts/migrate_roles.py --apply --allow-admin admin@example.com super@example.com
"""

import argparse
import asyncio
import os
import sys
from pathlib import Path

# Add backend directory to path if needed
backend_dir = Path(__file__).resolve().parent.parent / "backend"
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))
root_dir = Path(__file__).resolve().parent.parent
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))

from app.core.config import settings
from app.db.database import close_db, connect_db, get_database

STANDARD_ROLES = {"hospital", "operator", "admin"}


async def run_migration(apply: bool, allow_admin: list[str]) -> None:
    allow_admin_set = set(allow_admin or [])

    await connect_db()
    db = get_database()
    users_col = db["users"]

    # Find users whose role is not in the standard set (or missing)
    cursor = users_col.find({"$or": [{"role": {"$nin": list(STANDARD_ROLES)}}, {"role": None}]})
    legacy_users = await cursor.to_list(length=1000)

    print(f"Found {len(legacy_users)} user(s) with non-standard role.")
    print("-" * 70)

    migrated_count = 0
    skipped_count = 0

    for user in legacy_users:
        email = user.get("email")
        role = user.get("role")
        center_id = user.get("center_id")
        user_id = str(user.get("_id"))

        # Print user info (NO hashes)
        print(f"User ID: {user_id} | Email: {email} | Current Role: {role} | Center ID: {center_id}")

        target_role = None
        if role == "hospital_admin":
            target_role = "hospital"
        elif role == "system_admin":
            if email in allow_admin_set:
                target_role = "admin"
            else:
                print(f"  [SKIPPED] Email '{email}' not in --allow-admin list for system_admin -> admin")
                skipped_count += 1
                continue
        else:
            print(f"  [SKIPPED] Role '{role}' has no automatic mapping rule.")
            skipped_count += 1
            continue

        if apply:
            await users_col.update_one({"_id": user["_id"]}, {"$set": {"role": target_role}})
            print(f"  [APPLIED] Role migrated: {role} -> {target_role}")
            migrated_count += 1
        else:
            print(f"  [DRY-RUN] Would migrate role: {role} -> {target_role}")
            migrated_count += 1

    print("-" * 70)
    mode = "APPLY" if apply else "DRY-RUN"
    print(f"Summary ({mode}): {migrated_count} eligible/migrated, {skipped_count} skipped.")
    await close_db()


def main():
    print(f"Using database: {settings.MONGODB_DATABASE}")
    parser = argparse.ArgumentParser(description="Migrate legacy user roles to standard roles.")
    parser.add_argument(
        "--apply",
        action="store_true",
        default=False,
        help="Apply changes to MongoDB (default: dry-run only).",
    )
    parser.add_argument(
        "--allow-admin",
        nargs="*",
        default=[],
        help="List of emails allowed to migrate from system_admin to admin.",
    )
    args = parser.parse_args()

    asyncio.run(run_migration(apply=args.apply, allow_admin=args.allow_admin))


if __name__ == "__main__":
    main()
