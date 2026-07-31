import asyncio
from types import SimpleNamespace

from textual.widgets import Static

from anechoic_turntable import PanTilt
from anechoic_turntable import TurntableActivity
from anechoic_turntable import TurntableState
from anechoic_turntable import YawPitch
from anechoic_turntable.messages import ReceivedMessage
from anechoic_turntable.tui import TurntableTui


class FakeTurntable:
    def __init__(self):
        self.port = "/dev/fake0"
        self.move_calls = []
        self.set_calls = []
        self.confirm_calls = 0
        self.abort_calls = 0
        self.raw_writes = []
        self.closed = False
        self.snapshot = SimpleNamespace(
            state=TurntableState.STOPPED,
            activity=TurntableActivity.IDLE,
            activity_phase=None,
            uncorrected_position=YawPitch(2.0, -3.0),
            corrected_position=PanTilt(12.0, 5.0),
            target_position=None,
            recent_events=tuple(ReceivedMessage(message=f"serial line {index}\r\n".encode()) for index in range(1, 7)),
            seconds_since_last_communication=0.04,
            queued_command_count=0,
            last_error=None,
        )

    def get_complete_state(self):
        return self.snapshot

    def set_position(self, *, pan, tilt):
        self.set_calls.append((pan, tilt))

    def move_to(self, *, pan, tilt):
        self.move_calls.append((pan, tilt))

    def confirm_position(self):
        self.confirm_calls += 1

    def abort(self):
        self.abort_calls += 1

    def send_raw(self, payload):
        self.raw_writes.append(payload)

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

            assert rendered_text(app.query_one("#connection", Static)) == "status: stopped"
            assert rendered_text(app.query_one("#azimuth", Static)) == "az: 12.000°"
            assert rendered_text(app.query_one("#elevation", Static)) == "el: 5.000°"
            assert rendered_text(app.query_one("#reported-azimuth", Static)) == "az: 2.000°"
            assert rendered_text(app.query_one("#reported-elevation", Static)) == "el: -3.000°"
            assert rendered_text(app.query_one("#serial-output", Static)) == "\n".join(f"serial line {index}" for index in range(2, 7))
            assert table.move_calls == [(-3.5, 4.0)]
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


def test_tui_emergency_stop_button_aborts():
    async def exercise():
        table = FakeTurntable()
        app = TurntableTui(connector=lambda: table, refresh_interval=60)

        async with app.run_test() as pilot:
            submit(app, "connect")
            await pilot.click("#emergency-stop")

            assert table.abort_calls == 1

        assert table.abort_calls == 2

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
