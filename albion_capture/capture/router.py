"""Routes captured packets to the correct city worker based on local port."""
from __future__ import annotations

from typing import Callable

from albion_capture.core.logging import get_logger

log = get_logger("router")

WorkerCallback = Callable[[bytes], None]


class PacketRouter:
    """Dispatches packets to city workers based on local port mapping."""

    def __init__(self, game_port: int = 5056):
        self.game_port = game_port
        self._port_to_callback: dict[int, WorkerCallback] = {}

    def register_worker(self, local_port: int, callback: WorkerCallback) -> None:
        """Register a worker's callback for a specific local port."""
        self._port_to_callback[local_port] = callback
        log.info("worker_registered", local_port=local_port)

    def unregister_worker(self, local_port: int) -> None:
        """Remove a worker's callback."""
        self._port_to_callback.pop(local_port, None)
        log.info("worker_unregistered", local_port=local_port)

    def route_packet(
        self,
        raw_data: bytes,
        src_ip: str,
        src_port: int,
        dst_ip: str,
        dst_port: int,
    ) -> None:
        """Route a packet to the appropriate worker based on port matching.

        Packets FROM the game client have src_port = local_port.
        Packets TO the game client have dst_port = local_port.
        """
        # Check if src_port matches a registered worker (outgoing from client)
        callback = self._port_to_callback.get(src_port)
        if callback:
            callback(raw_data)
            return

        # Check if dst_port matches a registered worker (incoming to client)
        callback = self._port_to_callback.get(dst_port)
        if callback:
            callback(raw_data)
