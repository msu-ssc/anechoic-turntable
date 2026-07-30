"""A small auto-updating terminal UI for turntable diagnostics."""

from __future__ import annotations

import math
from collections.abc import Callable
from typing import ClassVar
from typing import Literal

from rich.text import Text
from textual import work
from textual.app import App
from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.containers import Vertical
from textual.widgets import Button
from textual.widgets import Footer
from textual.widgets import Input
from textual.widgets import Label
from textual.widgets import RichLog
from textual.widgets import Static

from anechoic_turntable.controller import TurntableCompleteState
from anechoic_turntable.controller import TurntableError
from anechoic_turntable.messages import ReceivedMessage
from anechoic_turntable.positions import PanTilt
from anechoic_turntable.positions import YawPitch
from anechoic_turntable.regimes import TiltRegime
from anechoic_turntable.session import CommandSyntaxError
from anechoic_turntable.session import ConnectionResult
from anechoic_turntable.session import NotConnectedError
from anechoic_turntable.session import TurntableSession
from anechoic_turntable.session import parse_coordinates
from anechoic_turntable.turntable import Turntable

_COMMAND_HELP = "Commands: connect | info | confirm | set az=<number> el=<number> | mov az=<number> el=<number> | raw <ASCII bytes> | stop | help | exit"


