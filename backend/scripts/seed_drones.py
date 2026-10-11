#!/usr/bin/env python3
"""
scripts/seed_drones.py — Seed 10 virtual drones around Bengaluru.

Usage (from project root, with venv active):
    python -m scripts.seed_drones

Or directly:
    python backend/scripts/seed_drones.py

The script is idempotent: it matches on drone_id and upserts, so running it
multiple times will not duplicate documents.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

# Allow running as a standalone script from repo root or backend directory
backend_dir = Path(__file__).resolve().parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

import motor.motor_asyncio
from app.core.config import settings

# ── Drone fleet definition ────────────────────────────────────────────────────
# Coordinates scattered across Bengaluru: lat 12.90–13.05, lng 77.55–77.70
# Status mix: 8 AVAILABLE, 1 CHARGING, 1 MAINTENANCE

DRONES = [
    {
        "drone_id": "DRN-001",
        "model": "Zipline P2 Zip",
        "battery_pct": 98.0,
        "max_payload_kg": 1.75,
        "max_range_km": 40.0,
        "latitude": 13.0358,
        "longitude": 77.5970,
        "status": "AVAILABLE",
        "zone": "North Bengaluru",
    },
    {
        "drone_id": "DRN-002",
        "model": "Zipline P2 Zip",
        "battery_pct": 85.5,
        "max_payload_kg": 1.75,
        "max_range_km": 40.0,
        "latitude": 13.0210,
        "longitude": 77.6150,
        "status": "AVAILABLE",
        "zone": "North Bengaluru",
    },
    {
        "drone_id": "DRN-003",
        "model": "Wingcopter 198",
        "battery_pct": 78.5,
        "max_payload_kg": 6.0,
        "max_range_km": 75.0,
        "latitude": 12.9102,
        "longitude": 77.5680,
        "status": "AVAILABLE",
        "zone": "South Bengaluru",
    },
    {
        "drone_id": "DRN-004",
        "model": "Wingcopter 198",
        "battery_pct": 91.0,
        "max_payload_kg": 6.0,
        "max_range_km": 75.0,
        "latitude": 12.9250,
        "longitude": 77.5820,
        "status": "AVAILABLE",
        "zone": "South Bengaluru",
    },
    {
        "drone_id": "DRN-005",
        "model": "Skydio X10",
        "battery_pct": 88.0,
        "max_payload_kg": 2.5,
        "max_range_km": 25.0,
        "latitude": 12.9800,
        "longitude": 77.6000,
        "status": "AVAILABLE",
        "zone": "East Bengaluru",
    },
    {
        "drone_id": "DRN-006",
        "model": "Skydio X10",
        "battery_pct": 55.0,
        "max_payload_kg": 2.5,
        "max_range_km": 25.0,
        "latitude": 12.9650,
        "longitude": 77.7000,
        "status": "AVAILABLE",
        "zone": "East Bengaluru",
    },
    {
        "drone_id": "DRN-007",
        "model": "DJI Matrice 350 RTK",
        "battery_pct": 88.0,
        "max_payload_kg": 2.7,
        "max_range_km": 20.0,
        "latitude": 12.9720,
        "longitude": 77.5560,
        "status": "AVAILABLE",
        "zone": "West Bengaluru",
    },
    {
        "drone_id": "DRN-008",
        "model": "DJI Matrice 350 RTK",
        "battery_pct": 77.0,
        "max_payload_kg": 2.7,
        "max_range_km": 20.0,
        "latitude": 12.9880,
        "longitude": 77.5600,
        "status": "AVAILABLE",
        "zone": "West Bengaluru",
    },
    {
        "drone_id": "DRN-009",
        "model": "Volansi VOLY C20",
        "battery_pct": 22.0,
        "max_payload_kg": 9.0,
        "max_range_km": 80.0,
        "latitude": 12.9800,
        "longitude": 77.6100,
        "status": "CHARGING",
        "zone": "Central Bengaluru",
    },
    {
        "drone_id": "DRN-010",
        "model": "Volansi VOLY C20",
        "battery_pct": 15.0,
        "max_payload_kg": 9.0,
        "max_range_km": 80.0,
        "latitude": 12.9780,
        "longitude": 77.5990,
        "status": "MAINTENANCE",
        "zone": "Central Bengaluru",
    },
]


async def seed() -> None:
    print(f"Using database: {settings.MONGODB_DATABASE}")
    client = motor.motor_asyncio.AsyncIOMotorClient(settings.MONGODB_URI)
    db = client[settings.MONGODB_DATABASE]
    col = db["drones"]

    now = datetime.now(UTC)
    upserted = 0
    matched = 0

    for drone in DRONES:
        drone["updated_at"] = now
        result = await col.update_one(
            {"drone_id": drone["drone_id"]},
            {"$set": drone},
            upsert=True,
        )
        if result.upserted_id:
            upserted += 1
        else:
            matched += 1

    total = await col.count_documents({})
    print(f"\n✅  Seed complete — {upserted} inserted, {matched} updated")
    print(f"   Total drones in collection: {total}\n")

    # Print a sample document (first AVAILABLE drone)
    sample = await col.find_one({"status": "AVAILABLE"})
    if sample:
        sample["_id"] = str(sample["_id"])
        sample["updated_at"] = sample["updated_at"].isoformat()
        print("   Sample document (first AVAILABLE drone):")
        print(json.dumps(sample, indent=4))

    client.close()


if __name__ == "__main__":
    asyncio.run(seed())
