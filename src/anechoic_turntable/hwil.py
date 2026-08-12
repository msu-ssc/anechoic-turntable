"""Operator-guided basic functionality HWIL testing."""

from __future__ import annotations

import argparse
import datetime
import json
import math
import sys
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from rich.console import Console

from anechoic_turntable._version import CONTROLLER_VERSION
from anechoic_turntable._version import PROTOCOL_VERSION
from anechoic_turntable._version import REFERENCE_FIRMWARE_VERSION
from anechoic_turntable.controller import ABSOLUTE_PAN_BOUNDS
from anechoic_turntable.controller import MOVE_TIMEOUT_ESTIMATE_MULTIPLIER
from anechoic_turntable.controller import MOVE_TIMEOUT_MARGIN_SECONDS
from anechoic_turntable.controller import SET_TILT_BOUNDS
from anechoic_turntable.controller import TurntableState
from anechoic_turntable.controller import estimate_movement_time
from anechoic_turntable.messages import ReceivedMessage
from anechoic_turntable.messages import ReceivedMessageAcknowledgement
from anechoic_turntable.messages import ReceivedMessageCounter
from anechoic_turntable.messages import ReceivedMessageError
from anechoic_turntable.messages import ReceivedMessagePosition
from anechoic_turntable.messages import ReceivedMessageVersion
from anechoic_turntable.positions import PanTilt
from anechoic_turntable.turntable import Turntable

console = Console(highlight=False)
POSITION_TRACE_INTERVAL_SECONDS = 1.0 / 3.0


class HardwareTestError(RuntimeError):
    """Raised when a basic functionality HWIL requirement fails."""


class OperatorCancelled(HardwareTestError):
    """Raised when the operator declines a required action."""


