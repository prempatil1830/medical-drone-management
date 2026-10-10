import sys
from pathlib import Path
import asyncio

backend_dir = Path("backend").resolve()
sys.path.insert(0, str(backend_dir))

from app.db.database import get_database, connect_db, close_db
from app.repositories.mission_tracking import MissionTrackingRepository

async def run_task9():
    await connect_db()
    db = get_database()
    tracking_repo = MissionTrackingRepository(db)
    
    mission_id = "MISSION_TEST_9"
    trackings = await tracking_repo.get_by_mission(mission_id)
    print(f"Mission Tracking Count: {len(trackings)}")
    if trackings:
        # get_by_mission usually returns descending order (latest first)
        last = trackings[0]
        first = trackings[-1]
        print(f"First tracking: status={first['status']}, lat={first['lat']}, lng={first['lng']}")
        print(f"Last tracking: status={last['status']}, lat={last['lat']}, lng={last['lng']}")
        
    await close_db()

asyncio.run(run_task9())

