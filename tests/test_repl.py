import io
from types import SimpleNamespace

import pytest

from anechoic_turntable import PanTilt, TurntableActivity, TurntableState
from anechoic_turntable.repl import (
    CommandSyntaxError,
    Coordinates,
    TurntableShell,
    parse_coordinates,
)


class FakeTurntable:
    def __init__(self, port="/dev/fake0"):
        self.port = port
        self.set_calls = []
        self.move_calls = []
        self.aborted = False
        self.closed = False
        self.snapshot = SimpleNamespace(
            state=TurntableState.STOPPED,
            activity=TurntableActivity.IDLE,
            corrected_position=PanTilt(12.0, 5.0),
            target_position=None,
            last_error=None,
        )

    def set_position(self, *, pan, tilt):
        self.set_calls.append((pan, tilt))

    def move_to(self, *, pan, tilt):
        self.move_calls.append((pan, tilt))

    def abort(self):
        self.aborted = True

    def close(self):
        self.closed = True

    def get_complete_state(self):
        return self.snapshot


def test_coordinates_accept_either_order():
    assert parse_coordinates("az=12 el=5.0") == Coordinates(
        azimuth=12.0,
        elevation=5.0,
    )
    assert parse_coordinates("el=-5.25 az=+12") == Coordinates(
        azimuth=12.0,
        elevation=-5.25,
    )


@pytest.mark.parametrize(
    "arguments",
    [
        "",
        "12 5",
        "az=12",
        "az=12 az=5",
        "az=12 elevation=5",
        "AZ=12 el=5",
        "az=nan el=5",
        "az=12 el=5 extra",
    ],
)
def test_coordinate_parsing_is_strict(arguments):
    with pytest.raises(CommandSyntaxError):
        parse_coordinates(arguments)


def test_shell_connects_reports_info_and_queues_commands():
    output = io.StringIO()
    table = FakeTurntable()
    shell = TurntableShell(connector=lambda: table, stdout=output)

    assert shell.onecmd("connect") is None
    assert shell.onecmd("info") is None
    assert shell.onecmd("set el=5 az=12") is None
    assert shell.onecmd("mov az=-3.5 el=4") is None

    assert table.set_calls == [(12.0, 5.0)]
    assert table.move_calls == [(-3.5, 4.0)]
    assert "connected: /dev/fake0" in output.getvalue()
    assert "state=stopped activity=idle az=12.000 el=5.000" in output.getvalue()
    assert "set queued: az=12.000 el=5.000" in output.getvalue()
    assert "mov queued: az=-3.500 el=4.000" in output.getvalue()


def test_shell_requires_a_connection_for_position_commands():
    output = io.StringIO()
    shell = TurntableShell(stdout=output)

    shell.onecmd("set az=12 el=5")

    assert output.getvalue() == "error: not connected\n"


def test_shell_reconnect_and_exit_stop_and_close_connections():
    output = io.StringIO()
    first = FakeTurntable("/dev/fake0")
    second = FakeTurntable("/dev/fake1")
    tables = iter((first, second))
    shell = TurntableShell(connector=lambda: next(tables), stdout=output)

    shell.onecmd("connect")
    shell.onecmd("connect")
    assert first.aborted
    assert first.closed

    assert shell.onecmd("exit")
    assert second.aborted
    assert second.closed


def test_info_reports_disconnected_state():
    output = io.StringIO()
    shell = TurntableShell(stdout=output)

    shell.onecmd("info")

    assert output.getvalue() == "state=disconnected\n"


def test_cmd_default_question_mark_alias_shows_help():
    output = io.StringIO()
    shell = TurntableShell(stdout=output)

    shell.onecmd("?")

    assert "Documented commands" in output.getvalue()
    assert "connect" in output.getvalue()
    assert "info" in output.getvalue()


def test_shell_reports_connection_failure_and_remains_disconnected():
    output = io.StringIO()

    def fail():
        raise OSError("adapter unavailable")

    shell = TurntableShell(connector=fail, stdout=output)

    shell.onecmd("connect")
    shell.onecmd("info")

    assert "connection failed: adapter unavailable" in output.getvalue()
    assert "state=disconnected" in output.getvalue()
