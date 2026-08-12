"""Stateful, non-blocking turntable controller."""

from __future__ import annotations

import dataclasses
import datetime
import enum
import logging
import math
import queue
import threading
import time
from collections import deque
from concurrent.futures import Future
from typing import Literal
from typing import overload

from anechoic_turntable.messages import ReceivedMessage
from anechoic_turntable.messages import ReceivedMessageAcknowledgement
from anechoic_turntable.messages import ReceivedMessageCounter
from anechoic_turntable.messages import ReceivedMessageError
from anechoic_turntable.messages import ReceivedMessagePosition
from anechoic_turntable.messages import ReceivedMessageVersion
from anechoic_turntable.position_publisher import PositionPublisher
from anechoic_turntable.positions import PanTilt
from anechoic_turntable.serial_listener import SerialConnection

ALLOWABLE_DISCREPANCY_DEG = 0.11
ABSOLUTE_PAN_BOUNDS = (-180.0, 180.0)
ABSOLUTE_TILT_BOUNDS = (-90.0, 45.0)
SET_TILT_BOUNDS = (-90.0, 90.0)
UINT32_MAX = 2**32 - 1
MOVE_TIMEOUT_ESTIMATE_MULTIPLIER = 1.5
MOVE_TIMEOUT_MARGIN_SECONDS = 5.0
COUNTER_MOVE_TIMEOUT_SECONDS = 300.0
ACKNOWLEDGEMENT_TIMEOUT_SECONDS = 0.25
EMERGENCY_STOP_REPEAT_COUNT = 5
COUNTS_PER_DEGREE = 240.0
PAN_ZERO_COUNTER = 50_000
TILT_ZERO_COUNTER = 30_000


class TurntableError(Exception):
    """Base exception for the asynchronous turntable controller."""


class TurntableState(str, enum.Enum):
    """Observable controller states."""

    NOT_SET = "not_set"
    STOPPED = "stopped"
    MOVING = "moving"
    NO_COMMUNICATION = "no_communication"
    TIMED_OUT = "timed_out"
    ERROR = "error"
    CLOSED = "closed"


class TurntableActivity(str, enum.Enum):
    """The work represented by a complete-state snapshot."""

    IDLE = "idle"
    QUEUED = "queued"
    SETTING_POSITION = "setting_position"
    MOVING = "moving"


@dataclasses.dataclass(frozen=True)
class PositionSample:
    """One firmware and physical position observed at the same time."""

    timestamp: datetime.datetime
    internal_position: PanTilt
    corrected_position: PanTilt


@dataclasses.dataclass(frozen=True)
class CommandWrite:
    """Exact bytes successfully written to the serial connection."""

    timestamp: datetime.datetime
    command: bytes


@dataclasses.dataclass(frozen=True)
class TurntableCompleteState:
    """An immutable diagnostic snapshot of controller state."""

    captured_at: datetime.datetime
    state: TurntableState
    activity: TurntableActivity
    activity_phase: str | None
    uncorrected_position: PanTilt | None
    corrected_position: PanTilt | None
    most_recent_position_event: ReceivedMessagePosition | None
    most_recent_event: ReceivedMessage | None
    most_recent_acknowledgement: ReceivedMessageAcknowledgement | None
    recent_events: tuple[ReceivedMessage, ...]
    last_communication_at: datetime.datetime | None
    seconds_since_last_communication: float
    communication_timeout: float
    activity_timeout_at: datetime.datetime | None
    target_position: PanTilt | None
    internal_target: PanTilt | None
    queued_command_count: int
    pending_acknowledgement_command: str | None
    has_been_set: bool
    set_requested: bool
    last_error: str | None
    event_count: int
    position_history_count: int
    position_history_generation: int = 0


@dataclasses.dataclass(frozen=True)
class _SetCommand:
    generation: int
    pan: float
    tilt: float
    timeout: float
    completion: _CommandCompletion


@dataclasses.dataclass(frozen=True)
class _MoveCommand:
    generation: int
    pan: float
    tilt: float
    timeout: float | None
    completion: _CommandCompletion


@dataclasses.dataclass(frozen=True)
class _RawCommand:
    generation: int
    payload: bytes


@dataclasses.dataclass(frozen=True)
class _VersionCommand:
    generation: int


@dataclasses.dataclass(frozen=True)
class _CounterRequestCommand:
    generation: int


@dataclasses.dataclass(frozen=True)
class _CounterSetCommand:
    generation: int
    pan: int
    tilt: int


@dataclasses.dataclass(frozen=True)
class _CounterMoveCommand:
    generation: int
    pan: int
    tilt: int
    timeout: float


_Command = _SetCommand | _MoveCommand | _RawCommand | _VersionCommand | _CounterRequestCommand | _CounterSetCommand | _CounterMoveCommand


