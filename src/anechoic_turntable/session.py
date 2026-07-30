"""Shared diagnostic-session behavior for interactive turntable front ends."""

from __future__ import annotations

import re
import threading
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

from anechoic_turntable.controller import TurntableCompleteState
from anechoic_turntable.controller import TurntableError
from anechoic_turntable.positions import PanTilt
from anechoic_turntable.turntable import Turntable

_NUMBER = r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)"
_COORDINATE = re.compile(rf"(?P<axis>az|el)=(?P<value>{_NUMBER})\Z")


class CommandSyntaxError(ValueError):
    """Raised when coordinate arguments are malformed."""


class NotConnectedError(TurntableError):
    """Raised when an operation requires a connected turntable."""


@dataclass(frozen=True)
class Coordinates:
    """Physical azimuth and elevation parsed from command arguments."""

    azimuth: float
    elevation: float


@dataclass(frozen=True)
class ConnectionResult:
    """The result of one connection attempt."""

    port: str | None
    error: Exception | None
    cleanup_warnings: tuple[str, ...] = ()

    @property
    def connected(self) -> bool:
        """Whether the connection attempt succeeded."""

        return self.error is None


def parse_coordinates(arguments: str) -> Coordinates:
    """Parse exactly one ``az=`` and one ``el=`` argument in either order."""

    tokens = arguments.split()
    if len(tokens) != 2:
        raise CommandSyntaxError("expected: az=<number> el=<number>")

    values: dict[str, float] = {}
    for token in tokens:
        match = _COORDINATE.fullmatch(token)
        if match is None:
            raise CommandSyntaxError("expected: az=<number> el=<number>")

        axis = match.group("axis")
        if axis in values:
            raise CommandSyntaxError(f"{axis}= may only be given once")
        values[axis] = float(match.group("value"))

    if values.keys() != {"az", "el"}:
        raise CommandSyntaxError("both az= and el= are required")

    return Coordinates(azimuth=values["az"], elevation=values["el"])


class TurntableSession:
    """Own one safely replaceable connection for a diagnostic front end."""

    def __init__(
        self,
        *,
        connector: Callable[[], Turntable] = Turntable.find,
    ) -> None:
        self._connector = connector
        self._lock = threading.RLock()
        self._generation = 0
        self._turntable: Turntable | None = None

    @property
    def connected(self) -> bool:
        """Whether this session currently owns a connection."""

        with self._lock:
            return self._turntable is not None

    @property
    def port(self) -> str | None:
        """Return the current connection's port, if known."""

        with self._lock:
            if self._turntable is None:
                return None
            return self._turntable.port

    def connect(self) -> ConnectionResult:
        """Stop any current connection and attempt to discover a replacement."""

        cleanup_warnings = self.close()
        with self._lock:
            generation = self._generation

        try:
            turntable = self._connector()
        except Exception as exc:  # noqa: BLE001 - diagnostic sessions report failures
            return ConnectionResult(
                port=None,
                error=exc,
                cleanup_warnings=cleanup_warnings,
            )

        with self._lock:
            if generation == self._generation and self._turntable is None:
                self._turntable = turntable
                return ConnectionResult(
                    port=turntable.port,
                    error=None,
                    cleanup_warnings=cleanup_warnings,
                )

        stale_warnings = self._stop_and_close(turntable)
        return ConnectionResult(
            port=None,
            error=TurntableError("connection attempt was superseded"),
            cleanup_warnings=cleanup_warnings + stale_warnings,
        )

    def get_complete_state(self) -> TurntableCompleteState | None:
        """Return the current immutable controller snapshot, if connected."""

        with self._lock:
            turntable = self._turntable
        if turntable is None:
            return None
        return turntable.get_complete_state()

    def queue_position(
        self,
        command: Literal["set", "mov"],
        coordinates: Coordinates,
    ) -> None:
        """Queue one physical position command on the current connection."""

        with self._lock:
            turntable = self._turntable
        if turntable is None:
            raise NotConnectedError("not connected")

        operation = turntable.set_position if command == "set" else turntable.move_to
        operation(pan=coordinates.azimuth, tilt=coordinates.elevation)

    def confirm_position(self) -> PanTilt:
        """Approve the currently reported azimuth and elevation."""

        with self._lock:
            turntable = self._turntable
        if turntable is None:
            raise NotConnectedError("not connected")

        turntable.confirm_position()
        position = turntable.get_complete_state().corrected_position
        if position is None:
            raise TurntableError("confirmed position is unavailable")
        return position

    def close(self) -> tuple[str, ...]:
        """Invalidate discovery, then safely stop and close the connection."""

        with self._lock:
            self._generation += 1
            turntable = self._turntable
            self._turntable = None
        if turntable is None:
            return ()
        return self._stop_and_close(turntable)

    @staticmethod
    def _stop_and_close(turntable: Turntable) -> tuple[str, ...]:
        warnings: list[str] = []
        try:
            turntable.abort()
        except Exception as exc:  # noqa: BLE001 - closing must continue after stop failure
            warnings.append(f"stop failed: {exc}")
        try:
            turntable.close()
        except Exception as exc:  # noqa: BLE001 - diagnostic front ends report cleanup
            warnings.append(f"disconnect failed: {exc}")
        return tuple(warnings)
