import asyncio
import datetime
from types import SimpleNamespace

from textual.widgets import Button
from textual.widgets import Checkbox
from textual.widgets import Input
from textual.widgets import Static

from anechoic_turntable import PanTilt
from anechoic_turntable import TurntableActivity
from anechoic_turntable import TurntableState
from anechoic_turntable import YawPitch
from anechoic_turntable.controller import CommandWrite
from anechoic_turntable.messages import ReceivedMessage
from anechoic_turntable.messages import ReceivedMessageCounter
from anechoic_turntable.messages import ReceivedMessagePosition
from anechoic_turntable.messages import ReceivedMessageVersion
from anechoic_turntable.tui import TurntableTui


class FakeTurntable:
    def __init__(self):
        self.port = "/dev/fake0"
        self.move_calls = []
        self.set_calls = []
        self.confirm_calls = 0
        self.abort_calls = 0
        self.raw_writes = []
        self.counter_requests = 0
        self.counter_sets = []
        self.closed = False
        self.receive_events = (
            ReceivedMessage(message=b"diagnostic one\r\n"),
            ReceivedMessageVersion(message=b"MSG:VERSION:1.2.3;\r\n", version="1.2.3"),
            *(
                ReceivedMessagePosition(
                    message=f"Pos= El: -3.00 , Az: {index:.2f}\r\n".encode(),
                    yaw=float(index),
                    pitch=-3.0,
                )
                for index in range(1, 7)
            ),
            ReceivedMessageCounter(message=b"MSG:CNT:PAN=12345,TILT=5555;\r\n", pan=12345, tilt=5555),
        )
        self.command_writes = (CommandWrite(timestamp=datetime.datetime.now(datetime.timezone.utc), command=b"CMD:VERSION;"),)
        self.snapshot = SimpleNamespace(
            state=TurntableState.STOPPED,
            activity=TurntableActivity.IDLE,
            activity_phase=None,
            uncorrected_position=YawPitch(2.0, -3.0),
            corrected_position=PanTilt(12.0, 5.0),
            target_position=None,
            recent_events=self.receive_events,
            seconds_since_last_communication=0.04,
            queued_command_count=0,
            last_error=None,
        )

    def get_complete_state(self):
        return self.snapshot

    def set_position(self, *, pan, tilt, timeout=5.0):
        self.set_calls.append((pan, tilt, timeout))

    def move_to(self, *, pan, tilt, move_timeout=120.0):
        self.move_calls.append((pan, tilt, move_timeout))

    def confirm_position(self):
        self.confirm_calls += 1

    def abort(self):
        self.abort_calls += 1

    def send_raw(self, payload):
        self.raw_writes.append(payload)

    def request_counters(self):
        self.counter_requests += 1

    def set_counters(self, *, pan, tilt):
        self.counter_sets.append((pan, tilt))

    def events(self):
        return self.receive_events

    def command_history(self):
        return self.command_writes

    def close(self):
        self.closed = True


def submit(app, command):
    if command == "connect":
        # Exercise connection completion synchronously; TurntableSession's
        # connection lifecycle is tested separately.
        app._connection_finished(app._session.connect())
        return
    app.execute_command(command)


def rendered_text(widget):
    return str(widget.render())


def test_tui_connects_updates_state_and_queues_commands():
    async def exercise():
        table = FakeTurntable()
        app = TurntableTui(connector=lambda: table, refresh_interval=60)

        async with app.run_test():
            submit(app, "connect")
            submit(app, "confirm")
            submit(app, "mov az=-3.5 el=4")
            app.refresh_controller_state()

            assert rendered_text(app.query_one("#connection", Static)) == "status: stopped    port: /dev/fake0"
            assert rendered_text(app.query_one("#azimuth", Static)) == "az: 12.000°"
            assert rendered_text(app.query_one("#elevation", Static)) == "el: 5.000°"
            assert "Az: 6.00" in rendered_text(app.query_one("#serial-raw", Static))
            assert "version: 1.2.3" not in rendered_text(app.query_one("#serial-parsed", Static))
            assert "position: az=6.0 el=-3.0" in rendered_text(app.query_one("#serial-parsed", Static))
            assert rendered_text(app.query_one("#command-raw", Static)) == "b'CMD:VERSION;'"
            assert table.move_calls == [(-3.5, 4.0, 120.0)]
            assert table.confirm_calls == 1

        assert table.abort_calls == 1
        assert table.closed

    asyncio.run(exercise())


def test_tui_sends_raw_command_and_stop_command():
    async def exercise():
        table = FakeTurntable()
        app = TurntableTui(connector=lambda: table, refresh_interval=60)

        async with app.run_test():
            submit(app, "connect")
            submit(app, "raw CMD:MOV:0.000,-70.00;")
            submit(app, "stop")

            assert table.raw_writes == [b"CMD:MOV:0.000,-70.00;"]
            assert table.abort_calls == 1

        assert table.abort_calls == 2

    asyncio.run(exercise())


