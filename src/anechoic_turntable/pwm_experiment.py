"""Guarded Textual bench tool for measuring azimuth breakaway PWM."""

from __future__ import annotations

import argparse
import csv
import datetime
import threading
import time
from collections.abc import Callable
from dataclasses import asdict
from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar

from textual import work
from textual.app import App
from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.containers import Vertical
from textual.timer import Timer
from textual.widgets import Button
from textual.widgets import Footer
from textual.widgets import Label
from textual.widgets import RichLog
from textual.widgets import Static

from anechoic_turntable.controller import TurntableActivity
from anechoic_turntable.controller import TurntableError
from anechoic_turntable.controller import TurntableState
from anechoic_turntable.turntable import Turntable

COUNTS_PER_DEGREE = 240.0


def linspace(start: float, stop: float, count: int) -> tuple[float, ...]:
    """Return ``count`` evenly spaced values including both endpoints."""

    if count < 2:
        raise ValueError("linspace count must be at least two")
    step = (stop - start) / (count - 1)
    return tuple(start + step * index for index in range(count))


@dataclass(frozen=True)
class ExperimentConfig:
    """Operator-selected limits for one PWM experiment."""

    output_path: Path
    tilt_min: float = -85.0
    tilt_max: float = 40.0
    tilt_count: int = 10
    pan_min: float = -175.0
    pan_max: float = 175.0
    pan_count: int = 10
    iterations: int = 5
    pwm_min: int = 100
    pwm_max: int = 150
    pwm_step: int = 5
    pulse_seconds: float = 0.75
    settle_seconds: float = 1.0
    approach_degrees: float = 3.0
    movement_counts: int = 5
    maximum_displacement_degrees: float = 0.25
    position_tolerance_degrees: float = 0.11
    positioning_timeout_seconds: float = 300.0

    def validate(self) -> None:
        """Reject unsafe or internally inconsistent experiment settings."""

        if not -90 <= self.tilt_min < self.tilt_max <= 45:
            raise ValueError("tilt range must be increasing and within [-90, 45]")
        if not -180 <= self.pan_min < self.pan_max <= 180:
            raise ValueError("pan range must be increasing and within [-180, 180]")
        if self.tilt_count < 2 or self.pan_count < 2:
            raise ValueError("pan and tilt counts must each be at least two")
        if self.iterations < 1:
            raise ValueError("iterations must be at least one")
        if not 0 <= self.pwm_min <= self.pwm_max <= 255 or self.pwm_step < 1:
            raise ValueError("PWM candidates must be an increasing subset of [0, 255]")
        if self.pulse_seconds <= 0 or self.settle_seconds < 0:
            raise ValueError("pulse time must be positive and settle time must not be negative")
        if self.approach_degrees <= 0:
            raise ValueError("approach distance must be positive")
        if self.pan_min - self.approach_degrees < -180:
            raise ValueError("pan minimum needs enough room for the configured approach distance")
        if self.movement_counts < 1:
            raise ValueError("movement threshold must be at least one encoder count")
        if self.maximum_displacement_degrees <= self.movement_counts / COUNTS_PER_DEGREE:
            raise ValueError("maximum displacement must exceed the movement threshold")
        if self.position_tolerance_degrees <= 0 or self.positioning_timeout_seconds <= 0:
            raise ValueError("position tolerance and positioning timeout must be positive")
        if not self.output_path.parent.is_dir():
            raise ValueError(f"output directory does not exist: {self.output_path.parent}")

    @property
    def pwm_candidates(self) -> tuple[int, ...]:
        """Return ascending candidate magnitudes, including the configured maximum."""

        candidates = list(range(self.pwm_min, self.pwm_max + 1, self.pwm_step))
        if not candidates or candidates[-1] != self.pwm_max:
            candidates.append(self.pwm_max)
        return tuple(candidates)


@dataclass(frozen=True)
class TrialResult:
    """One bounded PWM attempt written as one CSV row."""

    timestamp_utc: str
    requested_pan: float
    requested_tilt: float
    approach_pan: float
    approach_direction: str
    measured_start_pan: float
    measured_start_tilt: float
    direction: int
    direction_name: str
    iteration: int
    pwm_magnitude: int
    signed_pwm: int
    measured_end_pan: float
    measured_end_tilt: float
    delta_pan_degrees: float
    estimated_delta_counts: int
    elapsed_seconds: float
    time_to_movement_seconds: float | None
    started_moving: bool
    stop_reason: str


class ExperimentStopped(Exception):
    """Raised internally when the operator stops an experiment."""


