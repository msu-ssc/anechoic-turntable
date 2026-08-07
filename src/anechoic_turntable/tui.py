"""Auto-updating terminal UI for turntable diagnostics."""

from __future__ import annotations

import math
from collections.abc import Callable
from typing import ClassVar
from typing import Literal

from rich.text import Text
from textual import on
from textual import work
from textual.app import App
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal
from textual.containers import ScrollableContainer
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Button
from textual.widgets import Checkbox
from textual.widgets import Footer
from textual.widgets import Input
from textual.widgets import Label
from textual.widgets import RichLog
from textual.widgets import Static

from anechoic_turntable.controller import MOVE_TIMEOUT_ESTIMATE_MULTIPLIER
from anechoic_turntable.controller import MOVE_TIMEOUT_MARGIN_SECONDS
from anechoic_turntable.controller import CommandWrite
from anechoic_turntable.controller import TurntableCompleteState
from anechoic_turntable.controller import TurntableError
from anechoic_turntable.messages import ReceivedMessage
from anechoic_turntable.messages import ReceivedMessageAcknowledgement
from anechoic_turntable.messages import ReceivedMessageCounter
from anechoic_turntable.messages import ReceivedMessageError
from anechoic_turntable.messages import ReceivedMessagePosition
from anechoic_turntable.messages import ReceivedMessageVersion
from anechoic_turntable.positions import PanTilt
from anechoic_turntable.positions import YawPitch
from anechoic_turntable.session import CommandSyntaxError
from anechoic_turntable.session import ConnectionResult
from anechoic_turntable.session import Coordinates
from anechoic_turntable.session import NotConnectedError
from anechoic_turntable.session import TurntableSession
from anechoic_turntable.session import parse_coordinates
from anechoic_turntable.session import parse_counter_values
from anechoic_turntable.turntable import Turntable

_COMMAND_HELP = "Commands: connect | disconnect | version | info | confirm | set pan=<number> tilt=<number> | mov pan=<number> tilt=<number> | set_cnt pan=<integer> tilt=<integer> | mov_cnt pan=<integer> tilt=<integer> | counter? | raw <ASCII bytes> | stop | help | exit"
_MESSAGE_KINDS = ("position", "version", "counter", "acknowledgement", "error", "other")


class CommandInput(Input):
    """Single-line command input with shell-style history navigation."""

    BINDINGS: ClassVar[list[Binding]] = [
        *Input.BINDINGS,
        Binding("up", "history_previous", show=False),
        Binding("down", "history_next", show=False),
    ]

    def __init__(self, **kwargs: object) -> None:
        super().__init__(**kwargs)
        self._command_history: list[str] = []
        self._history_index: int | None = None
        self._draft = ""

    def remember(self, command_line: str) -> None:
        """Remember a submitted command and reset history navigation."""

        self._command_history.append(command_line)
        self._history_index = None
        self._draft = ""

    def action_history_previous(self) -> None:
        """Replace the input with the previous submitted command."""

        if not self._command_history:
            return
        if self._history_index is None:
            self._draft = self.value
            self._history_index = len(self._command_history) - 1
        elif self._history_index > 0:
            self._history_index -= 1
        self._show_history_value(self._command_history[self._history_index])

    def action_history_next(self) -> None:
        """Replace the input with the next command or the saved draft."""

        if self._history_index is None:
            return
        if self._history_index < len(self._command_history) - 1:
            self._history_index += 1
            value = self._command_history[self._history_index]
        else:
            self._history_index = None
            value = self._draft
        self._show_history_value(value)

    def _show_history_value(self, value: str) -> None:
        self.value = value
        self.cursor_position = len(value)


