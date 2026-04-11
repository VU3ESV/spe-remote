"""Multi-client WebSocket handler for SPE amplifier remote control."""

import logging
import time
from typing import Set

import tornado.websocket

from spe.protocol import AmplifierState

logger = logging.getLogger(__name__)


class AmplifierWebSocket(tornado.websocket.WebSocketHandler):
    """WebSocket handler supporting multiple simultaneous clients."""

    clients: Set["AmplifierWebSocket"] = set()
    _serial_handler = None
    _last_json = ""
    _last_broadcast_time = 0.0
    _heartbeat_interval = 15.0

    @classmethod
    def configure(cls, serial_handler, heartbeat: float = 15.0) -> None:
        cls._serial_handler = serial_handler
        cls._heartbeat_interval = heartbeat

    def check_origin(self, origin) -> bool:
        return True

    def open(self) -> None:
        AmplifierWebSocket.clients.add(self)
        logger.info(
            f"Client connected ({self.request.remote_ip}), "
            f"{len(self.clients)} total"
        )
        # Send current state immediately to new client
        if self._serial_handler:
            state_json = self._serial_handler.state.to_json()
            try:
                self.write_message(state_json)
            except tornado.websocket.WebSocketClosedError:
                pass

    def on_message(self, message: str) -> None:
        logger.info(f"Command from {self.request.remote_ip}: {message}")
        if self._serial_handler:
            self._serial_handler.send_command(message)

    def on_close(self) -> None:
        AmplifierWebSocket.clients.discard(self)
        logger.info(
            f"Client disconnected ({self.request.remote_ip}), "
            f"{len(self.clients)} remaining"
        )

    @classmethod
    def broadcast_state(cls, state: AmplifierState) -> None:
        """Broadcast amplifier state to all connected clients."""
        state_json = state.to_json()
        now = time.time()

        # Only broadcast if state changed or heartbeat interval elapsed
        if (
            state_json == cls._last_json
            and now - cls._last_broadcast_time < cls._heartbeat_interval
        ):
            return

        cls._last_json = state_json
        cls._last_broadcast_time = now

        dead_clients = set()
        for client in cls.clients:
            try:
                client.write_message(state_json)
            except tornado.websocket.WebSocketClosedError:
                dead_clients.add(client)

        cls.clients -= dead_clients