class PwmExperimentRunner:
    """Run the positioning and bounded PWM trials independently of the UI."""

    def __init__(
        self,
        turntable: Turntable,
        config: ExperimentConfig,
        stop_requested: threading.Event,
        *,
        state_callback: Callable[[str, str, int], None] | None = None,
        log_callback: Callable[[str], None] | None = None,
    ) -> None:
        config.validate()
        self._turntable = turntable
        self._config = config
        self._stop_requested = stop_requested
        self._state_callback = state_callback or (lambda status, progress, pwm: None)
        self._log_callback = log_callback or (lambda message: None)

    def run(self) -> None:
        """Run the complete grid and flush every attempt immediately to CSV."""

        tilts = linspace(self._config.tilt_min, self._config.tilt_max, self._config.tilt_count)
        pans = linspace(self._config.pan_min, self._config.pan_max, self._config.pan_count)
        total_threshold_searches = len(tilts) * len(pans) * self._config.iterations * 2
        completed_threshold_searches = 0

        with self._config.output_path.open("x", encoding="utf-8", newline="") as output_file:
            writer = csv.DictWriter(output_file, fieldnames=tuple(TrialResult.__dataclass_fields__))
            writer.writeheader()
            output_file.flush()

            try:
                for tilt_index, tilt in enumerate(tilts):
                    pan_order = pans if tilt_index % 2 == 0 else tuple(reversed(pans))
                    for pan in pan_order:
                        for iteration in range(1, self._config.iterations + 1):
                            directions = (-1, 1) if iteration % 2 else (1, -1)
                            for direction in directions:
                                self._check_stopped()
                                progress = f"search {completed_threshold_searches + 1}/{total_threshold_searches}  pan={pan:.3f}° tilt={tilt:.3f}°  iteration={iteration}  direction={'left' if direction < 0 else 'right'}"
                                threshold = self._find_threshold(
                                    writer,
                                    output_file,
                                    pan=pan,
                                    tilt=tilt,
                                    iteration=iteration,
                                    direction=direction,
                                    progress=progress,
                                )
                                threshold_text = "no start" if threshold is None else f"threshold PWM magnitude {threshold}"
                                self._log_callback(f"{progress}: {threshold_text}")
                                completed_threshold_searches += 1
            finally:
                self._set_state("stopping motors", "experiment cleanup", 0)
                self._turntable.abort()

        self._set_state("complete", f"saved {self._config.output_path}", 0)

    def _find_threshold(
        self,
        writer: csv.DictWriter,
        output_file,
        *,
        pan: float,
        tilt: float,
        iteration: int,
        direction: int,
        progress: str,
    ) -> int | None:
        for pwm in self._config.pwm_candidates:
            self._check_stopped()
            self._set_state("positioning", f"{progress}  candidate={pwm}", 0)
            self._reposition_and_settle(pan=pan, tilt=tilt)
            signed_pwm = direction * pwm
            self._log_callback(f"{progress}: trying PWM {signed_pwm:+d}")
            result = self._try_pwm(
                pan=pan,
                tilt=tilt,
                iteration=iteration,
                direction=direction,
                pwm=pwm,
                progress=progress,
            )
            writer.writerow(asdict(result))
            output_file.flush()
            outcome = "movement detected" if result.started_moving else f"no movement ({result.stop_reason})"
            self._log_callback(f"{progress}: PWM {result.signed_pwm:+d}: {outcome}; delta pan={result.delta_pan_degrees:+.3f}°; elapsed={result.elapsed_seconds:.3f}s")
            if result.started_moving:
                return pwm
        return None

    def _reposition_and_settle(self, *, pan: float, tilt: float) -> None:
        approach_pan = pan - self._config.approach_degrees
        self._move_and_wait(pan=approach_pan, tilt=tilt)
        self._move_and_wait(pan=pan, tilt=tilt)
        if self._stop_requested.wait(self._config.settle_seconds):
            raise ExperimentStopped

    def _move_and_wait(self, *, pan: float, tilt: float) -> None:
        self._check_stopped()
        self._turntable.move_to(pan=pan, tilt=tilt)
        deadline = time.monotonic() + self._config.positioning_timeout_seconds
        while time.monotonic() < deadline:
            self._check_stopped()
            snapshot = self._turntable.get_complete_state()
            if snapshot.state in {
                TurntableState.ERROR,
                TurntableState.NO_COMMUNICATION,
                TurntableState.TIMED_OUT,
                TurntableState.CLOSED,
            }:
                raise TurntableError(f"positioning failed with controller state {snapshot.state.value}")
            position = snapshot.corrected_position
            within_tolerance = position is not None and abs(position.pan - pan) <= self._config.position_tolerance_degrees and abs(position.tilt - tilt) <= self._config.position_tolerance_degrees
            if within_tolerance and snapshot.activity == TurntableActivity.IDLE and snapshot.queued_command_count == 0:
                return
            if self._stop_requested.wait(0.02):
                raise ExperimentStopped
        raise TimeoutError(f"positioning did not complete within {self._config.positioning_timeout_seconds:g} seconds")

    def _try_pwm(
        self,
        *,
        pan: float,
        tilt: float,
        iteration: int,
        direction: int,
        pwm: int,
        progress: str,
    ) -> TrialResult:
        start_position = self._turntable.current_position()
        if start_position is None:
            raise TurntableError("a current position is required before a PWM trial")

        signed_pwm = direction * pwm
        movement_threshold = self._config.movement_counts / COUNTS_PER_DEGREE
        started_at = time.monotonic()
        end_position = start_position
        time_to_movement: float | None = None
        stop_reason = "pulse_timeout"

        self._set_state("applying PWM", f"{progress}  candidate={pwm}", signed_pwm)
        try:
            self._turntable.set_azimuth_pwm(signed_pwm)
            while True:
                self._check_stopped()
                current_position = self._turntable.current_position()
                if current_position is not None:
                    end_position = current_position
                elapsed = time.monotonic() - started_at
                delta = end_position.pan - start_position.pan
                directed_delta = direction * delta
                if directed_delta >= movement_threshold:
                    time_to_movement = elapsed
                    stop_reason = "movement_detected"
                    break
                if abs(delta) >= self._config.maximum_displacement_degrees:
                    stop_reason = "displacement_limit"
                    break
                if elapsed >= self._config.pulse_seconds:
                    break
                if self._stop_requested.wait(0.01):
                    raise ExperimentStopped
        finally:
            self._turntable.abort()
            self._set_state("PWM stopped", progress, 0)

        elapsed = time.monotonic() - started_at
        delta = end_position.pan - start_position.pan
        return TrialResult(
            timestamp_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
            requested_pan=pan,
            requested_tilt=tilt,
            approach_pan=pan - self._config.approach_degrees,
            approach_direction="right_from_lower_pan",
            measured_start_pan=start_position.pan,
            measured_start_tilt=start_position.tilt,
            direction=direction,
            direction_name="left" if direction < 0 else "right",
            iteration=iteration,
            pwm_magnitude=pwm,
            signed_pwm=signed_pwm,
            measured_end_pan=end_position.pan,
            measured_end_tilt=end_position.tilt,
            delta_pan_degrees=delta,
            estimated_delta_counts=round(delta * COUNTS_PER_DEGREE),
            elapsed_seconds=elapsed,
            time_to_movement_seconds=time_to_movement,
            started_moving=time_to_movement is not None,
            stop_reason=stop_reason,
        )

    def _check_stopped(self) -> None:
        if self._stop_requested.is_set():
            raise ExperimentStopped

    def _set_state(self, status: str, progress: str, pwm: int) -> None:
        self._state_callback(status, progress, pwm)


