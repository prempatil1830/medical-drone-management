"""
app/websocket/manager.py — WebSocket Connection Manager.
"""

from __future__ import annotations

from typing import Dict, List
from fastapi import WebSocket
from app.core.logging import get_logger

log = get_logger(__name__)


class ConnectionManager:
    def __init__(self) -> None:
        # Map of mission_id -> list of connected WebSockets
        self.active_connections: Dict[str, List[WebSocket]] = {}

    async def connect(self, websocket: WebSocket, mission_id: str) -> None:
        await websocket.accept()
        if mission_id not in self.active_connections:
            self.active_connections[mission_id] = []
        self.active_connections[mission_id].append(websocket)
        log.info("websocket_connected", mission_id=mission_id, count=len(self.active_connections[mission_id]))

    def disconnect(self, websocket: WebSocket, mission_id: str) -> None:
        if mission_id in self.active_connections:
            if websocket in self.active_connections[mission_id]:
                self.active_connections[mission_id].remove(websocket)
            if not self.active_connections[mission_id]:
                del self.active_connections[mission_id]
        log.info("websocket_disconnected", mission_id=mission_id)

    async def broadcast_to_mission(self, mission_id: str, message: dict) -> None:
        """Send message to all clients connected to a specific mission_id."""
        if mission_id not in self.active_connections:
            return
        
        dead_sockets = []
        for connection in self.active_connections[mission_id]:
            try:
                await connection.send_json(message)
            except Exception as exc:
                log.error("websocket_send_error", mission_id=mission_id, error=str(exc))
                dead_sockets.append(connection)

        # Cleanup failed connections
        for dead_socket in dead_sockets:
            self.disconnect(dead_socket, mission_id)


# Module-level connection manager
manager = ConnectionManager()