@dataclasses.dataclass
class _SetOperation:
    pan: float
    tilt: float
    deadline: float
    timeout_at: datetime.datetime
    completion: _CommandCompletion


@dataclasses.dataclass
class _MoveOperation:
    pan: float
    tilt: float
    deadline: float
    timeout_at: datetime.datetime
    internal_target: PanTilt
    phase: Literal["direct", "counter"]
    completion: _CommandCompletion | None = None


_Operation = _SetOperation | _MoveOperation


@dataclasses.dataclass
class _PendingAcknowledgement:
    command: str
    frame: bytes
    attempts: int
    deadline: float
    stop_on_failure: bool
    invalidates_position_on_uncertainty: bool
    completion: _CommandCompletion | None = None


@dataclasses.dataclass
class _CommandCompletion:
    """Track acknowledgement and physical completion for one command."""

    future: Future[None] = dataclasses.field(default_factory=Future)
    acknowledged: bool = False
    position_reached: bool = False


class ControllerThread(threading.Thread):
    """Consume receive events and commands, and serialize all device writes."""

    def __init__(
        self,
        serial_connection: SerialConnection,
        received_messages: queue.Queue[ReceivedMessage],
        *,
        communication_timeout: float = 1.0,
        acknowledgement_timeout: float = ACKNOWLEDGEMENT_TIMEOUT_SECONDS,
        command_repetitions: int = 3,
        event_history_size: int = 1_000,
        poll_interval: float = 0.01,
        position_publisher: PositionPublisher | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        super().__init__(name="turntable-controller", daemon=True)
        if communication_timeout <= 0:
            raise ValueError("communication_timeout must be greater than zero")
        if not math.isfinite(acknowledgement_timeout) or acknowledgement_timeout <= 0:
            raise ValueError("acknowledgement_timeout must be a finite number greater than zero")
        if command_repetitions < 1:
            raise ValueError("command_repetitions must be at least one")
        if event_history_size < 1:
            raise ValueError("event_history_size must be at least one")
        if poll_interval <= 0:
            raise ValueError("poll_interval must be greater than zero")

        self._serial = serial_connection
        self._received_messages = received_messages
        self._communication_timeout = communication_timeout
        self._acknowledgement_timeout = acknowledgement_timeout
        self._command_repetitions = command_repetitions
        self._poll_interval = poll_interval
        self._position_publisher = position_publisher
        self._logger = logger or logging.getLogger(__name__)

        self._command_queue: queue.Queue[_Command] = queue.Queue()
        self._queued_commands: deque[_Command] = deque()
        self._operation: _Operation | None = None
        self._pending_acknowledgement: _PendingAcknowledgement | None = None
        self._stop_event = threading.Event()
        self._lock = threading.RLock()
        self._command_generation = 0
        self._unresolved_completions: set[Future[None]] = set()

        self._state = TurntableState.NOT_SET
        self._has_been_set = False
        self._set_requested = False
        self._internal_position: PanTilt | None = None
        self._corrected_position: PanTilt | None = None
        self._most_recent_communication = float("-inf")
        self._last_communication_at: datetime.datetime | None = None
        self._started_at = time.monotonic()
        self._events: deque[ReceivedMessage] = deque(maxlen=event_history_size)
        self._position_history: deque[PositionSample] = deque(maxlen=event_history_size)
        self._command_history: deque[CommandWrite] = deque(maxlen=event_history_size)
        self._position_history_generation = 0
        self._most_recent_by_kind: dict[str, ReceivedMessage] = {}
        self._last_error: Exception | None = None

    def submit_set(self, *, pan: float, tilt: float, timeout: float) -> Future[None]:
        _validate_set_position(pan=pan, tilt=tilt)
        _validate_timeout(timeout)
        with self._lock:
            self._ensure_open()
            completion = self._new_completion()
            # A SET changes the coordinate frame, so samples captured before it
            # must never be plotted alongside samples captured after it.
            self._position_history.clear()
            self._position_history_generation += 1
            self._set_requested = True
            self._command_queue.put(
                _SetCommand(
                    generation=self._command_generation,
                    pan=pan,
                    tilt=tilt,
                    timeout=timeout,
                    completion=completion,
                )
            )
            return completion.future

    def confirm_position(self) -> None:
        """Trust the firmware's current coordinates without sending a SET."""

        with self._lock:
            self._ensure_open()
            if self._operation is not None or self._has_pending_commands():
                raise TurntableError("The current position cannot be confirmed while commands are active or queued")
            if self._state == TurntableState.NO_COMMUNICATION:
                raise TurntableError("A live position report is required before the current position can be confirmed")
            if self._internal_position is None:
                raise TurntableError("A reported position is required before the current position can be confirmed")

            self._has_been_set = True
            self._set_requested = False
            self._corrected_position = PanTilt(
                pan=self._internal_position.pan,
                tilt=self._internal_position.tilt,
            )
            self._state = TurntableState.STOPPED

    def submit_move(self, *, pan: float, tilt: float, timeout: float | None) -> Future[None]:
        _validate_position(pan=pan, tilt=tilt)
        if timeout is not None:
            _validate_timeout(timeout)
        with self._lock:
            self._ensure_open()
            if not (self._has_been_set or self._set_requested):
                raise TurntableError("The turntable position must be set before it can move")
            completion = self._new_completion()
            self._command_queue.put(
                _MoveCommand(
                    generation=self._command_generation,
                    pan=pan,
                    tilt=tilt,
                    timeout=timeout,
                    completion=completion,
                )
            )
            return completion.future

    def wait_for_completion(self, completion: Future[None]) -> None:
        """Wait until one submitted command completes or fails."""

        completion.result()

    def estimate_time(self, *, pan: float, tilt: float) -> float:
        """Estimate travel time to a physical target, without timeout margin."""

        _validate_position(pan=pan, tilt=tilt)
        with self._lock:
            self._ensure_open()
            if self._corrected_position is None:
                raise TurntableError("A current position report is required to estimate movement time")
            return estimate_movement_time(
                current=self._corrected_position,
                target=PanTilt(pan=pan, tilt=tilt),
            )

    def submit_raw(self, payload: bytes) -> None:
        """Queue exact diagnostic bytes for one write without protocol validation."""

        with self._lock:
            self._ensure_open()
            self._command_queue.put(
                _RawCommand(
                    generation=self._command_generation,
                    payload=bytes(payload),
                )
            )

    def submit_version_request(self) -> None:
        """Queue one firmware version request."""

        with self._lock:
            self._ensure_open()
            self._command_queue.put(_VersionCommand(generation=self._command_generation))

    def submit_counter_request(self) -> None:
        """Queue one encoder-counter query."""

        with self._lock:
            self._ensure_open()
            self._command_queue.put(_CounterRequestCommand(generation=self._command_generation))

    def submit_counter_set(self, *, pan: int, tilt: int) -> None:
        """Queue one encoder-counter update."""

        _validate_counter("pan", pan)
        _validate_counter("tilt", tilt)
        with self._lock:
            self._ensure_open()
            self._command_queue.put(
                _CounterSetCommand(
                    generation=self._command_generation,
                    pan=pan,
                    tilt=tilt,
                )
            )

    def submit_counter_move(self, *, pan: int, tilt: int, timeout: float) -> None:
        """Queue one move to raw encoder-counter targets."""

        _validate_counter("pan", pan)
        _validate_counter("tilt", tilt)
        _validate_timeout(timeout)
        with self._lock:
            self._ensure_open()
            self._command_queue.put(
                _CounterMoveCommand(
                    generation=self._command_generation,
                    pan=pan,
                    tilt=tilt,
                    timeout=timeout,
                )
            )

    def submit_abort(self, *, repeat_count: int = EMERGENCY_STOP_REPEAT_COUNT) -> None:
        """Immediately invalidate queued work and send repeated stop bytes."""

        _validate_repeat_count(repeat_count)
        with self._lock:
            self._ensure_open()
            self._operation = None
            self._invalidate_pending_commands(TurntableError("Turntable command was aborted"))
            self._set_requested = False
            if self._state != TurntableState.NO_COMMUNICATION:
                self._state = TurntableState.STOPPED if self._has_been_set else TurntableState.NOT_SET
            self._write_stop(repeat_count=repeat_count)

    def stop(self) -> None:
        self._stop_event.set()

    def current_state(self) -> TurntableState:
        with self._lock:
            return self._state

    def current_position(self) -> PanTilt | None:
        with self._lock:
            return self._corrected_position

    def get_complete_state(self) -> TurntableCompleteState:
        """Return an immutable, internally consistent diagnostic snapshot."""

        with self._lock:
            operation = self._operation
            position_event = self._most_recent_by_kind.get("position")
            if not isinstance(position_event, ReceivedMessagePosition):
                position_event = None
            acknowledgement = self._most_recent_by_kind.get("acknowledgement")
            if not isinstance(acknowledgement, ReceivedMessageAcknowledgement):
                acknowledgement = None

            timeout_at: datetime.datetime | None = None
            target_position: PanTilt | None = None
            internal_target: PanTilt | None = None
            activity_phase: str | None = None
            if isinstance(operation, _SetOperation):
                activity = TurntableActivity.SETTING_POSITION
                activity_phase = "set"
                timeout_at = operation.timeout_at
                target_position = PanTilt(operation.pan, operation.tilt)
                internal_target = PanTilt(operation.pan, operation.tilt)
            elif isinstance(operation, _MoveOperation):
                activity = TurntableActivity.MOVING
                activity_phase = operation.phase
                timeout_at = operation.timeout_at
                target_position = PanTilt(operation.pan, operation.tilt)
                internal_target = operation.internal_target
            elif self._queued_commands or not self._command_queue.empty():
                activity = TurntableActivity.QUEUED
            else:
                activity = TurntableActivity.IDLE

            error = None
            if self._last_error is not None:
                error = f"{type(self._last_error).__name__}: {self._last_error}"

            return TurntableCompleteState(
                captured_at=_utc_now(),
                state=self._state,
                activity=activity,
                activity_phase=activity_phase,
                uncorrected_position=self._internal_position,
                corrected_position=self._corrected_position,
                most_recent_position_event=position_event,
                most_recent_event=self._events[-1] if self._events else None,
                most_recent_acknowledgement=acknowledgement,
                recent_events=tuple(self._events)[-5:],
                last_communication_at=self._last_communication_at,
                seconds_since_last_communication=time.monotonic() - self._most_recent_communication,
                communication_timeout=self._communication_timeout,
                activity_timeout_at=timeout_at,
                target_position=target_position,
                internal_target=internal_target,
                queued_command_count=len(self._queued_commands) + self._command_queue.qsize(),
                pending_acknowledgement_command=(None if self._pending_acknowledgement is None else self._pending_acknowledgement.command),
                has_been_set=self._has_been_set,
                set_requested=self._set_requested,
                last_error=error,
                event_count=len(self._events),
                position_history_count=len(self._position_history),
                position_history_generation=self._position_history_generation,
            )

    @overload
    def most_recent_event(self, *, kind: Literal["position"]) -> ReceivedMessagePosition | None: ...

    @overload
    def most_recent_event(self, *, kind: Literal["version"]) -> ReceivedMessageVersion | None: ...

    @overload
    def most_recent_event(self, *, kind: Literal["counter"]) -> ReceivedMessageCounter | None: ...

    @overload
    def most_recent_event(self, *, kind: Literal["acknowledgement"]) -> ReceivedMessageAcknowledgement | None: ...

    @overload
    def most_recent_event(self, *, kind: Literal["error"]) -> ReceivedMessageError | None: ...

    @overload
    def most_recent_event(self, *, kind: Literal["other"]) -> ReceivedMessage | None: ...

    @overload
    def most_recent_event(self, *, kind: None = None) -> ReceivedMessage | None: ...

    def most_recent_event(self, *, kind: str | None = None) -> ReceivedMessage | None:
        with self._lock:
            if kind is None:
                return self._events[-1] if self._events else None
            if kind not in {"position", "version", "counter", "acknowledgement", "error", "other"}:
                raise ValueError(f"Unknown event kind: {kind!r}")
            return self._most_recent_by_kind.get(kind)

    def events(self) -> tuple[ReceivedMessage, ...]:
        with self._lock:
            return tuple(self._events)

    def position_history(self) -> tuple[PositionSample, ...]:
        """Return raw and corrected position samples in receive order."""

        with self._lock:
            return tuple(self._position_history)

    def command_history(self) -> tuple[CommandWrite, ...]:
        """Return successful serial writes in the order they occurred."""

        with self._lock:
            return tuple(self._command_history)

    def last_error(self) -> Exception | None:
        with self._lock:
            return self._last_error

    def time_since_last_communication(self) -> float:
        with self._lock:
            return time.monotonic() - self._most_recent_communication

    def run(self) -> None:
        while not self._stop_event.is_set():
            try:
                self._drain_commands()
                if self._stop_event.is_set():
                    break
                self._drain_messages()
                self._check_timeouts()
                self._start_next_command()
            except Exception as exc:
                self._logger.exception("Unexpected turntable controller error")
                with self._lock:
                    self._last_error = exc
                    self._operation = None
                    self._invalidate_pending_commands(exc)
                    self._set_requested = False
                    self._state = TurntableState.ERROR
            self._stop_event.wait(self._poll_interval)

        with self._lock:
            self._invalidate_pending_commands(TurntableError("Turntable controller closed before command completion"))
            self._state = TurntableState.CLOSED

    def _drain_commands(self) -> None:
        while True:
            with self._lock:
                try:
                    command = self._command_queue.get_nowait()
                except queue.Empty:
                    return
                if command.generation == self._command_generation:
                    self._queued_commands.append(command)

    def _drain_messages(self) -> None:
        while True:
            try:
                event = self._received_messages.get_nowait()
            except queue.Empty:
                return
            self._handle_received_message(event)

    def _handle_received_message(self, event: ReceivedMessage) -> None:
        self._record_event(event)
        if isinstance(event, ReceivedMessageAcknowledgement):
            self._handle_acknowledgement(event)
            return
        if isinstance(event, ReceivedMessageError):
            self._handle_firmware_error(event)
            return
        if not isinstance(event, ReceivedMessagePosition):
            return
        if event.pan is None or event.tilt is None:
            return

        internal_position = PanTilt(pan=event.pan, tilt=event.tilt)
        with self._lock:
            self._most_recent_communication = time.monotonic()
            self._last_communication_at = event.timestamp
            self._internal_position = internal_position
            self._corrected_position = PanTilt(
                pan=internal_position.pan,
                tilt=internal_position.tilt,
            )

            if isinstance(self._operation, _SetOperation):
                operation = self._operation
                if _position_matches(
                    internal_position,
                    PanTilt(operation.pan, operation.tilt),
                ):
                    operation.completion.position_reached = True
                    self._complete_if_finished(operation.completion)
                    self._has_been_set = True
                    self._set_requested = any(isinstance(command, _SetCommand) for command in self._queued_commands)
                    self._operation = None
                    self._state = TurntableState.MOVING if self._has_pending_commands() else TurntableState.STOPPED
            elif not isinstance(self._operation, _MoveOperation):
                if self._state != TurntableState.ERROR:
                    self._state = TurntableState.STOPPED if self._has_been_set else TurntableState.NOT_SET
            else:
                operation = self._operation
                if _position_matches(
                    internal_position,
                    operation.internal_target,
                ):
                    if operation.completion is not None:
                        operation.completion.position_reached = True
                        self._complete_if_finished(operation.completion)
                    self._operation = None
                    if self._has_pending_commands():
                        self._state = TurntableState.MOVING
                    else:
                        self._state = TurntableState.STOPPED if self._has_been_set else TurntableState.NOT_SET

            assert self._corrected_position is not None
            self._position_history.append(
                PositionSample(
                    timestamp=event.timestamp,
                    internal_position=internal_position,
                    corrected_position=self._corrected_position,
                )
            )
            if self._position_publisher is not None:
                self._position_publisher.publish(
                    timestamp=event.timestamp,
                    state=self._state.value,
                    pan=self._corrected_position.pan,
                    tilt=self._corrected_position.tilt,
                )

    def _handle_acknowledgement(self, event: ReceivedMessageAcknowledgement) -> None:
        with self._lock:
            pending = self._pending_acknowledgement
            if pending is None or event.command != pending.command:
                return
            self._pending_acknowledgement = None
            if event.status == "NAK":
                reason = event.reason or "unspecified reason"
                self._fail_acknowledged_command(
                    TurntableError(f"Firmware rejected {event.command}: {reason}"),
                    pending=pending,
                    uncertain=False,
                )
            elif pending.completion is not None:
                pending.completion.acknowledged = True
                self._complete_if_finished(pending.completion)

    def _handle_firmware_error(self, event: ReceivedMessageError) -> None:
        with self._lock:
            self._write_stop()
            self._last_error = TurntableError(f"Firmware reported {event.reason}")
            self._operation = None
            self._invalidate_pending_commands(self._last_error)
            self._set_requested = False
            self._has_been_set = False
            self._internal_position = None
            self._corrected_position = None
            self._state = TurntableState.ERROR

    def _record_event(self, event: ReceivedMessage) -> None:
        with self._lock:
            self._events.append(event)
            self._most_recent_by_kind[event.kind] = event

    def _check_timeouts(self) -> None:
        now = time.monotonic()
        with self._lock:
            operation = self._operation
            reference = self._most_recent_communication if math.isfinite(self._most_recent_communication) else self._started_at
            if now - reference > self._communication_timeout:
                if self._state != TurntableState.NO_COMMUNICATION:
                    if isinstance(operation, _MoveOperation):
                        self._write_stop()
                    self._state = TurntableState.NO_COMMUNICATION
                    self._has_been_set = False
                    self._set_requested = False
                    self._operation = None
                    self._invalidate_pending_commands(TurntableError("Communication with the turntable was lost"))
                return

            if operation is not None and now > operation.deadline:
                self._write_stop()
                self._last_error = TimeoutError("Turntable command timed out")
                self._operation = None
                self._invalidate_pending_commands(self._last_error)
                self._set_requested = False
                self._state = TurntableState.TIMED_OUT
                self._pending_acknowledgement = None
                return

            pending = self._pending_acknowledgement
            if pending is not None and now > pending.deadline:
                if pending.attempts < self._command_repetitions:
                    pending.attempts += 1
                    pending.deadline = now + self._acknowledgement_timeout
                    self._write_command(pending.frame)
                else:
                    self._pending_acknowledgement = None
                    self._fail_acknowledged_command(
                        TimeoutError(f"No acknowledgement received for {pending.command}"),
                        pending=pending,
                        uncertain=True,
                    )

    def _start_next_command(self) -> None:
        with self._lock:
            if self._operation is not None or self._pending_acknowledgement is not None or not self._queued_commands or self._state == TurntableState.NO_COMMUNICATION:
                return
            command = self._queued_commands.popleft()
            if command.generation != self._command_generation:
                return
            if isinstance(command, _SetCommand):
                self._begin_set(command)
            elif isinstance(command, _MoveCommand):
                self._begin_move(command)
            elif isinstance(command, _RawCommand):
                self._send_raw(command)
            elif isinstance(command, _VersionCommand):
                self._send_version_request(command)
            elif isinstance(command, _CounterRequestCommand):
                self._send_counter_request(command)
            elif isinstance(command, _CounterSetCommand):
                self._send_counter_set(command)
            else:
                self._begin_counter_move(command)

    def _send_version_request(self, command: _VersionCommand) -> None:
        if command.generation == self._command_generation:
            self._write_acknowledged_command(b"CMD:VERSION;", command="VERSION")

    def _send_counter_request(self, command: _CounterRequestCommand) -> None:
        if command.generation == self._command_generation:
            self._write_acknowledged_command(b"CMD:CNT;", command="CNT")

    def _send_counter_set(self, command: _CounterSetCommand) -> None:
        with self._lock:
            if command.generation != self._command_generation:
                return
            # Direct counter changes redefine the firmware's coordinates.
            # Discard the physical frame before attempting the write because a
            # write error cannot prove that the firmware left the values alone.
            self._position_history.clear()
            self._position_history_generation += 1
            self._has_been_set = False
            self._set_requested = False
            self._corrected_position = None
            if self._state != TurntableState.NO_COMMUNICATION:
                self._state = TurntableState.NOT_SET
            self._write_acknowledged_command(
                f"CMD:SET_CNT:PAN={command.pan},TILT={command.tilt};".encode("ascii"),
                command="SET_CNT",
                invalidates_position_on_uncertainty=True,
            )

    def _send_raw(self, command: _RawCommand) -> None:
        with self._lock:
            if command.generation != self._command_generation:
                return
            # Arbitrary bytes may SET the firmware coordinate frame or start
            # motion that this controller cannot track. Fail closed by
            # discarding all trusted physical-coordinate state.
            self._position_history.clear()
            self._position_history_generation += 1
            self._has_been_set = False
            self._set_requested = False
            self._corrected_position = None
            if self._state != TurntableState.NO_COMMUNICATION:
                self._state = TurntableState.NOT_SET
            self._write_command(command.payload)

    def _begin_set(self, command: _SetCommand) -> None:
        with self._lock:
            if command.generation != self._command_generation:
                return
            self._position_history.clear()
            deadline, timeout_at = _make_deadline(command.timeout)
            self._operation = _SetOperation(
                pan=command.pan,
                tilt=command.tilt,
                deadline=deadline,
                timeout_at=timeout_at,
                completion=command.completion,
            )
            self._state = TurntableState.NOT_SET
            self._write_acknowledged_command(
                _format_set_command(pan=command.pan, tilt=command.tilt),
                command="SET",
                invalidates_position_on_uncertainty=True,
                completion=command.completion,
            )

    def _begin_move(self, command: _MoveCommand) -> None:
        with self._lock:
            if command.generation != self._command_generation:
                return
            if not self._has_been_set:
                error = TurntableError("The turntable position is not set")
                self._last_error = error
                self._state = TurntableState.ERROR
                self._set_requested = False
                self._fail_completion(command.completion, error)
                return
            if self._corrected_position is None:
                error = TurntableError("The current position is unavailable")
                self._last_error = error
                self._state = TurntableState.ERROR
                self._fail_completion(command.completion, error)
                return
            timeout = command.timeout
            if timeout is None:
                estimated_time = estimate_movement_time(
                    current=self._corrected_position,
                    target=PanTilt(pan=command.pan, tilt=command.tilt),
                )
                timeout = estimated_time * MOVE_TIMEOUT_ESTIMATE_MULTIPLIER + MOVE_TIMEOUT_MARGIN_SECONDS
            deadline, timeout_at = _make_deadline(timeout)
            operation = _MoveOperation(
                pan=command.pan,
                tilt=command.tilt,
                deadline=deadline,
                timeout_at=timeout_at,
                internal_target=PanTilt(pan=command.pan, tilt=command.tilt),
                phase="direct",
                completion=command.completion,
            )
            self._operation = operation
            self._state = TurntableState.MOVING
            self._write_acknowledged_command(
                _format_move_command(pan=command.pan, tilt=command.tilt),
                command="MOV",
                stop_on_failure=True,
                completion=command.completion,
            )

    def _begin_counter_move(self, command: _CounterMoveCommand) -> None:
        with self._lock:
            if command.generation != self._command_generation:
                return
            target = _counter_target_to_pan_tilt(pan=command.pan, tilt=command.tilt)
            deadline, timeout_at = _make_deadline(command.timeout)
            self._operation = _MoveOperation(
                pan=target.pan,
                tilt=target.tilt,
                deadline=deadline,
                timeout_at=timeout_at,
                internal_target=target,
                phase="counter",
            )
            self._state = TurntableState.MOVING
            self._write_acknowledged_command(
                f"CMD:MOV_CNT:PAN={command.pan},TILT={command.tilt};".encode("ascii"),
                command="MOV_CNT",
                stop_on_failure=True,
            )

    def _write_acknowledged_command(
        self,
        frame: bytes,
        *,
        command: str,
        stop_on_failure: bool = False,
        invalidates_position_on_uncertainty: bool = False,
        completion: _CommandCompletion | None = None,
    ) -> None:
        if self._pending_acknowledgement is not None:
            raise RuntimeError("Cannot write a second command while an acknowledgement is pending")
        pending = _PendingAcknowledgement(
            command=command,
            frame=frame,
            attempts=1,
            deadline=time.monotonic() + self._acknowledgement_timeout,
            stop_on_failure=stop_on_failure,
            invalidates_position_on_uncertainty=invalidates_position_on_uncertainty,
            completion=completion,
        )
        self._pending_acknowledgement = pending
        self._write_command(frame)

    def _fail_acknowledged_command(
        self,
        error: Exception,
        *,
        pending: _PendingAcknowledgement,
        uncertain: bool,
    ) -> None:
        if pending.stop_on_failure:
            self._write_stop()
        if uncertain and pending.invalidates_position_on_uncertainty:
            self._has_been_set = False
            self._corrected_position = None
        self._last_error = error
        self._operation = None
        self._set_requested = False
        self._invalidate_pending_commands(error)
        self._state = TurntableState.ERROR

    def _write_command(self, command: bytes) -> None:
        with self._lock:
            try:
                timestamp = _utc_now()
                written = self._serial.write(command)
                byte_count = len(command) if written is None else max(0, min(written, len(command)))
                if byte_count:
                    self._command_history.append(
                        CommandWrite(
                            timestamp=timestamp,
                            command=command[:byte_count],
                        )
                    )
            except Exception as exc:
                self._logger.exception("Failed to write command to the turntable")
                self._last_error = exc
                self._operation = None
                self._pending_acknowledgement = None
                self._invalidate_pending_commands(exc)
                self._set_requested = False
                self._state = TurntableState.ERROR

    def _write_stop(self, *, repeat_count: int = EMERGENCY_STOP_REPEAT_COUNT) -> None:
        for _ in range(repeat_count):
            self._write_command(b"%")

    def _new_completion(self) -> _CommandCompletion:
        completion = _CommandCompletion()
        self._unresolved_completions.add(completion.future)
        return completion

    def _complete_if_finished(self, completion: _CommandCompletion) -> None:
        if not completion.acknowledged or not completion.position_reached:
            return
        if not completion.future.done():
            completion.future.set_result(None)
        self._unresolved_completions.discard(completion.future)

    def _fail_completion(self, completion: _CommandCompletion, error: Exception) -> None:
        if not completion.future.done():
            completion.future.set_exception(error)
        self._unresolved_completions.discard(completion.future)

    def _invalidate_pending_commands(self, error: Exception) -> None:
        for completion in self._unresolved_completions:
            if not completion.done():
                completion.set_exception(error)
        self._unresolved_completions.clear()
        self._pending_acknowledgement = None
        self._command_generation += 1
        self._queued_commands.clear()
        self._command_queue = queue.Queue()

    def _has_pending_commands(self) -> bool:
        return bool(self._queued_commands) or not self._command_queue.empty()

    def _ensure_open(self) -> None:
        if self._state == TurntableState.CLOSED or self._stop_event.is_set():
            raise TurntableError("The turntable controller is closed")


def _utc_now() -> datetime.datetime:
    return datetime.datetime.now(tz=datetime.timezone.utc)


def _make_deadline(timeout: float) -> tuple[float, datetime.datetime]:
    return time.monotonic() + timeout, _utc_now() + datetime.timedelta(seconds=timeout)


def _validate_timeout(timeout: float) -> None:
    if not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("timeout must be a finite number greater than zero")


def _validate_repeat_count(repeat_count: int) -> None:
    if isinstance(repeat_count, bool) or not isinstance(repeat_count, int) or repeat_count < 1:
        raise ValueError("repeat_count must be an integer greater than or equal to one")


def _validate_counter(name: str, value: int) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= UINT32_MAX:
        raise ValueError(f"{name} counter must be an integer within [0, {UINT32_MAX}]")


def _validate_position(*, pan: float, tilt: float) -> None:
    if not math.isfinite(pan) or not ABSOLUTE_PAN_BOUNDS[0] <= pan <= ABSOLUTE_PAN_BOUNDS[1]:
        raise ValueError(f"pan must be within {ABSOLUTE_PAN_BOUNDS}")
    if not math.isfinite(tilt) or not ABSOLUTE_TILT_BOUNDS[0] <= tilt <= ABSOLUTE_TILT_BOUNDS[1]:
        raise ValueError(f"tilt must be within {ABSOLUTE_TILT_BOUNDS}")


def _counter_target_to_pan_tilt(*, pan: int, tilt: int) -> PanTilt:
    """Convert raw counter targets exactly as the firmware does."""

    return PanTilt(
        pan=(pan - PAN_ZERO_COUNTER) / COUNTS_PER_DEGREE,
        tilt=(tilt - TILT_ZERO_COUNTER) / COUNTS_PER_DEGREE,
    )


def _validate_set_position(*, pan: float, tilt: float) -> None:
    if not math.isfinite(pan) or not ABSOLUTE_PAN_BOUNDS[0] <= pan <= ABSOLUTE_PAN_BOUNDS[1]:
        raise ValueError(f"pan must be within {ABSOLUTE_PAN_BOUNDS}")
    if not math.isfinite(tilt) or not SET_TILT_BOUNDS[0] <= tilt <= SET_TILT_BOUNDS[1]:
        raise ValueError(f"tilt must be within {SET_TILT_BOUNDS}")


@overload
def estimate_movement_time(*, current: PanTilt, target: PanTilt) -> float: ...


@overload
def estimate_movement_time(
    *,
    current_pan: float,
    current_tilt: float,
    target_pan: float,
    target_tilt: float,
) -> float: ...


def estimate_movement_time(
    *,
    current: PanTilt | None = None,
    target: PanTilt | None = None,
    current_pan: float | None = None,
    current_tilt: float | None = None,
    target_pan: float | None = None,
    target_tilt: float | None = None,
) -> float:
    """Estimate concurrent two-axis travel time between physical positions.

    The coefficients in this acceleration-aware model were derived from the
    hardware measurements documented in
    https://github.com/msu-ssc/lems-anechoic/issues/35.
    See [Travel-time estimates](docs/travel-time-estimates.md) for the model
    and its limitations.

    Provide either ``current`` and ``target`` as :class:`PanTilt` values, or
    provide all four scalar coordinate arguments. This calculation does not
    command movement and does not include the controller's timeout margin.
    """

    if current is not None and target is not None and current_pan is None and current_tilt is None and target_pan is None and target_tilt is None:
        current_position = current
        target_position = target
    elif current is None and target is None and current_pan is not None and current_tilt is not None and target_pan is not None and target_tilt is not None:
        current_position = PanTilt(pan=current_pan, tilt=current_tilt)
        target_position = PanTilt(pan=target_pan, tilt=target_tilt)
    else:
        raise TypeError("Provide either current and target, or current_pan, current_tilt, target_pan, and target_tilt")

    pan_time = _estimate_axis_time(abs(target_position.pan - current_position.pan), axis="pan")
    tilt_time = _estimate_axis_time(abs(target_position.tilt - current_position.tilt), axis="tilt")
    return max(pan_time, tilt_time)


def _estimate_axis_time(angle: float, *, axis: Literal["pan", "tilt"]) -> float:
    """Estimate one-axis travel time, including acceleration and deceleration."""

    if axis == "pan":
        if angle < 2:
            return 0.5713 + 1.0117 * math.sqrt(angle)
        return 0.3940 * angle + 1.2141
    if axis == "tilt":
        if angle < 2:
            return -0.1949 + 2.8896 * math.sqrt(angle)
        return 0.9038 * angle + 2.0841
    raise ValueError(f"Invalid axis: {axis!r}. Must be 'pan' or 'tilt'.")


def _position_matches(actual: PanTilt, expected: PanTilt) -> bool:
    return abs(actual.pan - expected.pan) <= ALLOWABLE_DISCREPANCY_DEG and abs(actual.tilt - expected.tilt) <= ALLOWABLE_DISCREPANCY_DEG


def _format_set_command(*, pan: float, tilt: float) -> bytes:
    """Format the firmware's fixed SET pan/tilt value slots."""

    return f"CMD:SET:{_wire_number(pan)},{_wire_number(tilt)};".encode("ascii")


def _format_move_command(*, pan: float, tilt: float) -> bytes:
    """Format the firmware's fixed MOV pan/tilt value slots."""

    return f"CMD:MOV:{_wire_number(pan)},{_wire_number(tilt)};".encode("ascii")


def _wire_number(value: float) -> str:
    return f"{0.0 if value == 0 else value:.3f}"