class PwmExperimentApp(App[None]):
    """Minimal operator display for the guarded PWM experiment."""

    TITLE = "Azimuth PWM Start Experiment"
    CSS = """
    Screen {
        layout: vertical;
        padding: 1 2;
    }

    #live {
        height: 10;
        border: round $primary;
        padding: 1 2;
    }

    .value {
        text-style: bold;
        height: 2;
    }

    #warning {
        color: $warning;
        height: 3;
    }

    #log {
        height: 1fr;
        border: round $primary;
    }

    #actions {
        height: 7;
        margin-top: 1;
    }

    #start {
        width: 1fr;
        height: 5;
        margin-right: 1;
    }

    #stop-experiment {
        width: 2fr;
        height: 5;
        text-style: bold;
    }
    """
    BINDINGS: ClassVar[list[tuple[str, str, str]]] = [("ctrl+c", "stop_and_quit", "Stop and exit")]

    def __init__(
        self,
        config: ExperimentConfig,
        *,
        connector: Callable[[], Turntable] = Turntable.find,
        refresh_interval: float = 0.1,
    ) -> None:
        super().__init__()
        config.validate()
        self._config = config
        self._connector = connector
        self._refresh_interval = refresh_interval
        self._turntable: Turntable | None = None
        self._stop_requested = threading.Event()
        self._state_lock = threading.RLock()
        self._status = "connecting"
        self._progress = "waiting for turntable"
        self._current_pwm = 0
        self._experiment_running = False
        self._refresh_timer: Timer | None = None

    def compose(self) -> ComposeResult:
        with Vertical(id="live"):
            yield Label("Current position: pan=—  tilt=—", id="position", classes="value")
            yield Label("Current PWM: 0", id="pwm", classes="value")
            yield Static("Status: connecting", id="status")
            yield Static("Progress: waiting for turntable", id="progress")
            yield Static("Verify the displayed physical coordinates before starting. PWM pulses are bounded, but normal positioning moves the physical table.", id="warning")
        yield RichLog(id="log", wrap=True)
        with Horizontal(id="actions"):
            yield Button("CONFIRM POSITION AND START", id="start", variant="success", disabled=True)
            yield Button("STOP EXPERIMENT", id="stop-experiment", variant="error")
        yield Footer()

    def on_mount(self) -> None:
        """Connect without blocking the UI and begin live refreshes."""

        self._refresh_timer = self.set_interval(self._refresh_interval, self.refresh_display)
        self._connect()

    def on_unmount(self) -> None:
        """Attempt a safe stop before releasing the serial connection."""

        if self._refresh_timer is not None:
            self._refresh_timer.pause()
        self._stop_requested.set()
        turntable = self._turntable
        if turntable is not None:
            try:
                turntable.abort()
            finally:
                turntable.close()

    @work(thread=True, exclusive=True, group="connection")
    def _connect(self) -> None:
        try:
            turntable = self._connector()
        except Exception as exc:  # noqa: BLE001 - display connection failures
            self.call_from_thread(self._connection_failed, exc)
            return
        if self._stop_requested.is_set():
            try:
                turntable.abort()
            finally:
                turntable.close()
            return
        try:
            self.call_from_thread(self._connection_succeeded, turntable)
        except Exception:
            try:
                turntable.abort()
            finally:
                turntable.close()
            raise

    def _connection_succeeded(self, turntable: Turntable) -> None:
        if self._stop_requested.is_set():
            try:
                turntable.abort()
            finally:
                turntable.close()
            return
        self._turntable = turntable
        self._set_ui_state("ready", "verify position, then start", 0)
        self.query_one("#start", Button).disabled = False
        self.query_one("#log", RichLog).write(f"Connected on {turntable.port}. Output: {self._config.output_path}")
        self.query_one("#log", RichLog).write(
            f"Grid: pan {self._config.pan_min:g}..{self._config.pan_max:g} ({self._config.pan_count}), tilt {self._config.tilt_min:g}..{self._config.tilt_max:g} ({self._config.tilt_count}), iterations {self._config.iterations}, PWM {self._config.pwm_min}..{self._config.pwm_max} step {self._config.pwm_step}"
        )

    def _connection_failed(self, error: Exception) -> None:
        self._set_ui_state("connection failed", str(error), 0)
        self.query_one("#log", RichLog).write(f"Connection failed: {error}")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "start":
            self._start_experiment()
        elif event.button.id == "stop-experiment":
            self.stop_experiment()

    def _start_experiment(self) -> None:
        if self._experiment_running or self._turntable is None:
            return
        try:
            self._turntable.confirm_position()
        except (TurntableError, ValueError) as exc:
            self._set_ui_state("cannot start", f"position confirmation failed: {exc}", 0)
            self.refresh_display()
            self.query_one("#log", RichLog).write(f"Cannot start: {exc}")
            return
        self._stop_requested.clear()
        self._experiment_running = True
        self.query_one("#start", Button).disabled = True
        self._set_ui_state("starting", "position confirmed; starting experiment", 0)
        self.refresh_display()
        self.query_one("#log", RichLog).write("Position confirmed. Experiment started.")
        self._run_experiment()

    @work(thread=True, exclusive=True, group="experiment")
    def _run_experiment(self) -> None:
        assert self._turntable is not None
        runner = PwmExperimentRunner(
            self._turntable,
            self._config,
            self._stop_requested,
            state_callback=self._set_ui_state,
            log_callback=self._log_from_worker,
        )
        try:
            runner.run()
        except ExperimentStopped:
            self._set_ui_state("stopped", "stopped by operator", 0)
            self._log_from_worker("Experiment stopped by operator.")
        except Exception as exc:  # noqa: BLE001 - fail safe and keep the error visible
            self._set_ui_state("error", str(exc), 0)
            self._log_from_worker(f"Experiment failed: {type(exc).__name__}: {exc}")
        finally:
            try:
                self._turntable.abort()
            finally:
                self.call_from_thread(self._experiment_finished)

    def _experiment_finished(self) -> None:
        self._experiment_running = False
        if not self._stop_requested.is_set():
            self.query_one("#start", Button).disabled = False

    def stop_experiment(self) -> None:
        """Stop the worker and immediately attempt the firmware stop writes."""

        self._stop_requested.set()
        self._set_ui_state("stopping", "operator requested stop", 0)
        self.query_one("#start", Button).disabled = True
        turntable = self._turntable
        if turntable is not None:
            try:
                turntable.abort()
            except Exception as exc:  # noqa: BLE001 - keep the stop error visible
                self.query_one("#log", RichLog).write(f"STOP WRITE FAILED: {exc}")

    def refresh_display(self) -> None:
        turntable = self._turntable
        position_text = "Current position: pan=—  tilt=—"
        if turntable is not None:
            try:
                position = turntable.current_position()
            except Exception as exc:  # noqa: BLE001 - diagnostics must remain responsive
                position_text = f"Current position: unavailable ({exc})"
            else:
                if position is not None:
                    position_text = f"Current position: pan={position.pan:.3f}°  tilt={position.tilt:.3f}°"
        with self._state_lock:
            status = self._status
            progress = self._progress
            pwm = self._current_pwm
        self.query_one("#position", Label).update(position_text)
        self.query_one("#pwm", Label).update(f"Current PWM: {pwm:+d}" if pwm else "Current PWM: 0")
        self.query_one("#status", Static).update(f"Status: {status}")
        self.query_one("#progress", Static).update(f"Progress: {progress}")

    def _set_ui_state(self, status: str, progress: str, pwm: int) -> None:
        with self._state_lock:
            self._status = status
            self._progress = progress
            self._current_pwm = pwm

    def _log_from_worker(self, message: str) -> None:
        self.call_from_thread(self.query_one("#log", RichLog).write, message)

    def action_stop_and_quit(self) -> None:
        self.stop_experiment()
        self.exit()


