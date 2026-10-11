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
            assert calls[0][0][1]["$set"]["battery_pct"] == pytest.approx(76.0)

            # Doc 2: 50.0 + 1.0 = 51.0
            assert calls[1][0][0] == {"_id": "doc2", "status": "CHARGING"}
            assert calls[1][0][1]["$set"]["battery_pct"] == pytest.approx(51.0)

            # Doc 3: 79.9 + 1.0 = 80.9 (>= 80, so becomes AVAILABLE)
            assert calls[2][0][0] == {"_id": "doc3", "status": "CHARGING"}
            assert calls[2][0][1]["$set"]["battery_pct"] == pytest.approx(80.9)
            assert calls[2][0][1]["$set"]["status"] == "AVAILABLE"
            
        finally:
            settings.SIMULATION_TICK_INTERVAL_SEC = original_tick
            settings.DRONE_RECHARGE_RATE_PCT_PER_MIN = original_rate
            settings.SIMULATION_SPEED_MULTIPLIER = original_mult
            settings.DRONE_AVAILABLE_AT_PCT = original_avail


@pytest.mark.asyncio
async def test_recharge_math_battery_increase():
    """
    Test exact recharge math:
    battery: 40.0%
    recharge rate: 2.0% / min
    multiplier: 8.0x
    tick interval: 30.0 sec -> elapsed = (30/60) * 8 = 4.0 simulated min
    gain = 4.0 * 2.0 = 8.0%
    new battery: 40.0 + 8.0 = 48.0%
    """
    with patch("app.simulation.recharge.get_database") as get_db:
        mock_db = AsyncMock()
        drones_col = AsyncMock()

        async def mock_find_results():
            yield {"_id": "d-math", "status": "CHARGING", "battery_pct": 40.0}

        from unittest.mock import MagicMock, Mock
        drones_col.find = MagicMock(return_value=mock_find_results())
        mock_db.__getitem__.side_effect = lambda name: drones_col if name == "drones" else AsyncMock()
        get_db.return_value = mock_db

        service = RechargeService()
        orig_tick = settings.SIMULATION_TICK_INTERVAL_SEC
        orig_rate = settings.DRONE_RECHARGE_RATE_PCT_PER_MIN
        orig_mult = settings.SIMULATION_SPEED_MULTIPLIER
        orig_avail = settings.DRONE_AVAILABLE_AT_PCT

        settings.SIMULATION_TICK_INTERVAL_SEC = 30.0
        settings.DRONE_RECHARGE_RATE_PCT_PER_MIN = 2.0
        settings.SIMULATION_SPEED_MULTIPLIER = 8.0
        settings.DRONE_AVAILABLE_AT_PCT = 80.0

        try:
            service._stop_event.is_set = Mock(side_effect=[False, True])
            with patch("asyncio.wait_for", new_callable=AsyncMock):
                await service._recharge_loop()

            assert drones_col.update_one.call_count == 1
            call_args = drones_col.update_one.call_args[0]
            assert call_args[0] == {"_id": "d-math", "status": "CHARGING"}
            assert call_args[1]["$set"]["battery_pct"] == pytest.approx(48.0)
            assert "status" not in call_args[1]["$set"]  # still under 80%
        finally:
            settings.SIMULATION_TICK_INTERVAL_SEC = orig_tick
            settings.DRONE_RECHARGE_RATE_PCT_PER_MIN = orig_rate
            settings.SIMULATION_SPEED_MULTIPLIER = orig_mult
            settings.DRONE_AVAILABLE_AT_PCT = orig_avail