class HardwareTestRunner:
    """Run a guarded basic functionality HWIL test against one turntable."""

    def __init__(self, turntable: Turntable) -> None:
        self.turntable = turntable
        self._last_position_trace_at: datetime.datetime | None = None
        self.report: dict[str, Any] = {
            "status": "not_started",
            "started_at": datetime.datetime.now().astimezone().isoformat(),
            "port": turntable.port,
            "controller_version": CONTROLLER_VERSION,
            "protocol_version": PROTOCOL_VERSION,
            "reference_firmware_version": REFERENCE_FIRMWARE_VERSION,
            "firmware_version": None,
            "preflight_confirmed": False,
            "centering_attempts": [],
            "steps": [],
            "trace": [],
            "warnings": [],
        }

    def run(self) -> dict[str, Any]:
        """Run the complete basic functionality test and return its report."""

        self.report["status"] = "running"
        try:
            self._show_banner()
            self._verify_connection()
            self._run_preflight()
            self._center_interactively()
            self._run_basic_movements()
        except OperatorCancelled:
            self.report["status"] = "cancelled"
            raise
        except BaseException:
            self.report["status"] = "failed"
            raise
        finally:
            stop_error = self._attempt_final_stop()
            self.report["finished_at"] = datetime.datetime.now().astimezone().isoformat()
            if stop_error is not None and sys.exc_info()[0] is None:
                self.report["status"] = "failed"
                raise HardwareTestError(f"final stop failed: {stop_error}") from stop_error
        self.report["status"] = "passed"
        console.print("\nPASS: Basic functionality HWIL test completed.", style="bold green")
        return self.report

    def _show_banner(self) -> None:
        console.print("\nBasic functionality HWIL test", style="bold")
        console.print(f"Port: {self.turntable.port or 'auto-discovered'}")
        console.print(f"Controller: {CONTROLLER_VERSION}")
        console.print(f"Protocol snapshot: {PROTOCOL_VERSION}")
        console.print(f"Reference firmware: {REFERENCE_FIRMWARE_VERSION}")
        self._attention("\nPress Ctrl-C at any prompt or during movement to issue an immediate stop.")

    def _verify_connection(self) -> None:
        console.print("\nConnection check", style="bold")
        deadline = time.monotonic() + 3.0
        while self.turntable.current_position() is None:
            error = self.turntable.last_error()
            if error is not None:
                raise HardwareTestError(f"controller reported an error: {error}")
            if time.monotonic() >= deadline:
                raise HardwareTestError("no valid position report received within 3 seconds")
            time.sleep(0.05)

        initial_position = self.turntable.current_position()
        assert initial_position is not None
        console.print(f"Position telemetry received: {self._format_position(initial_position)}")

        events = self.turntable.events()
        event_cursor = events[-1] if events else None
        command_index = len(self.turntable.command_history())
        self.turntable.request_version()
        version_deadline = time.monotonic() + 2.0
        firmware_version: str | None = None
        version_acknowledged = False
        while time.monotonic() < version_deadline:
            command_index, event_cursor, new_events = self._drain_trace(command_index, event_cursor)
            version_events = [event for event in new_events if isinstance(event, ReceivedMessageVersion)]
            if version_events:
                firmware_version = version_events[-1].version
            version_acknowledged = version_acknowledged or any(isinstance(event, ReceivedMessageAcknowledgement) and event.status == "ACK" and event.command == "VERSION" for event in new_events)
            if firmware_version is not None and version_acknowledged:
                break
            error = self.turntable.last_error()
            if error is not None:
                raise HardwareTestError(f"firmware version request failed: {error}")
            time.sleep(0.05)
        command_index, event_cursor, new_events = self._drain_trace(command_index, event_cursor)
        del command_index, event_cursor, new_events
        if firmware_version is None or not version_acknowledged:
            raise HardwareTestError("firmware did not acknowledge and answer the version request within 2 seconds")
        self.report["firmware_version"] = firmware_version
        console.print(f"Firmware: {firmware_version}")

    def _run_preflight(self) -> None:
        console.print("\nPre-flight", style="bold")
        self._attention("Confirm that:")
        self._attention("  - the complete pan and tilt travel area is clear;")
        self._attention("  - no person is within the equipment's motion envelope;")
        self._attention("  - the emergency power disconnect is immediately accessible;")
        self._attention("  - the observed position can be estimated in physical pan/tilt degrees.")
        self._require_yes("Are all pre-flight conditions satisfied? [y/N] ")
        self.report["preflight_confirmed"] = True

    def _center_interactively(self) -> None:
        console.print("\nInteractive centering", style="bold")
        self._attention("Each attempt declares your estimated current position with SET, then moves to pan=0°, tilt=0°.")
        self._attention("Your estimate directly determines the direction and distance of travel. Check signs and values carefully.")
        console.print("Displayed positions and movement amounts are rounded to the nearest degree.")

        attempt_number = 0
        while True:
            attempt_number += 1
            console.print(f"\nCentering attempt {attempt_number}", style="bold")
            pan = self._read_coordinate("Approximate current pan in degrees: ", axis="pan")
            tilt = self._read_coordinate("Approximate current tilt in degrees: ", axis="tilt")
            estimated_seconds = estimate_movement_time(
                current_pan=pan,
                current_tilt=tilt,
                target_pan=0.0,
                target_tilt=0.0,
            )
            move_timeout = self._move_timeout(estimated_seconds)
            target = PanTilt(pan=0.0, tilt=0.0)
            console.print(f"Current position will be declared as {self._format_position(PanTilt(pan=pan, tilt=tilt))}.")
            self._show_move_summary(PanTilt(pan=pan, tilt=tilt), target, estimated_seconds, move_timeout)
            self._require_yes("Are the estimate, signs, travel path, and target correct? [y/N] ")

            attempt: dict[str, Any] = {
                "attempt": attempt_number,
                "declared_position": {"pan": pan, "tilt": tilt},
                "estimated_seconds": estimated_seconds,
                "move_timeout_seconds": move_timeout,
                "started_at": datetime.datetime.now().astimezone().isoformat(),
            }
            self.report["centering_attempts"].append(attempt)
            try:
                self._run_traced_operation(
                    lambda pan=pan, tilt=tilt: self.turntable.set_position_blocking(pan=pan, tilt=tilt),
                )
                self._run_traced_operation(
                    lambda move_timeout=move_timeout: self.turntable.move_to_blocking(
                        pan=0.0,
                        tilt=0.0,
                        move_timeout=move_timeout,
                    ),
                )
                final_position = self.turntable.current_position()
                if self.turntable.current_state() is not TurntableState.STOPPED:
                    raise HardwareTestError("controller did not stop after the centering move")
                if final_position is None:
                    raise HardwareTestError("final centering position is unavailable")
            except BaseException as exc:
                attempt["machine_result"] = "failed"
                attempt["error"] = str(exc)
                raise
            attempt["machine_result"] = "passed"
            attempt["final_position"] = {"pan": final_position.pan, "tilt": final_position.tilt}
            attempt["finished_at"] = datetime.datetime.now().astimezone().isoformat()

            physically_centered = self._ask_yes_no(self._confirmation_prompt(PanTilt(pan=0.0, tilt=0.0)))
            attempt["operator_confirmed_centered"] = physically_centered
            if physically_centered:
                console.print("Center established.", style="green")
                return
            self._attention("The table remains stopped. Enter the observed residual offset for another centering attempt.")

    def _run_basic_movements(self) -> None:
        targets = (
            PanTilt(pan=5.0, tilt=0.0),
            PanTilt(pan=0.0, tilt=0.0),
            PanTilt(pan=0.0, tilt=5.0),
            PanTilt(pan=0.0, tilt=0.0),
        )
        console.print("\nBasic movement checks", style="bold")
        for step_number, target in enumerate(targets, start=1):
            current = self.turntable.current_position()
            if current is None:
                raise HardwareTestError(f"current position is unavailable before step {step_number}")
            expected_seconds = self.turntable.estimate_time(pan=target.pan, tilt=target.tilt)
            move_timeout = self._move_timeout(expected_seconds)
            console.print(f"\nStep {step_number}/{len(targets)}", style="bold")
            self._show_move_summary(current, target, expected_seconds, move_timeout)
            self._require_yes("Ready to move? [y/N] ")

            step: dict[str, Any] = {
                "step": step_number,
                "target": {"pan": target.pan, "tilt": target.tilt},
                "estimated_seconds": expected_seconds,
                "move_timeout_seconds": move_timeout,
                "started_at": datetime.datetime.now().astimezone().isoformat(),
            }
            self.report["steps"].append(step)
            try:
                self._run_traced_operation(
                    lambda target=target, move_timeout=move_timeout: self.turntable.move_to_blocking(
                        pan=target.pan,
                        tilt=target.tilt,
                        move_timeout=move_timeout,
                    ),
                )
                final_position = self.turntable.current_position()
                if self.turntable.current_state() is not TurntableState.STOPPED:
                    raise HardwareTestError(f"controller did not stop after step {step_number}")
                if final_position is None:
                    raise HardwareTestError(f"final position is unavailable after step {step_number}")
            except BaseException as exc:
                step["machine_result"] = "failed"
                step["error"] = str(exc)
                raise

            step["machine_result"] = "passed"
            step["final_position"] = {"pan": final_position.pan, "tilt": final_position.tilt}
            step["finished_at"] = datetime.datetime.now().astimezone().isoformat()
            operator_confirmed = self._ask_yes_no(self._confirmation_prompt(target))
            step["operator_confirmed"] = operator_confirmed
            if not operator_confirmed:
                raise HardwareTestError(f"operator rejected the physical result of step {step_number}")

    def _show_move_summary(
        self,
        current: PanTilt,
        target: PanTilt,
        estimated_seconds: float,
        move_timeout: float,
    ) -> None:
        now = datetime.datetime.now().astimezone()
        expected_at = now + datetime.timedelta(seconds=estimated_seconds)
        timeout_at = now + datetime.timedelta(seconds=move_timeout)
        self._attention(self._movement_description(current, target))
        self._attention(f"Target: {self._format_position(target)}")
        console.print(f"Expected travel time: {self._nearest_int(estimated_seconds)} s (estimate only)")
        console.print(f"Expected completion by: {expected_at:%H:%M:%S}")
        console.print(f"Hard controller timeout at: {timeout_at:%H:%M:%S}")

    def _run_traced_operation(self, operation: Callable[[], None]) -> None:
        command_index = len(self.turntable.command_history())
        events = self.turntable.events()
        event_cursor = events[-1] if events else None
        outcome: dict[str, BaseException | None] = {"error": None}

        def run_operation() -> None:
            try:
                operation()
            except BaseException as exc:  # noqa: BLE001 - propagate worker failures on the operator thread
                outcome["error"] = exc

        worker = threading.Thread(target=run_operation, name="turntable-hwil-operation", daemon=True)
        worker.start()
        try:
            while worker.is_alive():
                command_index, event_cursor, _ = self._drain_trace(command_index, event_cursor)
                worker.join(timeout=0.05)
            self._drain_trace(command_index, event_cursor, force_final_position=True)
        except BaseException:
            try:
                self.turntable.abort()
            except Exception as exc:  # noqa: BLE001 - preserve the cancellation or operation failure
                self.report["warnings"].append(f"stop during interrupted operation failed: {exc}")
                console.print(f"WARNING: stop during interrupted operation failed: {exc}", style="bold red")
            worker.join(timeout=2.0)
            raise

        if outcome["error"] is not None:
            raise outcome["error"]

    def _drain_trace(
        self,
        command_index: int,
        event_cursor: ReceivedMessage | None,
        *,
        force_final_position: bool = False,
    ) -> tuple[int, ReceivedMessage | None, tuple[ReceivedMessage, ...]]:
        commands = self.turntable.command_history()
        events = self.turntable.events()
        new_events = self._events_after(events, event_cursor)
        final_position_event = next((event for event in reversed(new_events) if isinstance(event, ReceivedMessagePosition)), None)
        for command in commands[command_index:]:
            self._write_trace(f"{self._timestamp(command.timestamp)}  TX    {command.command!r}")
        for event in new_events:
            if isinstance(event, ReceivedMessagePosition):
                elapsed = None if self._last_position_trace_at is None else (event.timestamp - self._last_position_trace_at).total_seconds()
                if (event is not final_position_event or not force_final_position) and elapsed is not None and elapsed < POSITION_TRACE_INTERVAL_SECONDS:
                    continue
                self._last_position_trace_at = event.timestamp
            self._write_trace(self._format_event(event))
        if force_final_position and final_position_event is None:
            latest_position = next((event for event in reversed(events) if isinstance(event, ReceivedMessagePosition)), None)
            if latest_position is not None and latest_position.timestamp != self._last_position_trace_at:
                self._last_position_trace_at = latest_position.timestamp
                self._write_trace(self._format_event(latest_position))
        return len(commands), events[-1] if events else event_cursor, new_events

    @staticmethod
    def _events_after(
        events: tuple[ReceivedMessage, ...],
        cursor: ReceivedMessage | None,
    ) -> tuple[ReceivedMessage, ...]:
        if cursor is None:
            return events
        for index in range(len(events) - 1, -1, -1):
            if events[index] is cursor:
                return events[index + 1 :]
        return events

    def _write_trace(self, line: str) -> None:
        self.report["trace"].append(line)
        console.print(line, style="dim", markup=False)

    def _format_event(self, event: ReceivedMessage) -> str:
        prefix = self._timestamp(event.timestamp)
        if isinstance(event, ReceivedMessageAcknowledgement):
            suffix = event.command if event.reason is None else f"{event.command}: {event.reason}"
            return f"{prefix}  {event.status:<4}  {suffix}"
        if isinstance(event, ReceivedMessagePosition):
            if event.pan is None or event.tilt is None:
                return f"{prefix}  POS   invalid position payload"
            return f"{prefix}  POS   pan={event.pan:.3f}°, tilt={event.tilt:.3f}°"
        if isinstance(event, ReceivedMessageVersion):
            return f"{prefix}  VER   {event.version}"
        if isinstance(event, ReceivedMessageCounter):
            return f"{prefix}  CNT   pan={event.pan}, tilt={event.tilt}"
        if isinstance(event, ReceivedMessageError):
            return f"{prefix}  ERR   {event.reason}"
        return f"{prefix}  RX    {event.message!r}"

    def _read_coordinate(self, prompt: str, *, axis: str) -> float:
        lower, upper = ABSOLUTE_PAN_BOUNDS if axis == "pan" else SET_TILT_BOUNDS
        while True:
            try:
                response = self._input(prompt).strip()
            except EOFError as exc:
                raise OperatorCancelled("operator input ended") from exc
            if response.lower() in {"q", "quit"}:
                raise OperatorCancelled("operator cancelled centering")
            try:
                value = float(response)
            except ValueError:
                self._attention(f"Enter a numeric {axis} value from {lower:.0f} through {upper:.0f}, or q to stop.")
                continue
            if not math.isfinite(value) or not lower <= value <= upper:
                self._attention(f"{axis} must be finite and from {lower:.0f} through {upper:.0f} degrees.")
                continue
            return value

    def _require_yes(self, prompt: str) -> None:
        if not self._ask_yes_no(prompt):
            raise OperatorCancelled("operator declined a required action")

    def _ask_yes_no(self, prompt: str) -> bool:
        while True:
            try:
                response = self._input(prompt).strip().lower()
            except EOFError as exc:
                raise OperatorCancelled("operator input ended") from exc
            if response in {"y", "yes"}:
                return True
            if response in {"", "n", "no"}:
                return False
            self._attention("Enter y or n.")

    def _attempt_final_stop(self) -> Exception | None:
        try:
            self.turntable.abort()
            self.report["final_stop_attempted"] = True
            return None
        except Exception as exc:  # noqa: BLE001 - retain the primary test outcome
            self.report["final_stop_attempted"] = True
            self.report["final_stop_error"] = str(exc)
            self.report["warnings"].append(f"final stop failed: {exc}")
            console.print(f"WARNING: final stop failed: {exc}", style="bold red")
            return exc

    @staticmethod
    def _input(prompt: str) -> str:
        console.print(prompt, style="yellow", end="", markup=False)
        return input()

    @staticmethod
    def _attention(message: str) -> None:
        console.print(message, style="yellow", markup=False)

    @classmethod
    def _movement_description(cls, current: PanTilt, target: PanTilt) -> str:
        movements: list[str] = []
        pan_change = cls._nearest_int(target.pan - current.pan)
        tilt_change = cls._nearest_int(target.tilt - current.tilt)
        if pan_change:
            movements.append(f"{'LEFT' if pan_change > 0 else 'RIGHT'} {abs(pan_change)}°")
        if tilt_change:
            movements.append(f"{'UP' if tilt_change > 0 else 'DOWN'} {abs(tilt_change)}°")
        if not movements:
            return "The turntable will remain at its current position."
        return f"The turntable will move {' and '.join(movements)}."

    @classmethod
    def _confirmation_prompt(cls, target: PanTilt) -> str:
        return f"Did the motion complete, and is the current position {cls._format_position(target)}? [y/N] "

    @staticmethod
    def _nearest_int(value: float) -> int:
        if value >= 0:
            return math.floor(value + 0.5)
        return math.ceil(value - 0.5)

    @staticmethod
    def _move_timeout(estimated_seconds: float) -> float:
        return estimated_seconds * MOVE_TIMEOUT_ESTIMATE_MULTIPLIER + MOVE_TIMEOUT_MARGIN_SECONDS

    @staticmethod
    def _format_position(position: PanTilt) -> str:
        return f"pan={HardwareTestRunner._nearest_int(position.pan)}°, tilt={HardwareTestRunner._nearest_int(position.tilt)}°"

    @staticmethod
    def _timestamp(timestamp: datetime.datetime) -> str:
        local_timestamp = timestamp.astimezone()
        return local_timestamp.strftime("%H:%M:%S.%f")[:-3]


