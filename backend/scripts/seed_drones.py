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

# Allow running as a standalone script from repo root
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import motor.motor_asyncio
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent.parent / ".env")

MONGODB_URI = os.getenv("MONGODB_URI", "mongodb://localhost:27017")
MONGODB_DATABASE = os.getenv("MONGODB_DATABASE", "medical_drone_db")

# ── Drone fleet definition ────────────────────────────────────────────────────
# Coordinates scattered across Bengaluru: lat 12.90–13.05, lng 77.55–77.70
# Status mix: 8 AVAILABLE, 1 CHARGING, 1 MAINTENANCE

DRONES = [
    {
        "drone_id": "BLR-D001",
        "model": "MediHawk X200",
        "battery_pct": 98.0,
        "max_payload_kg": 5.0,
        "max_range_km": 25.0,
        "latitude": 12.9716,
        "longitude": 77.5946,
        "status": "AVAILABLE",
        "zone": "Central Bengaluru",
    },
    {
        "drone_id": "BLR-D002",
        "model": "MediHawk X200",
        "battery_pct": 85.5,
        "max_payload_kg": 5.0,
        "max_range_km": 25.0,
        "latitude": 13.0358,
        "longitude": 77.5970,
        "status": "AVAILABLE",
        "zone": "Yelahanka",
    },
    {
        "drone_id": "BLR-D003",
        "model": "CargoSky Pro",
        "battery_pct": 72.0,
        "max_payload_kg": 10.0,
        "max_range_km": 40.0,
        "latitude": 12.9352,
        "longitude": 77.6245,
        "status": "AVAILABLE",
        "zone": "Koramangala",
    },
    {
        "drone_id": "BLR-D004",
        "model": "CargoSky Pro",
        "battery_pct": 91.0,
        "max_payload_kg": 10.0,
        "max_range_km": 40.0,
        "latitude": 12.9279,
        "longitude": 77.6271,
        "status": "AVAILABLE",
        "zone": "BTM Layout",
    },
    {
        "drone_id": "BLR-D005",
        "model": "SwiftMed 100",
        "battery_pct": 64.0,
        "max_payload_kg": 2.5,
        "max_range_km": 15.0,
        "latitude": 13.0012,
        "longitude": 77.5553,
        "status": "AVAILABLE",
        "zone": "Rajajinagar",
    },
    {
        "drone_id": "BLR-D006",
        "model": "SwiftMed 100",
        "battery_pct": 55.0,
        "max_payload_kg": 2.5,
        "max_range_km": 15.0,
        "latitude": 12.9592,
        "longitude": 77.6974,
        "status": "AVAILABLE",
        "zone": "Whitefield",
    },
    {
        "drone_id": "BLR-D007",
        "model": "MediHawk X300",
        "battery_pct": 88.0,
        "max_payload_kg": 8.0,
        "max_range_km": 35.0,
        "latitude": 13.0475,
        "longitude": 77.6160,
        "status": "AVAILABLE",
        "zone": "Hebbal",
    },
    {
        "drone_id": "BLR-D008",
        "model": "MediHawk X300",
        "battery_pct": 77.0,
        "max_payload_kg": 8.0,
        "max_range_km": 35.0,
        "latitude": 12.9255,
        "longitude": 77.5638,
        "status": "AVAILABLE",
        "zone": "Jayanagar",
    },
    {
        "drone_id": "BLR-D009",
        "model": "CargoSky Pro",
        "battery_pct": 22.0,
        "max_payload_kg": 10.0,
        "max_range_km": 40.0,
        "latitude": 12.9698,
        "longitude": 77.7499,
        "status": "CHARGING",
        "zone": "Electronic City",
    },
    {
        "drone_id": "BLR-D010",
        "model": "SwiftMed 100",
        "battery_pct": 0.0,
        "max_payload_kg": 2.5,
        "max_range_km": 15.0,
        "latitude": 12.9165,
        "longitude": 77.6011,
        "status": "MAINTENANCE",
        "zone": "Banashankari",
    },
]


async def seed() -> None:
    client = motor.motor_asyncio.AsyncIOMotorClient(MONGODB_URI)
    db = client[MONGODB_DATABASE]
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