class TurntableTui(App[None]):
    """Auto-updating diagnostic interface backed by ``TurntableSession``."""

    TITLE = "Anechoic Turntable"
    SUB_TITLE = "Firmware diagnostic controller"
    CSS = """
    Screen {
        layout: vertical;
    }

    #summary {
        height: 8;
    }

    #diagnostics {
        height: 7;
    }

    .panel {
        border: round $primary;
        padding: 0 1;
        width: 1fr;
    }

    .panel-title {
        text-style: bold;
        color: $accent;
    }

    #controller {
        border: round $primary;
        padding: 0 1;
        width: 2fr;
    }

    #serial-panel {
        border: round $primary;
        height: 8;
        padding: 0 1;
    }

    #serial-output {
        height: 5;
        overflow: hidden;
    }

    #messages {
        border: round $primary;
        height: 1fr;
        padding: 0 1;
    }

    #emergency-stop {
        width: 100%;
        height: 3;
        text-style: bold;
    }

    #command {
        dock: bottom;
    }
    """
    BINDINGS: ClassVar[list[tuple[str, str, str]]] = [
        ("ctrl+c", "quit", "Exit"),
        ("ctrl+l", "focus_command", "Command"),
    ]

    def __init__(
        self,
        *,
        connector: Callable[[], Turntable] = Turntable.find,
        refresh_interval: float = 0.2,
    ) -> None:
        super().__init__()
        if refresh_interval <= 0:
            raise ValueError("refresh_interval must be greater than zero")
        self._session = TurntableSession(connector=connector)
        self._refresh_interval = refresh_interval

    def compose(self) -> ComposeResult:
        with Horizontal(id="summary"):
            with Vertical(classes="panel"):
                yield Label("Connection", classes="panel-title")
                yield Static("status: disconnected", id="connection", markup=False)
                yield Static("port: —", id="port", markup=False)
            with Vertical(classes="panel"):
                yield Label("Physical position", classes="panel-title")
                yield Static("az: —", id="azimuth", markup=False)
                yield Static("el: —", id="elevation", markup=False)
            with Vertical(classes="panel"):
                yield Label("Reported position", classes="panel-title")
                yield Static("az: —", id="reported-azimuth", markup=False)
                yield Static("el: —", id="reported-elevation", markup=False)
            with Vertical(classes="panel"):
                yield Label("Target", classes="panel-title")
                yield Static("az: —", id="target-azimuth", markup=False)
                yield Static("el: —", id="target-elevation", markup=False)
        with Horizontal(id="diagnostics"):
            with Vertical(classes="panel"):
                yield Label("Regime", classes="panel-title")
                yield Static("current: —", id="current-regime", markup=False)
                yield Static("az offset: —", id="offset-azimuth", markup=False)
                yield Static("el offset: —", id="offset-elevation", markup=False)
            yield Static(
                "Controller\nactivity: —\ncommunication: —",
                id="controller",
                markup=False,
            )
        yield Button("EMERGENCY STOP", id="emergency-stop", variant="error")
        with Vertical(id="serial-panel"):
            yield Label("Recent serial output", classes="panel-title")
            yield Static("—", id="serial-output", markup=False)
        yield RichLog(id="messages", markup=False, wrap=True)
        yield Input(placeholder="command> mov az=15 el=0", id="command")
        yield Footer()

    def on_mount(self) -> None:
        """Start state refreshes and focus the command field."""

        self.set_interval(self._refresh_interval, self.refresh_controller_state)
        self.query_one("#command", Input).focus()
        self.refresh_controller_state()
        self._write_message(_COMMAND_HELP)

    def on_unmount(self) -> None:
        """Safely stop the table and invalidate any pending connection attempt."""

        self._session.close()

    def action_focus_command(self) -> None:
        """Move keyboard focus to the command field."""

        self.query_one("#command", Input).focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Execute a command submitted through the command field."""

        command_line = event.value.strip()
        event.input.clear()
        if command_line:
            self.execute_command(command_line)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle the emergency-stop button."""

        if event.button.id == "emergency-stop":
            self._stop_turntable()

    def execute_command(self, command_line: str) -> None:
        """Execute one diagnostic command without blocking on discovery."""

        command, _, arguments = command_line.partition(" ")
        arguments = arguments.strip()

        if command == "connect":
            if self._reject_arguments(command, arguments):
                return
            self._write_message("connecting...")
            self._connect()
        elif command == "info":
            if self._reject_arguments(command, arguments):
                return
            self._write_info()
        elif command == "confirm":
            if self._reject_arguments(command, arguments):
                return
            self._confirm_position()
        elif command in {"set", "mov"}:
            self._queue_position(command, arguments)
        elif command == "raw":
            self._send_raw(arguments)
        elif command == "stop":
            if self._reject_arguments(command, arguments):
                return
            self._stop_turntable()
        elif command == "help":
            if self._reject_arguments(command, arguments):
                return
            self._write_message(_COMMAND_HELP)
        elif command == "exit":
            if self._reject_arguments(command, arguments):
                return
            self.exit()
        else:
            self._write_message(f"error: unknown command: {command}")

    def refresh_controller_state(self) -> None:
        """Render the newest immutable controller snapshot."""

        try:
            snapshot = self._session.get_complete_state()
        except Exception as exc:  # noqa: BLE001 - keep diagnostics visible
            self.query_one("#connection", Static).update("status: unavailable")
            self.query_one("#controller", Static).update(f"Controller\nactivity: —\nerror: {exc}")
            return

        self.query_one("#port", Static).update(f"port: {self._session.port or '—'}")
        if snapshot is None:
            self.query_one("#connection", Static).update("status: disconnected")
            self._update_position("azimuth", "elevation", None)
            self._update_position("reported-azimuth", "reported-elevation", None)
            self._update_position("target-azimuth", "target-elevation", None)
            self._update_regime(None, None)
            self.query_one("#serial-output", Static).update("—")
            self.query_one("#controller", Static).update("Controller\nactivity: —\ncommunication: —")
            return

        self.query_one("#connection", Static).update(f"status: {snapshot.state.value}")
        self._update_position("azimuth", "elevation", snapshot.corrected_position)
        self._update_position(
            "reported-azimuth",
            "reported-elevation",
            snapshot.uncorrected_position,
        )
        self._update_position(
            "target-azimuth",
            "target-elevation",
            snapshot.target_position,
        )
        self._update_regime(snapshot.current_regime, snapshot.regime_offset)
        self._update_serial_output(snapshot.recent_events)

        communication_age = snapshot.seconds_since_last_communication
        communication = "never" if math.isinf(communication_age) else f"{communication_age:.2f}s ago"
        activity = snapshot.activity.value
        if snapshot.activity_phase is not None:
            activity = f"{activity} ({snapshot.activity_phase})"
        controller_lines = [
            "Controller",
            f"activity: {activity}    queue: {snapshot.queued_command_count}",
            f"communication: {communication}",
        ]
        if snapshot.last_error is not None:
            controller_lines.append(f"error: {snapshot.last_error}")
        self.query_one("#controller", Static).update("\n".join(controller_lines))

    @work(thread=True, exclusive=True, group="connection")
    def _connect(self) -> None:
        result = self._session.connect()
        self.call_from_thread(self._connection_finished, result)

    def _connection_finished(self, result: ConnectionResult) -> None:
        self._write_cleanup_warnings(result.cleanup_warnings)
        if result.error is not None:
            self._write_message(f"connection failed: {result.error}")
        else:
            self._write_message(f"connected: {result.port}")
        self.refresh_controller_state()

    def _queue_position(
        self,
        command: Literal["set", "mov"],
        arguments: str,
    ) -> None:
        try:
            coordinates = parse_coordinates(arguments)
            self._session.queue_position(command, coordinates)
        except (CommandSyntaxError, NotConnectedError, TurntableError, ValueError) as exc:
            self._write_message(f"error: {exc}")
            return
        self._write_message(f"{command} queued: az={coordinates.azimuth:.3f} el={coordinates.elevation:.3f}")
        self.refresh_controller_state()

    def _send_raw(self, command: str) -> None:
        if not command:
            self._write_message("error: expected: raw <ASCII bytes>")
            return
        try:
            self._session.send_raw(command)
        except (NotConnectedError, TurntableError, ValueError) as exc:
            self._write_message(f"error: {exc}")
            return
        self._write_message(f"raw queued: {command}")
        self.refresh_controller_state()

    def _stop_turntable(self) -> None:
        try:
            self._session.stop()
        except (NotConnectedError, TurntableError) as exc:
            self._write_message(f"error: {exc}")
            return
        self._write_message("emergency stop sent")
        self.refresh_controller_state()

    def _write_info(self) -> None:
        snapshot = self._session.get_complete_state()
        if snapshot is None:
            self._write_message("state=disconnected")
            return
        self._write_message(self._format_info(snapshot))

    def _confirm_position(self) -> None:
        try:
            position = self._session.confirm_position()
        except (TurntableError, ValueError) as exc:
            self._write_message(f"error: {exc}")
            return
        self._write_message(f"position confirmed: az={position.pan:.3f} el={position.tilt:.3f}")
        self.refresh_controller_state()

    @staticmethod
    def _format_info(snapshot: TurntableCompleteState) -> str:
        parts = [
            f"state={snapshot.state.value}",
            f"activity={snapshot.activity.value}",
        ]
        if snapshot.corrected_position is None:
            parts.extend(("az=?", "el=?"))
        else:
            parts.extend(
                (
                    f"az={snapshot.corrected_position.pan:.3f}",
                    f"el={snapshot.corrected_position.tilt:.3f}",
                )
            )
        if snapshot.target_position is not None:
            parts.extend(
                (
                    f"target_az={snapshot.target_position.pan:.3f}",
                    f"target_el={snapshot.target_position.tilt:.3f}",
                )
            )
        if snapshot.last_error is not None:
            parts.append(f"error={snapshot.last_error}")
        return " ".join(parts)

    def _reject_arguments(self, command: str, arguments: str) -> bool:
        if not arguments:
            return False
        self._write_message(f"error: {command} takes no arguments")
        return True

    def _write_cleanup_warnings(self, warnings: tuple[str, ...]) -> None:
        for warning in warnings:
            self._write_message(f"warning: {warning}")

    def _write_message(self, message: str) -> None:
        self.query_one("#messages", RichLog).write(Text(message))

    def _update_position(
        self,
        azimuth_widget: str,
        elevation_widget: str,
        position: PanTilt | YawPitch | None,
    ) -> None:
        if position is None:
            azimuth = elevation = "—"
        elif isinstance(position, PanTilt):
            azimuth = f"{position.pan:.3f}°"
            elevation = f"{position.tilt:.3f}°"
        else:
            azimuth = f"{position.yaw:.3f}°"
            elevation = f"{position.pitch:.3f}°"
        self.query_one(f"#{azimuth_widget}", Static).update(f"az: {azimuth}")
        self.query_one(f"#{elevation_widget}", Static).update(f"el: {elevation}")

    def _update_regime(self, regime: TiltRegime | None, offset: PanTilt | None) -> None:
        self.query_one("#current-regime", Static).update(f"current: {regime if regime is not None else '—'}")
        if offset is None:
            azimuth = elevation = "—"
        else:
            azimuth = f"{offset.pan:.3f}°"
            elevation = f"{offset.tilt:.3f}°"
        self.query_one("#offset-azimuth", Static).update(f"az offset: {azimuth}")
        self.query_one("#offset-elevation", Static).update(f"el offset: {elevation}")

    def _update_serial_output(self, events: tuple[ReceivedMessage, ...]) -> None:
        lines = [self._format_serial_line(event.message) for event in events[-5:]]
        self.query_one("#serial-output", Static).update("\n".join(lines) if lines else "—")

    @staticmethod
    def _format_serial_line(message: bytes) -> str:
        decoded = message.decode("ascii", errors="backslashreplace").rstrip("\r\n")
        return "".join(character if character.isprintable() or character == "\t" else f"\\x{ord(character):02x}" for character in decoded)


def main() -> None:
    """Run the auto-updating turntable diagnostic TUI."""

    TurntableTui().run()


if __name__ == "__main__":
    main()
