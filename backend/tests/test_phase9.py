"""
Tests for Phase 9: Drone Simulation Engine and WebSockets.
"""

from unittest.mock import AsyncMock, patch

import pytest

from app.simulation.engine import SimulationEngine
from app.websocket.manager import ConnectionManager


@pytest.mark.asyncio
async def test_simulation_engine_run():
    # Mock repositories and DB interactions
    with patch("app.simulation.engine.get_database") as get_db, \
         patch("app.simulation.engine.manager.broadcast_to_mission", new_callable=AsyncMock) as mock_broadcast, \
         patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:

        mock_db = {}
        
        # In-memory collections to capture updates
        missions_col = AsyncMock()
        drones_col = AsyncMock()
        trackings = []

        # Setup find_one mock for mission
        mission_repo_mock = AsyncMock()
        mission_repo_mock.get_by_id.return_value = {
            "mission_id": "miss-sim-123",
            "request_id": "req-sim-123",
            "drone_id": "BLR-SIM-99",
            "route": [
                {"lat": 12.9716, "lng": 77.5946}, # Pickup (Lalbagh)
                {"lat": 12.9352, "lng": 77.6245}, # Destination (Koramangala)
            ],
            "distance_km": 5.18,
            "eta_minutes": 5.18,
            "battery_required_pct": 7.77,
            "status": "ASSIGNED"
        }

        # Setup find_one mock for drone
        drone_repo_mock = AsyncMock()
        drone_repo_mock.get_by_drone_id.return_value = {
            "drone_id": "BLR-SIM-99",
            "status": "ASSIGNED",
            "battery_pct": 100.0,
            "latitude": 12.9716,
            "longitude": 77.5946, # Starts exactly at pickup for simpler test
        }

        # Setup insert mock for tracking
        tracking_repo_mock = AsyncMock()
        async def mock_create(data):
            trackings.append(data)
            return {"id": "mock-tracking-id"}
        tracking_repo_mock.create.side_effect = mock_create

        # Mock database call dispatching
        def db_getitem(name):
            if name == "missions":
                return missions_col
            if name == "drones":
                return drones_col
            return AsyncMock()

        db_mock = AsyncMock()
        db_mock.__getitem__.side_effect = db_getitem
        get_db.return_value = db_mock

        # Instantiating engine with mocked repos
        with patch("app.simulation.engine.MissionRepository", return_value=mission_repo_mock), \
             patch("app.simulation.engine.DroneRepository", return_value=drone_repo_mock), \
             patch("app.simulation.engine.MissionTrackingRepository", return_value=tracking_repo_mock):
             
             engine = SimulationEngine()
             await engine.run_mission_simulation("miss-sim-123")

        # Assertions
        # 1. Mission statuses transitioned sequentially:
        # Since it starts at pickup (dist=0), it triggers PACKAGE_COLLECTED -> IN_TRANSIT -> DELIVERED
        # Verify missions status was updated
        assert missions_col.update_one.call_count >= 3
        
        # Verify drone is reset back to AVAILABLE on completion
        drone_repo_mock.release_drone.assert_called_once_with(
            drone_id="BLR-SIM-99",
            latitude=12.9352,
            longitude=77.6245,
            battery_pct=92.22291830024075,
            new_status="AVAILABLE",
        )

        # 2. Tracking logs were written
        assert len(trackings) >= 3
        assert trackings[0]["status"] == "PACKAGE_COLLECTED"
        assert trackings[-1]["status"] == "DELIVERED"
        assert trackings[-1]["lat"] == 12.9352  # Arrived at destination
        assert trackings[-1]["lng"] == 77.6245

        # 3. Broadcast was triggered
        assert mock_broadcast.call_count >= 3
        last_broadcast_message = mock_broadcast.call_args[0][1]
        assert last_broadcast_message["status"] == "DELIVERED"


@pytest.mark.asyncio
async def test_websocket_manager():
    manager = ConnectionManager()
    
    ws1 = AsyncMock()
    ws2 = AsyncMock()
    
    # Test connect
    await manager.connect(ws1, "miss-1")
    await manager.connect(ws2, "miss-1")
    
    assert len(manager.active_connections["miss-1"]) == 2
    
    # Test broadcast
    message = {"status": "IN_TRANSIT", "battery_pct": 95.0}
    await manager.broadcast_to_mission("miss-1", message)
    
    ws1.send_json.assert_called_once_with(message)
    ws2.send_json.assert_called_once_with(message)
    
    # Test disconnect
    manager.disconnect(ws1, "miss-1")
    assert len(manager.active_connections["miss-1"]) == 1
