import asyncio
from types import SimpleNamespace

from textual.widgets import Input
from textual.widgets import Static

from anechoic_turntable import PanTilt
from anechoic_turntable import TurntableActivity
from anechoic_turntable import TurntableState
from anechoic_turntable.tui import TurntableTui


class FakeTurntable:
    def __init__(self):
        self.port = "/dev/fake0"
        self.move_calls = []
        self.set_calls = []
        self.confirm_calls = 0
        self.aborted = False
        self.closed = False
        self.snapshot = SimpleNamespace(
            state=TurntableState.STOPPED,
            activity=TurntableActivity.IDLE,
            activity_phase=None,
            corrected_position=PanTilt(12.0, 5.0),
            target_position=None,
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
        self.aborted = True

    def close(self):
        self.closed = True


async def submit(app, pilot, command):
    command_input = app.query_one("#command", Input)
    command_input.value = command
    command_input.focus()
    await pilot.press("enter")
    await pilot.pause()


def rendered_text(widget):
    return str(widget.render())


def test_tui_connects_updates_state_and_queues_commands():
    async def exercise():
        table = FakeTurntable()
        app = TurntableTui(connector=lambda: table, refresh_interval=60)

        async with app.run_test() as pilot:
            await submit(app, pilot, "connect")
            await submit(app, pilot, "confirm")
            await submit(app, pilot, "mov az=-3.5 el=4")
            app.refresh_controller_state()

            assert rendered_text(app.query_one("#connection", Static)) == "status: stopped"
            assert rendered_text(app.query_one("#azimuth", Static)) == "az: 12.000°"
            assert rendered_text(app.query_one("#elevation", Static)) == "el: 5.000°"
            assert table.move_calls == [(-3.5, 4.0)]
            assert table.confirm_calls == 1

        assert table.aborted
        assert table.closed

    asyncio.run(exercise())


def test_tui_rejects_malformed_position_commands():
    async def exercise():
        table = FakeTurntable()
        app = TurntableTui(connector=lambda: table, refresh_interval=60)

        async with app.run_test() as pilot:
            await submit(app, pilot, "connect")
            await submit(app, pilot, "set az=12")

            assert table.set_calls == []

    asyncio.run(exercise())
