"""Non-blocking ZMQ publication of controller position updates."""

from __future__ import annotations

import dataclasses
import datetime
import json
import logging
import queue
import threading

import zmq


@dataclasses.dataclass(frozen=True)
class PositionUpdate:
    """One controller position and state observed at the same time."""

    timestamp: datetime.datetime
    state: str
    pan: float
    tilt: float


class PositionPublisher(threading.Thread):
    """Publish the newest queued position update from a background thread."""

    def __init__(
        self,
        *,
        host: str = "localhost",
        port: int = 8_005,
        logger: logging.Logger | None = None,
    ) -> None:
        super().__init__(name="turntable-position-publisher", daemon=True)
        if not isinstance(host, str) or not host:
            raise ValueError("publish_host must be a non-empty string")
        if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65_535:
            raise ValueError("publish_port must be an integer within [1, 65535]")

        self.endpoint = f"tcp://{host}:{port}"
        self._logger = logger or logging.getLogger(__name__)
        self._updates: queue.Queue[PositionUpdate] = queue.Queue(maxsize=1)
        self._stop_event = threading.Event()

    def publish(
        self,
        *,
        timestamp: datetime.datetime,
        state: str,
        pan: float,
        tilt: float,
    ) -> None:
        """Queue an update without waiting for socket I/O."""

        if self._stop_event.is_set():
            return
        update = PositionUpdate(timestamp=timestamp, state=state, pan=pan, tilt=tilt)
        try:
            self._updates.put_nowait(update)
        except queue.Full:
            try:
                self._updates.get_nowait()
            except queue.Empty:
                pass
            try:
                self._updates.put_nowait(update)
            except queue.Full:
                # Another producer replaced the queued value first. Either
                # value is newer than the one that was deliberately dropped.
                pass

    def stop(self) -> None:
        self._stop_event.set()

    def run(self) -> None:
        context: zmq.Context[zmq.Socket[bytes]] | None = None
        socket: zmq.Socket[bytes] | None = None
        try:
            context = zmq.Context()
            socket = context.socket(zmq.PUB)
            socket.setsockopt(zmq.LINGER, 0)
            socket.setsockopt(zmq.SNDHWM, 1)
            socket.bind(self.endpoint)
            while not self._stop_event.is_set() or not self._updates.empty():
                try:
                    update = self._updates.get(timeout=0.1)
                except queue.Empty:
                    continue
                try:
                    socket.send(_format_position_update(update), flags=zmq.NOBLOCK)
                except zmq.Again:
                    self._logger.debug("Dropped a ZMQ position update because the socket was busy")
        except Exception:
            # Telemetry must not be able to terminate or stall device control.
            self._logger.exception("Turntable position publisher failed")
        finally:
            if socket is not None:
                socket.close()
            if context is not None:
                context.term()


def _format_position_update(update: PositionUpdate) -> bytes:
    return json.dumps(
        {
            "timestamp": update.timestamp.isoformat(timespec="microseconds"),
            "state": update.state,
            "pan": update.pan,
            "tilt": update.tilt,
        },
        separators=(",", ":"),
    ).encode("utf-8")