@pytest.mark.asyncio
async def test_recharge_reaches_80_becomes_available():
    """
    When battery recharges to or above 80.0%, status must transition to AVAILABLE:
    battery: 78.0% + 4.0% -> 82.0% >= 80.0% -> AVAILABLE.
    """
    with patch("app.simulation.recharge.get_database") as get_db:
        mock_db = AsyncMock()
        drones_col = AsyncMock()

        async def mock_find_results():
            yield {"_id": "d-avail", "status": "CHARGING", "battery_pct": 78.0}

        from unittest.mock import MagicMock, Mock
        drones_col.find = MagicMock(return_value=mock_find_results())
        mock_db.__getitem__.side_effect = lambda name: drones_col if name == "drones" else AsyncMock()
        get_db.return_value = mock_db

        service = RechargeService()
        orig_tick = settings.SIMULATION_TICK_INTERVAL_SEC
        orig_rate = settings.DRONE_RECHARGE_RATE_PCT_PER_MIN
        orig_mult = settings.SIMULATION_SPEED_MULTIPLIER
        orig_avail = settings.DRONE_AVAILABLE_AT_PCT

        settings.SIMULATION_TICK_INTERVAL_SEC = 60.0
        settings.DRONE_RECHARGE_RATE_PCT_PER_MIN = 4.0
        settings.SIMULATION_SPEED_MULTIPLIER = 1.0
        settings.DRONE_AVAILABLE_AT_PCT = 80.0

        try:
            service._stop_event.is_set = Mock(side_effect=[False, True])
            with patch("asyncio.wait_for", new_callable=AsyncMock):
                await service._recharge_loop()

            assert drones_col.update_one.call_count == 1
            call_args = drones_col.update_one.call_args[0]
            assert call_args[0] == {"_id": "d-avail", "status": "CHARGING"}
            assert call_args[1]["$set"]["battery_pct"] == pytest.approx(82.0)
            assert call_args[1]["$set"]["status"] == "AVAILABLE"
        finally:
            settings.SIMULATION_TICK_INTERVAL_SEC = orig_tick
            settings.DRONE_RECHARGE_RATE_PCT_PER_MIN = orig_rate
            settings.SIMULATION_SPEED_MULTIPLIER = orig_mult
            settings.DRONE_AVAILABLE_AT_PCT = orig_avail


@pytest.mark.asyncio
async def test_recharge_non_charging_drones_untouched():
    """
    Query filter must strictly be {"status": "CHARGING"}.
    Drones in AVAILABLE, ASSIGNED, IN_FLIGHT, MAINTENANCE are never selected.
    """
    with patch("app.simulation.recharge.get_database") as get_db:
        mock_db = AsyncMock()
        drones_col = AsyncMock()

        async def mock_empty_results():
            if False:
                yield {}

        from unittest.mock import MagicMock, Mock
        drones_col.find = MagicMock(return_value=mock_empty_results())
        mock_db.__getitem__.side_effect = lambda name: drones_col if name == "drones" else AsyncMock()
        get_db.return_value = mock_db

        service = RechargeService()
        service._stop_event.is_set = Mock(side_effect=[False, True])
        with patch("asyncio.wait_for", new_callable=AsyncMock):
            await service._recharge_loop()

        # Verified find query filter
        drones_col.find.assert_called_once_with({"status": "CHARGING"})
        # No updates performed
        assert drones_col.update_one.call_count == 0


@pytest.mark.asyncio
async def test_recharge_assigned_between_read_and_write_not_overwritten():
    """
    Atomic guard: update_one includes {"status": "CHARGING"} in the filter.
    If another process sets status to ASSIGNED between read and write, MongoDB matches 0 docs.
    """
    with patch("app.simulation.recharge.get_database") as get_db:
        mock_db = AsyncMock()
        drones_col = AsyncMock()

        async def mock_find():
            yield {"_id": "d-race", "status": "CHARGING", "battery_pct": 50.0}

        from unittest.mock import MagicMock, Mock
        drones_col.find = MagicMock(return_value=mock_find())
        # Simulate update_one returning matched_count=0 because status changed to ASSIGNED
        update_result = MagicMock()
        update_result.matched_count = 0
        update_result.modified_count = 0
        drones_col.update_one = AsyncMock(return_value=update_result)
        mock_db.__getitem__.side_effect = lambda name: drones_col if name == "drones" else AsyncMock()
        get_db.return_value = mock_db

        service = RechargeService()
        service._stop_event.is_set = Mock(side_effect=[False, True])
        with patch("asyncio.wait_for", new_callable=AsyncMock):
            await service._recharge_loop()

        assert drones_col.update_one.call_count == 1
        filter_doc = drones_col.update_one.call_args[0][0]
        # Guard verification
        assert filter_doc == {"_id": "d-race", "status": "CHARGING"}


@pytest.mark.asyncio
async def test_recharge_clean_task_cancellation():
    """
    RechargeService start() starts a background task and stop() cleanly cancels and awaits it.
    """
    service = RechargeService()
    assert service._task is None

    with patch("app.simulation.recharge.get_database") as get_db:
        mock_db = AsyncMock()
        drones_col = AsyncMock()

        async def infinite_find():
            while True:
                await asyncio.sleep(10)
                yield {}

        from unittest.mock import MagicMock
        drones_col.find = MagicMock(return_value=infinite_find())
        mock_db.__getitem__.side_effect = lambda name: drones_col if name == "drones" else AsyncMock()
        get_db.return_value = mock_db

        service.start()
        assert service._task is not None
        assert not service._task.done()

        # Stop service
        await service.stop()
        assert service._task is None
        assert service._stop_event.is_set()