def test_tui_queues_counter_set_and_query_commands():
    async def exercise():
        table = FakeTurntable()
        app = TurntableTui(connector=lambda: table, refresh_interval=60)

        async with app.run_test():
            submit(app, "connect")
            submit(app, "counter pan=12345 tilt=5555")
            submit(app, "counter?")
            app.refresh_controller_state()

            assert table.counter_sets == [(12345, 5555)]
            assert table.counter_requests == 1
            assert "counter: pan=12345 tilt=5555" in rendered_text(app.query_one("#serial-parsed", Static))

    asyncio.run(exercise())


def test_tui_rejects_malformed_counter_commands():
    async def exercise():
        table = FakeTurntable()
        app = TurntableTui(connector=lambda: table, refresh_interval=60)

        async with app.run_test():
            submit(app, "connect")
            for command in (
                "counter pan=12345",
                "counter pan=1.5 tilt=2",
                "counter pan=-1 tilt=2",
                "counter? now",
            ):
                submit(app, command)

            assert table.counter_sets == []
            assert table.counter_requests == 0

    asyncio.run(exercise())


def test_tui_emergency_stop_button_aborts():
    async def exercise():
        table = FakeTurntable()
        app = TurntableTui(connector=lambda: table, refresh_interval=60)

        async with app.run_test(size=(120, 40)) as pilot:
            submit(app, "connect")
            await pilot.click("#emergency-stop")

            assert table.abort_calls == 1

        assert table.abort_calls == 2

    asyncio.run(exercise())


def test_tui_expands_data_panels_and_preserves_button_labels():
    async def exercise():
        app = TurntableTui(refresh_interval=60)

        async with app.run_test(size=(180, 50)):
            assert app.query_one("#streams").region.height >= 12
            assert app.query_one("#commands-panel").region.height >= 12
            for selector, label in (
                ("#emergency-stop", "EMERGENCY STOP"),
                ("#filter-parsed", "Filter"),
                ("#move-submit", "Move"),
                ("#move-home", "Go home"),
                ("#set-submit", "Set"),
                ("#set-confirm", "Confirm"),
            ):
                button = app.query_one(selector, Button)
                assert button.region.height == 3
                assert str(button.label) == label

            for prefix in ("move", "set"):
                input_region = app.query_one(f"#{prefix}-az", Input).region
                button_region = app.query_one(f"#{prefix}-submit", Button).region
                assert input_region.height == 3
                assert input_region.bottom == button_region.y

    asyncio.run(exercise())


def test_tui_rejects_malformed_position_commands():
    async def exercise():
        table = FakeTurntable()
        app = TurntableTui(connector=lambda: table, refresh_interval=60)

        async with app.run_test():
            submit(app, "connect")
            submit(app, "set az=12")

            assert table.set_calls == []

    asyncio.run(exercise())


def test_tui_hides_timeout_error_when_next_move_begins():
    async def exercise():
        table = FakeTurntable()
        app = TurntableTui(connector=lambda: table, refresh_interval=60)

        async with app.run_test():
            submit(app, "connect")
            table.snapshot.state = TurntableState.TIMED_OUT
            table.snapshot.last_error = "TimeoutError: Turntable command timed out"
            app.refresh_controller_state()
            assert "TimeoutError" in rendered_text(app.query_one("#controller", Static))

            table.snapshot.state = TurntableState.MOVING
            table.snapshot.activity = TurntableActivity.MOVING
            app.refresh_controller_state()
            assert "TimeoutError" not in rendered_text(app.query_one("#controller", Static))

    asyncio.run(exercise())


def test_tui_move_set_and_filter_controls():
    async def exercise():
        table = FakeTurntable()
        app = TurntableTui(connector=lambda: table, refresh_interval=60)

        async with app.run_test(size=(120, 40)) as pilot:
            submit(app, "connect")
            app.query_one("#move-az", Input).value = "12.5"
            app.query_one("#move-el", Input).value = "-4"
            app.query_one("#move-timeout", Input).value = "30"
            await pilot.click("#move-submit")
            await pilot.click("#move-home")

            app.query_one("#set-az", Input).value = "3"
            app.query_one("#set-el", Input).value = "2"
            app.query_one("#set-timeout", Input).value = "9"
            await pilot.click("#set-submit")
            await pilot.click("#set-confirm")

            assert table.move_calls == [(12.5, -4.0, 30.0), (0, 0, 240)]
            assert table.set_calls == [(3.0, 2.0, 9.0)]
            assert table.confirm_calls == 1

            await pilot.click("#filter-parsed")
            app.screen.query_one("#filter-position", Checkbox).value = False
            await pilot.click("#apply-filter")
            assert rendered_text(app.query_one("#serial-parsed", Static)) == "other\nversion: 1.2.3\ncounter: pan=12345 tilt=5555"

        assert table.abort_calls == 1

    asyncio.run(exercise())
