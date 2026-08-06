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
_COORDINATE = re.compile(rf"(?P<axis>pan|tilt)=(?P<value>{_NUMBER})\Z")
_COUNTER = re.compile(r"(?P<axis>pan|tilt)=(?P<value>\d+)\Z")
_UINT32_MAX = 2**32 - 1
_PWM_POWER_MIN = -255
_PWM_POWER_MAX = 255


class CommandSyntaxError(ValueError):
    """Raised when coordinate arguments are malformed."""


class NotConnectedError(TurntableError):
    """Raised when an operation requires a connected turntable."""


@dataclass(frozen=True)
class Coordinates:
    """Physical pan and tilt parsed from command arguments."""

    pan: float
    tilt: float


@dataclass(frozen=True)
class CounterValues:
    """Raw pan and tilt encoder-counter values."""

    pan: int
    tilt: int


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
    """Parse exactly one ``pan=`` and one ``tilt=`` argument in either order."""

    tokens = arguments.split()
    if len(tokens) != 2:
        raise CommandSyntaxError("expected: pan=<number> tilt=<number>")

    values: dict[str, float] = {}
    for token in tokens:
        match = _COORDINATE.fullmatch(token)
        if match is None:
            raise CommandSyntaxError("expected: pan=<number> tilt=<number>")

        axis = match.group("axis")
        if axis in values:
            raise CommandSyntaxError(f"{axis}= may only be given once")
        values[axis] = float(match.group("value"))

    if values.keys() != {"pan", "tilt"}:
        raise CommandSyntaxError("both pan= and tilt= are required")

    return Coordinates(pan=values["pan"], tilt=values["tilt"])


def parse_counter_values(arguments: str) -> CounterValues:
    """Parse exactly one unsigned ``pan=`` and ``tilt=`` counter value."""

    tokens = arguments.split()
    if len(tokens) != 2:
        raise CommandSyntaxError("expected: pan=<integer> tilt=<integer>")

    values: dict[str, int] = {}
    for token in tokens:
        match = _COUNTER.fullmatch(token)
        if match is None:
            raise CommandSyntaxError("expected: pan=<integer> tilt=<integer>")
        axis = match.group("axis")
        if axis in values:
            raise CommandSyntaxError(f"{axis}= may only be given once")
        value = int(match.group("value"))
        if value > _UINT32_MAX:
            raise CommandSyntaxError(f"{axis} counter must not exceed {_UINT32_MAX}")
        values[axis] = value

    if values.keys() != {"pan", "tilt"}:
        raise CommandSyntaxError("both pan= and tilt= are required")
    return CounterValues(pan=values["pan"], tilt=values["tilt"])


def parse_pwm_power(arguments: str) -> int:
    """Parse one signed integer PWM power in the firmware-supported range."""

    tokens = arguments.split()
    if len(tokens) != 1 or re.fullmatch(r"[+-]?\d+", tokens[0]) is None:
        raise CommandSyntaxError("expected one integer power from -255 through 255")
    power = int(tokens[0])
    if not _PWM_POWER_MIN <= power <= _PWM_POWER_MAX:
        raise CommandSyntaxError("power must be from -255 through 255")
    return power


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
        operation(pan=coordinates.pan, tilt=coordinates.tilt)

    def confirm_position(self) -> PanTilt:
        """Approve the currently reported pan and tilt."""

        with self._lock:
            turntable = self._turntable
        if turntable is None:
            raise NotConnectedError("not connected")

        turntable.confirm_position()
        position = turntable.get_complete_state().corrected_position
        if position is None:
            raise TurntableError("confirmed position is unavailable")
        return position

    def send_raw(self, command: str) -> None:
        """Queue one exact ASCII diagnostic write on the current connection."""

        with self._lock:
            turntable = self._turntable
        if turntable is None:
            raise NotConnectedError("not connected")

        try:
            payload = command.encode("ascii")
        except UnicodeEncodeError as exc:
            raise ValueError("raw command must contain only ASCII characters") from exc
        turntable.send_raw(payload)

    def request_counters(self) -> None:
        """Queue one encoder-counter query on the current connection."""

        with self._lock:
            turntable = self._turntable
        if turntable is None:
            raise NotConnectedError("not connected")
        turntable.request_counters()

    def set_counters(self, counters: CounterValues) -> None:
        """Queue one encoder-counter update on the current connection."""

        with self._lock:
            turntable = self._turntable
        if turntable is None:
            raise NotConnectedError("not connected")
        turntable.set_counters(pan=counters.pan, tilt=counters.tilt)

    def move_to_counters(self, counters: CounterValues) -> None:
        """Queue one move to encoder-counter targets on the current connection."""

        with self._lock:
            turntable = self._turntable
        if turntable is None:
            raise NotConnectedError("not connected")
        turntable.move_to_counters(pan=counters.pan, tilt=counters.tilt)

    def set_pwm(self, axis: Literal["az", "el"], power: int) -> None:
        """Set persistent signed PWM power for one diagnostic axis."""

        if axis not in {"az", "el"}:
            raise ValueError("PWM axis must be 'az' or 'el'")
        with self._lock:
            turntable = self._turntable
        if turntable is None:
            raise NotConnectedError("not connected")
        operation = turntable.set_azimuth_pwm if axis == "az" else turntable.set_elevation_pwm
        operation(power)

    def stop(self) -> None:
        """Immediately stop the connected turntable and cancel queued work."""

        with self._lock:
            turntable = self._turntable
        if turntable is None:
            raise NotConnectedError("not connected")
        turntable.abort()

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