def _default_output_path() -> Path:
    timestamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d_%H%M%S")
    output_directory = Path.cwd() / "local"
    output_directory.mkdir(exist_ok=True)
    return output_directory / f"azimuth_pwm_experiment_{timestamp}.csv"


def _parse_arguments() -> ExperimentConfig:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=None, help="CSV output path (default: timestamped file in ./local)")
    parser.add_argument("--tilt-min", type=float, default=-85.0)
    parser.add_argument("--tilt-max", type=float, default=40.0, help="defaults below the +45 degree encoder endpoint")
    parser.add_argument("--tilt-count", type=int, default=10)
    parser.add_argument("--pan-min", type=float, default=-175.0)
    parser.add_argument("--pan-max", type=float, default=175.0)
    parser.add_argument("--pan-count", type=int, default=10)
    parser.add_argument("--iterations", type=int, default=5)
    parser.add_argument("--pwm-min", type=int, default=100)
    parser.add_argument("--pwm-max", type=int, default=150)
    parser.add_argument("--pwm-step", type=int, default=5)
    parser.add_argument("--pulse-seconds", type=float, default=0.75)
    parser.add_argument("--settle-seconds", type=float, default=1.0)
    parser.add_argument("--approach-degrees", type=float, default=3.0)
    parser.add_argument("--movement-counts", type=int, default=5)
    parser.add_argument("--maximum-displacement-degrees", type=float, default=0.25)
    arguments = parser.parse_args()
    return ExperimentConfig(
        output_path=arguments.output or _default_output_path(),
        tilt_min=arguments.tilt_min,
        tilt_max=arguments.tilt_max,
        tilt_count=arguments.tilt_count,
        pan_min=arguments.pan_min,
        pan_max=arguments.pan_max,
        pan_count=arguments.pan_count,
        iterations=arguments.iterations,
        pwm_min=arguments.pwm_min,
        pwm_max=arguments.pwm_max,
        pwm_step=arguments.pwm_step,
        pulse_seconds=arguments.pulse_seconds,
        settle_seconds=arguments.settle_seconds,
        approach_degrees=arguments.approach_degrees,
        movement_counts=arguments.movement_counts,
        maximum_displacement_degrees=arguments.maximum_displacement_degrees,
    )


def main() -> None:
    """Run the guarded azimuth PWM experiment TUI."""

    config = _parse_arguments()
    config.validate()
    PwmExperimentApp(config).run()


if __name__ == "__main__":
    main()