class _TurntableTuiSession(TurntableSession):
    """TUI-only access to diagnostics already exposed by ``Turntable``."""

    def queue_position_with_timeout(
        self,
        command: Literal["set", "mov"],
        coordinates: Coordinates,
        timeout: float,
    ) -> None:
        """Queue a position operation using the timeout entered in the TUI."""

        with self._lock:
            turntable = self._turntable
        if turntable is None:
            raise NotConnectedError("not connected")
        if command == "set":
            turntable.set_position(pan=coordinates.pan, tilt=coordinates.tilt, timeout=timeout)
        else:
            turntable.move_to(pan=coordinates.pan, tilt=coordinates.tilt, move_timeout=timeout)

    def events(self) -> tuple[ReceivedMessage, ...]:
        """Return receive history through the connected public API."""

        with self._lock:
            turntable = self._turntable
        return () if turntable is None else turntable.events()

    def command_history(self) -> tuple[CommandWrite, ...]:
        """Return write history through the connected public API."""

        with self._lock:
            turntable = self._turntable
        return () if turntable is None else turntable.command_history()

    def estimate_move_timeout(self, coordinates: Coordinates) -> float:
        """Estimate the default timeout for one physical move."""

        with self._lock:
            turntable = self._turntable
        if turntable is None:
            raise NotConnectedError("not connected")
        travel_time = turntable.estimate_time(
            pan=coordinates.pan,
            tilt=coordinates.tilt,
        )
        return travel_time * MOVE_TIMEOUT_ESTIMATE_MULTIPLIER + MOVE_TIMEOUT_MARGIN_SECONDS


class ParsedFilterModal(ModalScreen[set[str] | None]):
    """Select which parsed receive-event types are visible."""

    CSS = """
    ParsedFilterModal {
        align: center middle;
    }

    #filter-dialog {
        width: 42;
        height: auto;
        border: round $primary;
        background: $surface;
        padding: 1 2;
    }

    #filter-actions {
        height: 3;
        margin-top: 1;
    }

    #filter-actions Button {
        width: 1fr;
    }
    """

    def __init__(self, selected_kinds: set[str]) -> None:
        super().__init__()
        self._selected_kinds = selected_kinds

    def compose(self) -> ComposeResult:
        with Vertical(id="filter-dialog"):
            yield Label("Parsed message types", classes="panel-title")
            for kind in _MESSAGE_KINDS:
                yield Checkbox(kind.title(), value=kind in self._selected_kinds, id=f"filter-{kind}")
            with Horizontal(id="filter-actions"):
                yield Button("Apply", id="apply-filter", variant="primary")
                yield Button("Cancel", id="cancel-filter")

    @on(Button.Pressed, "#apply-filter")
    def apply_filter(self) -> None:
        """Return the checked message kinds."""

        selected = {kind for kind in _MESSAGE_KINDS if self.query_one(f"#filter-{kind}", Checkbox).value}
        self.dismiss(selected)

    @on(Button.Pressed, "#cancel-filter")
    def cancel_filter(self) -> None:
        """Close without changing the filter."""

        self.dismiss(None)


