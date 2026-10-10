import asyncio
import pytest
from unittest.mock import patch, AsyncMock

from app.simulation.recharge import RechargeService
from app.core.config import settings

@pytest.mark.asyncio
async def test_recharge_service_logic():
    # Setup mock DB
    with patch("app.simulation.recharge.get_database") as get_db:
        mock_db = AsyncMock()
        drones_col = AsyncMock()
        
        # We need an async generator for the find method
        async def mock_find_results():
            yield {"_id": "doc1", "status": "CHARGING", "battery_pct": 75.0}
            yield {"_id": "doc2", "status": "CHARGING", "battery_pct": 50.0}
            yield {"_id": "doc3", "status": "CHARGING", "battery_pct": 79.9}
        
        from unittest.mock import MagicMock
        drones_col.find = MagicMock(return_value=mock_find_results())
        
        def db_getitem(name):
            if name == "drones":
                return drones_col
            return AsyncMock()
            
        mock_db.__getitem__.side_effect = db_getitem
        get_db.return_value = mock_db
        
        service = RechargeService()
        
        # Override config for predictable values
        original_tick = settings.SIMULATION_TICK_INTERVAL_SEC
        original_rate = settings.DRONE_RECHARGE_RATE_PCT_PER_MIN
        original_mult = settings.SIMULATION_SPEED_MULTIPLIER
        original_avail = settings.DRONE_AVAILABLE_AT_PCT
        
        settings.SIMULATION_TICK_INTERVAL_SEC = 60.0 # 1 minute tick
        settings.DRONE_RECHARGE_RATE_PCT_PER_MIN = 1.0 # 1% per real minute
        settings.SIMULATION_SPEED_MULTIPLIER = 1.0 # 1x speed
        settings.DRONE_AVAILABLE_AT_PCT = 80.0
        
        try:
            # We just want to run one loop iteration manually
            # But _recharge_loop runs indefinitely.
            # We'll set the stop event so it exits after one pass (wait_for timeout will catch it or the while loop will exit)
            service._stop_event.set()
            # To actually run the inner code, we need to not be stopped immediately... 
            # Actually, we can just call it and it will not enter the loop if stop_event is set.
            # Let's mock _stop_event.is_set to return False then True
            from unittest.mock import Mock
            is_set_mock = Mock(side_effect=[False, True])
            service._stop_event.is_set = is_set_mock
            
            # and patch wait_for to immediately return
            with patch("asyncio.wait_for", new_callable=AsyncMock) as mock_wait:
                await service._recharge_loop()
            
            # Assertions
            assert drones_col.update_one.call_count == 3
            
            # Check updates
            calls = drones_col.update_one.call_args_list
            
            # Doc 1: 75.0 + 1.0 = 76.0
            assert calls[0][0][0] == {"_id": "doc1", "status": "CHARGING"}
            assert calls[0][0][1] == {"$set": {"battery_pct": 76.0}}
            
            # Doc 2: 50.0 + 1.0 = 51.0
            assert calls[1][0][0] == {"_id": "doc2", "status": "CHARGING"}
            assert calls[1][0][1] == {"$set": {"battery_pct": 51.0}}
            
            # Doc 3: 79.9 + 1.0 = 80.9 (>= 80, so becomes AVAILABLE)
            assert calls[2][0][0] == {"_id": "doc3", "status": "CHARGING"}
            assert calls[2][0][1] == {"$set": {"battery_pct": 80.9, "status": "AVAILABLE"}}
            
        finally:
            settings.SIMULATION_TICK_INTERVAL_SEC = original_tick
            settings.DRONE_RECHARGE_RATE_PCT_PER_MIN = original_rate
            settings.SIMULATION_SPEED_MULTIPLIER = original_mult
            settings.DRONE_AVAILABLE_AT_PCT = original_avail
