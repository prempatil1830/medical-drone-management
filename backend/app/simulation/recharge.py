import asyncio
from datetime import UTC, datetime
from typing import Optional

from app.core.config import settings
from app.core.logging import get_logger
from app.db.database import get_database
from app.repositories.drone import DroneRepository

log = get_logger(__name__)

class RechargeService:
    def __init__(self):
        self._task: Optional[asyncio.Task] = None
        self._stop_event = asyncio.Event()

    def start(self):
        if self._task is None:
            self._stop_event.clear()
            self._task = asyncio.create_task(self._recharge_loop())

    async def stop(self):
        if self._task:
            self._stop_event.set()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def _recharge_loop(self):
        db = get_database()
        drone_repo = DroneRepository(db)
        
        tick_sec = settings.SIMULATION_TICK_INTERVAL_SEC
        recharge_rate = settings.DRONE_RECHARGE_RATE_PCT_PER_MIN
        speed_mult = settings.SIMULATION_SPEED_MULTIPLIER
        available_pct = settings.DRONE_AVAILABLE_AT_PCT
        
        elapsed_minutes = (tick_sec / 60.0) * speed_mult

        while not self._stop_event.is_set():
            try:
                # Find all charging drones
                cursor = db["drones"].find({"status": "CHARGING"})
                async for drone in cursor:
                    current_batt = drone.get("battery_pct", 0.0)
                    new_batt = current_batt + (recharge_rate * elapsed_minutes)
                    new_batt = min(100.0, new_batt)
                    
                    update_doc = {"$set": {"battery_pct": new_batt}}
                    if new_batt >= available_pct:
                        update_doc["$set"]["status"] = "AVAILABLE"
                        
                    # Conditional update: only if it's still CHARGING
                    await db["drones"].update_one(
                        {"_id": drone["_id"], "status": "CHARGING"},
                        update_doc
                    )
                    
            except Exception as e:
                log.error("recharge_loop_error", error=str(e))
                
            try:
                # Use wait_for to allow quick cancellation
                await asyncio.wait_for(self._stop_event.wait(), timeout=tick_sec)
            except asyncio.TimeoutError:
                pass

recharge_service = RechargeService()