class TurntableTui(App[None]):
    """Auto-updating diagnostic interface backed by ``TurntableSession``."""

    TITLE = "Anechoic Turntable"
    SUB_TITLE = "Firmware diagnostic controller"
    CSS = """
    Screen {
        layout: vertical;
    }

    #body {
        height: 1fr;
        overflow-y: auto;
    }

    #summary {
        height: 6;
    }

    .panel, .stream-panel, .command-column, .operation-panel {
        border: round $primary;
        padding: 0 1;
    }

    .panel-title {
        text-style: bold;
        color: $accent;
    }

    #controller-panel {
        width: 1fr;
        min-width: 42;
    }

    #state-panel {
        width: 18;
    }

    #position-panel, #target-panel {
        width: 20;
    }

    #controller-actions {
        dock: right;
        width: 30;
        height: 3;
    }

    #connect-toggle {
        width: 14;
        min-width: 14;
        height: 3;
    }

    #emergency-stop {
        width: 16;
        min-width: 16;
        height: 3;
    }

    .status-box {
        height: 1;
        content-align: center middle;
        text-style: bold;
    }

    .status-neutral {
        background: $primary;
    }

    .status-safe {
        background: $success;
    }

    .status-active, .status-unset {
        background: $warning;
        color: $surface;
    }

    .status-error {
        background: $error;
    }

    #streams {
        height: 1fr;
        min-height: 8;
    }

    .stream-panel {
        width: 1fr;
    }

    .stream-heading {
        height: 3;
    }

    #filter-parsed {
        dock: right;
        width: 10;
        height: 3;
    }

    .stream-output, #command-raw {
        height: 1fr;
        overflow: hidden;
    }

    #commands-panel {
        border: round $primary;
        height: 1fr;
        min-height: 8;
        padding: 0 1;
    }

    #command-columns {
        height: 1fr;
    }

    .command-column {
        width: 1fr;
        border: none;
        padding: 0 1 0 0;
    }

    #operations {
        height: 10;
    }

    .operation-panel {
        width: 1fr;
    }

    .field-labels {
        height: 1;
    }

    .operation-fields {
        height: 3;
    }

    .field-labels Label {
        width: 1fr;
        color: $text-muted;
    }

    .operation-fields Input {
        width: 1fr;
        height: 3;
    }

    .operation-actions {
        height: 3;
    }

    .operation-actions Button {
        width: 1fr;
        height: 3;
    }

    #command {
        height: 3;
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
        self._session = _TurntableTuiSession(connector=connector)
        self._refresh_interval = refresh_interval
        self._parsed_kinds = set(_MESSAGE_KINDS) - {"position"}
        self._timeout_error_hidden = False
        self._firmware_version: str | None = None

    def compose(self) -> ComposeResult:
        with ScrollableContainer(id="body"):
            with Horizontal(id="summary"):
                with Vertical(classes="panel", id="controller-panel"):
                    yield Label("Connection / Controller", classes="panel-title")
                    with Horizontal(id="controller-actions"):
                        yield Button("Connect", id="connect-toggle", variant="primary")
                        yield Button("EMERGENCY STOP", id="emergency-stop", variant="error")
                    yield Static("status: disconnected    port: —", id="connection", markup=False)
                    yield Static("Firmware version: ?", id="firmware-version", markup=False)
                    yield Static("activity: —\ncommunication: —", id="controller", markup=False)
                with Vertical(classes="panel", id="state-panel"):
                    yield Label("State", classes="panel-title")
                    yield Static("DISCONNECTED", id="state-status", classes="status-box status-neutral", markup=False)
                    yield Static("NOT SET", id="position-status", classes="status-box status-unset", markup=False)
                with Vertical(classes="panel", id="position-panel"):
                    yield Label("Position", classes="panel-title")
                    yield Static("pan: —", id="azimuth", markup=False)
                    yield Static("tilt: —", id="elevation", markup=False)
                with Vertical(classes="panel", id="target-panel"):
                    yield Label("Target", classes="panel-title")
                    yield Static("pan: —", id="target-azimuth", markup=False)
                    yield Static("tilt: —", id="target-elevation", markup=False)
            with Horizontal(id="streams"):
                with Vertical(classes="stream-panel"):
                    yield Label("Raw", classes="panel-title stream-heading")
                    yield Static("—", id="serial-raw", classes="stream-output", markup=False)
                with Vertical(classes="stream-panel"):
                    yield Label("Parsed", classes="panel-title stream-heading")
                    yield Button("Filter", id="filter-parsed")
                    yield Static("—", id="serial-parsed", classes="stream-output", markup=False)
            with Vertical(id="commands-panel"):
                yield Label("Commands", classes="panel-title")
                with Horizontal(id="command-columns"):
                    with Vertical(classes="command-column"):
                        yield Label("Output", classes="panel-title")
                        yield RichLog(id="messages", markup=False, wrap=True)
                    with Vertical(classes="command-column"):
                        yield Label("Raw", classes="panel-title")
                        yield Static("—", id="command-raw", markup=False)
            with Horizontal(id="operations"):
                with Vertical(classes="operation-panel"):
                    yield Label("Move", classes="panel-title")
                    with Horizontal(classes="field-labels"):
                        yield Label("Pan")
                        yield Label("Tilt")
                        yield Label("Timeout")
                    with Horizontal(classes="operation-fields"):
                        yield Input(value="0", placeholder="pan", id="move-az", type="number")
                        yield Input(value="0", placeholder="tilt", id="move-el", type="number")
                        yield Input(placeholder="auto", id="move-timeout", type="number")
                    with Horizontal(classes="operation-actions"):
                        yield Button("Move", id="move-submit", variant="primary")
                        yield Button("Go home", id="move-home")
                with Vertical(classes="operation-panel"):
                    yield Label("Set", classes="panel-title")
                    with Horizontal(classes="field-labels"):
                        yield Label("Pan")
                        yield Label("Tilt")
                        yield Label("Timeout")
                    with Horizontal(classes="operation-fields"):
                        yield Input(value="0", placeholder="pan", id="set-az", type="number")
                        yield Input(value="0", placeholder="tilt", id="set-el", type="number")
                        yield Input(value="5", placeholder="timeout", id="set-timeout", type="number")
                    with Horizontal(classes="operation-actions"):
                        yield Button("Set", id="set-submit", variant="primary")
                        yield Button("Confirm", id="set-confirm")
        yield CommandInput(placeholder="command> version", id="command")
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

        if event.input.id != "command":
            return
        command_line = event.value.strip()
        if command_line:
            command_input = event.input
            if isinstance(command_input, CommandInput):
                command_input.remember(command_line)
        event.input.clear()
        if command_line:
            self.execute_command(command_line)

    def on_input_changed(self, event: Input.Changed) -> None:
        """Refresh the automatic timeout when a move coordinate changes."""

        if event.input.id in {"move-az", "move-el"}:
            self._update_move_timeout_placeholder()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle diagnostic and operation buttons."""

        button_id = event.button.id
        if button_id == "connect-toggle":
            if self._session.connected:
                self._disconnect()
            else:
                self._begin_connection()
        elif button_id == "emergency-stop":
            self._stop_turntable()
        elif button_id == "filter-parsed":
            self.push_screen(ParsedFilterModal(self._parsed_kinds), self._apply_parsed_filter)
        elif button_id == "move-submit":
            self._queue_from_inputs("mov", "move")
        elif button_id == "move-home":
            self._queue_coordinates("mov", Coordinates(pan=0, tilt=0))
        elif button_id == "set-submit":
            self._queue_from_inputs("set", "set")
        elif button_id == "set-confirm":
            self._confirm_position()

    def execute_command(self, command_line: str) -> None:
        """Execute one diagnostic command without blocking on discovery."""

        command, _, arguments = command_line.partition(" ")
        arguments = arguments.strip()

        if command == "connect":
            if self._reject_arguments(command, arguments):
                return
            self._begin_connection()
        elif command == "disconnect":
            if self._reject_arguments(command, arguments):
                return
            self._disconnect()
        elif command == "version":
            if self._reject_arguments(command, arguments):
                return
            self._request_version()
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
        elif command == "set_cnt":
            self._set_counters(arguments)
        elif command == "mov_cnt":
            self._move_to_counters(arguments)
        elif command == "counter?":
            if self._reject_arguments(command, arguments):
                return
            self._request_counters()
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
            self.query_one("#connection", Static).update("status: unavailable    port: —")
            self._update_status_indicators("unavailable", False)
            self.query_one("#controller", Static).update(f"activity: —\nerror: {exc}")
            return

        if snapshot is None:
            self.query_one("#connection", Static).update("status: disconnected    port: —")
            self.query_one("#connect-toggle", Button).label = "Connect"
            self.query_one("#firmware-version", Static).update("Firmware version: ?")
            self._update_status_indicators("disconnected", False)
            self._update_position("azimuth", "elevation", None)
            self._update_position("target-azimuth", "target-elevation", None)
            self.query_one("#serial-raw", Static).update("—")
            self.query_one("#serial-parsed", Static).update("—")
            self.query_one("#command-raw", Static).update("—")
            self.query_one("#controller", Static).update("activity: —\ncommunication: —")
            self._update_move_timeout_placeholder()
            return

        self.query_one("#connection", Static).update(f"status: {snapshot.state.value}    port: {self._session.port or '—'}")
        self.query_one("#connect-toggle", Button).label = "Disconnect"
        self._update_position("azimuth", "elevation", snapshot.corrected_position)
        self._update_position("target-azimuth", "target-elevation", snapshot.target_position)
        self._update_receive_streams(self._session.events())
        self._update_command_raw(self._session.command_history())
        self._update_status_indicators(snapshot.state.value, snapshot.has_been_set)
        self.query_one("#firmware-version", Static).update(f"Firmware version: {self._firmware_version or '?'}")

        communication_age = snapshot.seconds_since_last_communication
        communication = "never" if math.isinf(communication_age) else f"{communication_age:.2f}s ago"
        activity = snapshot.activity.value
        if snapshot.activity_phase is not None:
            activity = f"{activity} ({snapshot.activity_phase})"
        controller_lines = [
            f"activity: {activity}    queue: {snapshot.queued_command_count}",
            f"communication: {communication}",
        ]
        if snapshot.pending_acknowledgement_command is not None:
            controller_lines.append(f"acknowledgement: pending {snapshot.pending_acknowledgement_command}")
        elif snapshot.most_recent_acknowledgement is not None:
            acknowledgement = snapshot.most_recent_acknowledgement
            reason = "" if acknowledgement.reason is None else f" ({acknowledgement.reason})"
            controller_lines.append(f"acknowledgement: {acknowledgement.status} {acknowledgement.command}{reason}")
        if snapshot.last_error is None or not snapshot.last_error.startswith("TimeoutError:") or snapshot.state.value == "timed_out":
            self._timeout_error_hidden = False
        elif snapshot.activity.value == "moving":
            self._timeout_error_hidden = True
        if snapshot.last_error is not None and not self._timeout_error_hidden:
            controller_lines.append(f"error: {snapshot.last_error}")
        self.query_one("#controller", Static).update("\n".join(controller_lines))
        self._update_move_timeout_placeholder()

    def _update_move_timeout_placeholder(self) -> None:
        """Show the calculated default while the timeout input is blank."""

        timeout_input = self.query_one("#move-timeout", Input)
        placeholder = "auto"
        try:
            coordinates = Coordinates(
                pan=float(self.query_one("#move-az", Input).value),
                tilt=float(self.query_one("#move-el", Input).value),
            )
            timeout = self._session.estimate_move_timeout(coordinates)
            placeholder = f"auto: {timeout:.2f} seconds"
        except (NotConnectedError, TurntableError, ValueError):
            pass
        timeout_input.placeholder = placeholder

    @work(thread=True, exclusive=True, group="connection")
    def _connect(self) -> None:
        result = self._session.connect()
        self.call_from_thread(self._connection_finished, result)

    def _begin_connection(self) -> None:
        """Start background device discovery for a fresh connection."""

        self._firmware_version = None
        self.query_one("#connect-toggle", Button).label = "Connecting…"
        self._write_message("connecting...")
        self._connect()

    def _disconnect(self) -> None:
        warnings = self._session.close()
        self._disconnection_finished(warnings)

    def _disconnection_finished(self, warnings: tuple[str, ...]) -> None:
        self._firmware_version = None
        self._write_cleanup_warnings(warnings)
        self._write_message("disconnected")
        self.refresh_controller_state()

    def _connection_finished(self, result: ConnectionResult) -> None:
        self._write_cleanup_warnings(result.cleanup_warnings)
        if result.error is not None:
            self._write_message(f"connection failed: {result.error}")
        else:
            self._write_message(f"connected: {result.port}")
        self.refresh_controller_state()

    def _queue_position(self, command: Literal["set", "mov"], arguments: str) -> None:
        try:
            coordinates = parse_coordinates(arguments)
        except CommandSyntaxError as exc:
            self._write_message(f"error: {exc}")
            return
        self._queue_coordinates(command, coordinates)

    def _queue_from_inputs(self, command: Literal["set", "mov"], prefix: str) -> None:
        try:
            coordinates = Coordinates(
                pan=float(self.query_one(f"#{prefix}-az", Input).value),
                tilt=float(self.query_one(f"#{prefix}-el", Input).value),
            )
            timeout_value = self.query_one(f"#{prefix}-timeout", Input).value.strip()
            timeout = None if command == "mov" and not timeout_value else float(timeout_value)
        except ValueError:
            self._write_message("error: pan, tilt, and timeout must be numbers")
            return
        self._queue_coordinates(command, coordinates, timeout=timeout)

    def _queue_coordinates(
        self,
        command: Literal["set", "mov"],
        coordinates: Coordinates,
        *,
        timeout: float | None = None,
    ) -> None:
        try:
            if timeout is None:
                self._session.queue_position(command, coordinates)
            else:
                self._session.queue_position_with_timeout(command, coordinates, timeout)
        except (NotConnectedError, TurntableError, ValueError) as exc:
            self._write_message(f"error: {exc}")
            return
        timeout_text = "" if timeout is None else f" timeout={timeout:g}"
        self._write_message(f"{command} queued: pan={coordinates.pan:.3f} tilt={coordinates.tilt:.3f}{timeout_text}")
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

    def _set_counters(self, arguments: str) -> None:
        try:
            counters = parse_counter_values(arguments)
            self._session.set_counters(counters)
        except (CommandSyntaxError, NotConnectedError, TurntableError, ValueError) as exc:
            self._write_message(f"error: {exc}")
            return
        self._write_message(f"counter set queued: pan={counters.pan} tilt={counters.tilt}")
        self.refresh_controller_state()

    def _move_to_counters(self, arguments: str) -> None:
        try:
            counters = parse_counter_values(arguments)
            self._session.move_to_counters(counters)
        except (CommandSyntaxError, NotConnectedError, TurntableError, ValueError) as exc:
            self._write_message(f"error: {exc}")
            return
        self._write_message(f"counter move queued: pan={counters.pan} tilt={counters.tilt}")
        self.refresh_controller_state()

    def _request_counters(self) -> None:
        try:
            self._session.request_counters()
        except (NotConnectedError, TurntableError) as exc:
            self._write_message(f"error: {exc}")
            return
        self._write_message("counter query queued")
        self.refresh_controller_state()

    def _request_version(self) -> None:
        try:
            self._session.request_version()
        except (NotConnectedError, TurntableError) as exc:
            self._write_message(f"error: {exc}")
            return
        self._write_message("version query queued")
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
        self._write_message(f"position confirmed: pan={position.pan:.3f} tilt={position.tilt:.3f}")
        self.refresh_controller_state()

    @staticmethod
    def _format_info(snapshot: TurntableCompleteState) -> str:
        parts = [f"state={snapshot.state.value}", f"activity={snapshot.activity.value}"]
        if snapshot.corrected_position is None:
            parts.extend(("pan=?", "tilt=?"))
        else:
            parts.extend((f"pan={snapshot.corrected_position.pan:.3f}", f"tilt={snapshot.corrected_position.tilt:.3f}"))
        if snapshot.target_position is not None:
            parts.extend((f"target_pan={snapshot.target_position.pan:.3f}", f"target_tilt={snapshot.target_position.tilt:.3f}"))
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

    def _update_position(self, azimuth_widget: str, elevation_widget: str, position: PanTilt | YawPitch | None) -> None:
        if position is None:
            azimuth = elevation = "—"
        elif isinstance(position, PanTilt):
            azimuth = f"{position.pan:.3f}°"
            elevation = f"{position.tilt:.3f}°"
        else:
            azimuth = f"{position.yaw:.3f}°"
            elevation = f"{position.pitch:.3f}°"
        self.query_one(f"#{azimuth_widget}", Static).update(f"pan: {azimuth}")
        self.query_one(f"#{elevation_widget}", Static).update(f"tilt: {elevation}")

    def _update_receive_streams(self, events: tuple[ReceivedMessage, ...]) -> None:
        for event in reversed(events):
            if isinstance(event, ReceivedMessageVersion):
                self._firmware_version = event.version
                break
        recent_events = events[-5:]
        raw_lines = [self._format_bytes(event.message) for event in recent_events]
        filtered_events = [event for event in events if event.kind in self._parsed_kinds]
        parsed_lines = [self._format_parsed_event(event) for event in filtered_events[-5:]]
        self.query_one("#serial-raw", Static).update("\n".join(raw_lines) if raw_lines else "—")
        self.query_one("#serial-parsed", Static).update("\n".join(parsed_lines) if parsed_lines else "—")

    def _update_command_raw(self, commands: tuple[CommandWrite, ...]) -> None:
        lines = [self._format_bytes(command.command) for command in commands[-5:]]
        self.query_one("#command-raw", Static).update("\n".join(lines) if lines else "—")

    def _apply_parsed_filter(self, selected_kinds: set[str] | None) -> None:
        if selected_kinds is None:
            return
        self._parsed_kinds = selected_kinds
        self.refresh_controller_state()

    def _update_status_indicators(self, state: str, has_been_set: bool) -> None:
        state_class = "status-neutral"
        if state == "stopped":
            state_class = "status-safe"
        elif state == "moving":
            state_class = "status-active"
        elif state in {"timed_out", "error", "no_communication"}:
            state_class = "status-error"
        self._set_status_box("state-status", state.replace("_", " ").upper(), state_class)
        position_class = "status-safe" if has_been_set else "status-unset"
        position_text = "SET" if has_been_set else "NOT SET"
        self._set_status_box("position-status", position_text, position_class)

    def _set_status_box(self, widget_id: str, text: str, status_class: str) -> None:
        widget = self.query_one(f"#{widget_id}", Static)
        widget.update(text)
        widget.remove_class("status-neutral", "status-safe", "status-active", "status-unset", "status-error")
        widget.add_class(status_class)

    @staticmethod
    def _format_bytes(message: bytes) -> str:
        return repr(message)

    @staticmethod
    def _format_parsed_event(event: ReceivedMessage) -> str:
        if isinstance(event, ReceivedMessagePosition):
            return f"position: pan={event.yaw if event.yaw is not None else '—'} tilt={event.pitch if event.pitch is not None else '—'}"
        if isinstance(event, ReceivedMessageVersion):
            return f"version: {event.version}"
        if isinstance(event, ReceivedMessageCounter):
            return f"counter: pan={event.pan} tilt={event.tilt}"
        if isinstance(event, ReceivedMessageAcknowledgement):
            reason = "" if event.reason is None else f" ({event.reason})"
            return f"{event.status.lower()}: {event.command}{reason}"
        if isinstance(event, ReceivedMessageError):
            return f"error: {event.reason}"
        text = event.message.decode("ascii", errors="backslashreplace").rstrip("\r\n")
        return f"other: {text}"


def main() -> None:
    """Run the auto-updating turntable diagnostic TUI."""

    TurntableTui().run()


if __name__ == "__main__":
    main()