def _default_report_path() -> Path:
    timestamp = datetime.datetime.now().astimezone()
    return Path(f"turntable-hwil-{timestamp:%Y%m%d-%H%M%S}.json")


def _write_report(path: Path, report: dict[str, Any]) -> None:
    path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    """Run the operator-guided basic functionality HWIL test."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", help="serial port to use; omit to auto-discover")
    parser.add_argument("--report", type=Path, help="JSON result path")
    args = parser.parse_args(argv)
    report_path = args.report or _default_report_path()

    turntable: Turntable | None = None
    runner: HardwareTestRunner | None = None
    exit_code = 1
    try:
        turntable = Turntable(port=args.port, publish=False) if args.port else Turntable.find(publish=False)
        runner = HardwareTestRunner(turntable)
        runner.run()
        exit_code = 0
    except OperatorCancelled as exc:
        print(f"\nCANCELLED: {exc}", file=sys.stderr)
        exit_code = 2
    except KeyboardInterrupt:
        print("\nCANCELLED: immediate stop requested", file=sys.stderr)
        exit_code = 130
    except Exception as exc:  # noqa: BLE001 - CLI boundary reports hardware failures
        print(f"\nFAIL: {exc}", file=sys.stderr)
        exit_code = 1
    finally:
        if runner is not None:
            try:
                _write_report(report_path, runner.report)
                print(f"Report: {report_path}")
            except Exception as exc:  # noqa: BLE001 - do not hide the hardware result
                print(f"WARNING: could not write report: {exc}", file=sys.stderr)
                exit_code = 1
        if turntable is not None:
            turntable.close()
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
