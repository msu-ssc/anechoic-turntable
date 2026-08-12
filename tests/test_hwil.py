import datetime
from collections import deque

import pytest

from anechoic_turntable.controller import CommandWrite
from anechoic_turntable.controller import TurntableState
from anechoic_turntable.hwil.basic import HardwareTestError
from anechoic_turntable.hwil.basic import HardwareTestRunner
from anechoic_turntable.hwil.basic import OperatorCancelled
from anechoic_turntable.hwil.basic import main
from anechoic_turntable.messages import ReceivedMessageAcknowledgement
from anechoic_turntable.messages import ReceivedMessagePosition
from anechoic_turntable.messages import ReceivedMessageVersion
from anechoic_turntable.positions import PanTilt

TEST_TIME = datetime.datetime(2026, 8, 12, 18, 25, tzinfo=datetime.timezone.utc)


class FakeHardwareTurntable:
    port = "/dev/fake-hwil"

    def __init__(self):
        self._commands = []
        self._events = deque(
            [
                ReceivedMessagePosition(
                    message=b"MSG:POS:PAN=2.000,TILT=-1.000\r\n",
                    timestamp=TEST_TIME,
                    pan=2.0,
                    tilt=-1.0,
                )
            ],
            maxlen=1_000,
        )
        self.position = PanTilt(pan=2.0, tilt=-1.0)
        self.state = TurntableState.NOT_SET
        self.set_calls = []
        self.move_calls = []
        self.abort_calls = 0
        self.abort_error = None
        self.abort_error_on_call = 1
        self.confirm_calls = 0
        self.closed = False

    def abort(self):
        self.abort_calls += 1
        if self.abort_error is not None and self.abort_calls >= self.abort_error_on_call:
            raise self.abort_error
        self.state = TurntableState.STOPPED

    def close(self):
        self.closed = True

    def command_history(self):
        return tuple(self._commands)

    def current_position(self):
        return self.position

    def current_state(self):
        return self.state

    def confirm_position(self):
        self.confirm_calls += 1
        self.state = TurntableState.STOPPED

    def estimate_time(self, *, pan, tilt):
        return 1.0

    def events(self):
        return tuple(self._events)

    def last_error(self):
        return None

    def move_to_blocking(self, *, pan, tilt, move_timeout=None):
        self.move_calls.append((pan, tilt, move_timeout))
        self._record_command("MOV", f"CMD:MOV:{pan:.3f},{tilt:.3f};".encode())
        midpoint = PanTilt(
            pan=(self.position.pan + pan) / 2,
            tilt=(self.position.tilt + tilt) / 2,
        )
        self._record_position(midpoint)
        self.position = PanTilt(pan=pan, tilt=tilt)
        self._record_position(self.position)
        self.state = TurntableState.STOPPED

    def move_to(self, *, pan, tilt, move_timeout=None):
        self.move_calls.append((pan, tilt, move_timeout))
        self._record_command("MOV", f"CMD:MOV:{pan:.3f},{tilt:.3f};".encode())
        self.position = PanTilt(pan=5.5, tilt=0.0) if pan > 0 else PanTilt(pan=0.0, tilt=-5.5)
        self._record_position(self.position)
        self.state = TurntableState.MOVING

    def request_version(self):
        self._record_command("VERSION", b"CMD:VERSION;")
        self._events.append(
            ReceivedMessageVersion(
                message=b"MSG:VERSION:1.2.3;\r\n",
                timestamp=TEST_TIME,
                version="1.2.3",
            )
        )

    def set_position_blocking(self, *, pan, tilt, timeout=5.0):
        del timeout
        self.set_calls.append((pan, tilt))
        self._record_command("SET", f"CMD:SET:{pan:.3f},{tilt:.3f};".encode())
        self.position = PanTilt(pan=pan, tilt=tilt)
        self._record_position(self.position)
        self.state = TurntableState.STOPPED

    def _record_command(self, name, command):
        self._commands.append(CommandWrite(timestamp=TEST_TIME, command=command))
        self._events.append(
            ReceivedMessageAcknowledgement(
                message=f"MSG:ACK:{name};\r\n".encode(),
                timestamp=TEST_TIME,
                status="ACK",
                command=name,
            )
        )

    def _record_position(self, position):
        self._events.append(
            ReceivedMessagePosition(
                message=f"MSG:POS:PAN={position.pan:.3f},TILT={position.tilt:.3f}\r\n".encode(),
                timestamp=TEST_TIME,
                pan=position.pan,
                tilt=position.tilt,
            )
        )


def scripted_input(responses):
    remaining = iter(responses)
    return lambda: next(remaining)


def make_runner(table, responses, monkeypatch):
    monkeypatch.setattr("builtins.input", scripted_input(responses))
    return HardwareTestRunner(table)


def test_hwil_runner_repeats_centering_then_runs_basic_movement_sequence(monkeypatch, capsys):
    table = FakeHardwareTurntable()
    runner = make_runner(
        table,
        [
            "y",  # preflight
            "n",  # reported position is not physically correct
            "2",
            "-1",
            "y",  # approve first centering move
            "n",  # residual physical offset remains
            "n",  # reported zero is not physically correct
            "0.5",
            "0.25",
            "y",  # approve second centering move
            "y",  # physically centered
            "y",
            "y",  # pan +5 approval and observation
            "y",
            "y",  # return home
            "y",
            "y",  # tilt +5
            "y",
            "y",  # return home
            "y",  # begin emergency-stop movement
            "y",  # emergency stop appeared safe
            "y",  # begin final return home
            "y",  # final home position confirmed
            "y",  # begin tilt emergency-stop movement
            "y",  # tilt emergency stop appeared safe
            "y",  # begin second return home
            "y",  # second home position confirmed
        ],
        monkeypatch,
    )

    report = runner.run()

    assert report["status"] == "passed"
    assert report["firmware_version"] == "1.2.3"
    assert len(report["centering_attempts"]) == 2
    assert len(report["steps"]) == 4
    assert table.set_calls == [(2.0, -1.0), (0.5, 0.25)]
    assert [(pan, tilt) for pan, tilt, _timeout in table.move_calls] == [
        (0.0, 0.0),
        (0.0, 0.0),
        (5.0, 0.0),
        (0.0, 0.0),
        (0.0, 5.0),
        (0.0, 0.0),
        (30.0, 0.0),
        (0.0, 0.0),
        (0.0, -30.0),
        (0.0, 0.0),
    ]
    assert table.abort_calls == 3
    rendered = capsys.readouterr().out
    assert "Interactive centering" in rendered
    assert "b'CMD:MOV:5.000,0.000;'" in rendered
    assert "The turntable will move RIGHT 5°." in rendered
    assert "Did the motion complete, and is the current position pan=+5°, tilt=+0°? [y/N]" in rendered
    assert "PASS: Basic functionality HWIL test completed." in rendered
    assert "Pan emergency-stop check" in rendered
    assert "Tilt emergency-stop check" in rendered
    assert report["emergency_stops"]["pan"]["stop_position"]["pan"] > 5.0
    assert report["emergency_stops"]["pan"]["stop_sent"]
    assert report["emergency_stops"]["pan"]["return_home"]["operator_confirmed"]
    assert report["emergency_stops"]["tilt"]["stop_position"]["tilt"] < -5.0
    assert report["emergency_stops"]["tilt"]["stop_sent"]
    assert report["emergency_stops"]["tilt"]["return_home"]["operator_confirmed"]


def test_declining_a_required_movement_cancels_and_stops(monkeypatch):
    table = FakeHardwareTurntable()
    runner = make_runner(
        table,
        [
            "y",  # preflight
            "n",  # reported position is not correct
            "2",
            "-1",
            "y",  # approve centering
            "y",  # centered
            "n",  # decline first basic movement
        ],
        monkeypatch,
    )

    with pytest.raises(OperatorCancelled, match="declined"):
        runner.run()

    assert runner.report["status"] == "cancelled"
    assert table.abort_calls == 1
    assert len(table.move_calls) == 1


def test_rejecting_observed_motion_fails_and_stops_without_continuing(monkeypatch):
    table = FakeHardwareTurntable()
    runner = make_runner(
        table,
        [
            "y",  # preflight
            "n",  # reported position is not correct
            "2",
            "-1",
            "y",  # approve centering
            "y",  # centered
            "y",  # approve first basic movement
            "n",  # reject physical result
        ],
        monkeypatch,
    )

    with pytest.raises(HardwareTestError, match="operator rejected"):
        runner.run()

    assert runner.report["status"] == "failed"
    assert table.abort_calls == 1
    assert [(pan, tilt) for pan, tilt, _timeout in table.move_calls] == [
        (0.0, 0.0),
        (5.0, 0.0),
    ]


def test_final_stop_failure_prevents_a_passing_result(monkeypatch):
    table = FakeHardwareTurntable()
    table.abort_error = OSError("serial link lost")
    table.abort_error_on_call = 3
    runner = make_runner(
        table,
        [
            "y",  # preflight
            "n",  # reported position is not correct
            "2",
            "-1",
            "y",  # approve centering
            "y",  # centered
            "y",
            "y",  # pan +5
            "y",
            "y",  # return home
            "y",
            "y",  # tilt +5
            "y",
            "y",  # return home
            "y",  # begin emergency-stop movement
            "y",  # emergency stop appeared safe
            "y",  # begin final return home
            "y",  # final home position confirmed
            "y",  # begin tilt emergency-stop movement
            "y",  # tilt emergency stop appeared safe
            "y",  # begin second return home
            "y",  # second home position confirmed
        ],
        monkeypatch,
    )

    with pytest.raises(HardwareTestError, match="final stop failed"):
        runner.run()

    assert runner.report["status"] == "failed"
    assert runner.report["final_stop_error"] == "serial link lost"


def test_emergency_stop_is_sent_after_pan_passes_five_degrees_then_returns_home(monkeypatch):
    table = FakeHardwareTurntable()
    runner = make_runner(table, ["y", "y", "y", "y"], monkeypatch)
    table.position = PanTilt(pan=0.0, tilt=0.0)
    table.state = TurntableState.STOPPED

    runner.report["emergency_stops"] = {}
    runner._run_axis_emergency_stop_test(
        axis="pan",
        target=PanTilt(pan=30.0, tilt=0.0),
        abort_position=PanTilt(pan=5.0, tilt=0.0),
    )

    assert table.move_calls[-2][0:2] == (30.0, 0.0)
    assert table.move_calls[-1][0:2] == (0.0, 0.0)
    assert runner.report["emergency_stops"]["pan"]["stop_position"]["pan"] == 5.5
    assert runner.report["emergency_stops"]["pan"]["stop_sent"]
    assert runner.report["emergency_stops"]["pan"]["return_home"]["operator_confirmed"]
    assert table.abort_calls == 1
    assert any("REMAINING_UNTIL_ABORT: pan=-0.500°" in line for line in runner.report["trace"])


def test_correct_reported_position_skips_set_but_still_goes_home(monkeypatch):
    table = FakeHardwareTurntable()
    table.position = PanTilt(pan=3.0, tilt=-2.0)
    runner = make_runner(table, ["y", "y", "y"], monkeypatch)

    runner._center_interactively()

    assert table.confirm_calls == 1
    assert table.set_calls == []
    assert [(pan, tilt) for pan, tilt, _timeout in table.move_calls] == [(0.0, 0.0)]
    assert runner.report["position_confirmation"]["position"] == {"pan": 3.0, "tilt": -2.0}
    assert runner.report["position_confirmation"]["operator_confirmed_centered"]


def test_tilt_emergency_stop_is_sent_after_tilt_passes_negative_five_then_returns_home(monkeypatch):
    table = FakeHardwareTurntable()
    runner = make_runner(table, ["y", "y", "y", "y"], monkeypatch)
    table.position = PanTilt(pan=0.0, tilt=0.0)
    table.state = TurntableState.STOPPED
    runner.report["emergency_stops"] = {}

    runner._run_axis_emergency_stop_test(
        axis="tilt",
        target=PanTilt(pan=0.0, tilt=-30.0),
        abort_position=PanTilt(pan=0.0, tilt=-5.0),
    )

    assert table.move_calls[-2][0:2] == (0.0, -30.0)
    assert table.move_calls[-1][0:2] == (0.0, 0.0)
    assert runner.report["emergency_stops"]["tilt"]["stop_position"]["tilt"] == -5.5
    assert runner.report["emergency_stops"]["tilt"]["stop_sent"]
    assert runner.report["emergency_stops"]["tilt"]["return_home"]["operator_confirmed"]
    assert table.abort_calls == 1
    assert any("REMAINING_UNTIL_ABORT: tilt=+0.500°" in line for line in runner.report["trace"])


def test_operator_movement_text_uses_directions_and_rounded_degrees():
    current = PanTilt(pan=-10.0, tilt=15.4)
    target = PanTilt(pan=-15.2, tilt=5.2)

    assert HardwareTestRunner._movement_description(current, target) == "The turntable will move LEFT 5° and DOWN 10°."
    assert HardwareTestRunner._confirmation_prompt(target) == "Did the motion complete, and is the current position pan=-15°, tilt=+5°? [y/N] "
    assert HardwareTestRunner._movement_description(PanTilt(pan=0.0, tilt=0.0), PanTilt(pan=5.0, tilt=5.0)) == "The turntable will move RIGHT 5° and UP 5°."
    assert HardwareTestRunner._format_position(PanTilt(pan=0.0, tilt=123.4)) == "pan=+0°, tilt=+123°"
    assert HardwareTestRunner._format_precise_position(PanTilt(pan=-0.0, tilt=0.123)) == "pan=+0.000°, tilt=+0.123°"


def test_cli_prints_title_and_connection_status_before_discovery(monkeypatch, capsys):
    def fail_discovery(**_kwargs):
        output = capsys.readouterr().out
        assert output.index("Basic functionality HWIL test") < output.index("Trying to connect...")
        raise OSError("not connected")

    monkeypatch.setattr("anechoic_turntable.hwil.basic.Turntable.find", fail_discovery)

    assert main([]) == 1


def test_trace_continues_after_event_history_reaches_capacity(monkeypatch):
    table = FakeHardwareTurntable()
    initial_event = table._events[-1]
    table._events.extend(initial_event for _ in range(table._events.maxlen - len(table._events)))
    runner = make_runner(
        table,
        [
            "y",  # preflight
            "n",  # reported position is not correct
            "2",
            "-1",
            "y",  # approve centering
            "y",  # centered
            "n",  # stop before the basic movement checks
        ],
        monkeypatch,
    )

    with pytest.raises(OperatorCancelled):
        runner.run()

    trace = runner.report["trace"]
    assert any("ACK   VERSION" in line for line in trace)
    assert any("ACK   SET" in line for line in trace)
    assert any("ACK   MOV" in line for line in trace)
    assert any("POS" in line for line in trace)


def test_position_trace_is_limited_to_about_three_hz_with_three_decimal_places():
    table = FakeHardwareTurntable()
    table._events.clear()
    for milliseconds, pan in ((0, 1.234), (100, 1.5), (340, 2.345), (500, 2.8), (680, 3.456)):
        table._events.append(
            ReceivedMessagePosition(
                message=b"position",
                timestamp=TEST_TIME + datetime.timedelta(milliseconds=milliseconds),
                pan=pan,
                tilt=-0.125,
            )
        )
    runner = HardwareTestRunner(table)

    runner._drain_trace(0, None, target=PanTilt(pan=5.0, tilt=0.0))

    position_lines = [line for line in runner.report["trace"] if " POS " in line]
    assert len(position_lines) == 3
    assert "CURRENT: pan=+1.234°, tilt=-0.125° REMAINING: pan=+3.766°, tilt=+0.125°" in position_lines[0]
    assert "CURRENT: pan=+2.345°, tilt=-0.125° REMAINING: pan=+2.655°, tilt=+0.125°" in position_lines[1]
    assert "CURRENT: pan=+3.456°, tilt=-0.125° REMAINING: pan=+1.544°, tilt=+0.125°" in position_lines[2]


@pytest.mark.parametrize(
    ("axis", "responses", "expected_message"),
    [
        ("pan", ["nan", "0"], "pan must be finite"),
        ("pan", ["181", "0"], "pan must be finite"),
        ("tilt", ["91", "0"], "tilt must be finite"),
    ],
)
def test_centering_rejects_nonfinite_and_out_of_bounds_estimates(axis, responses, expected_message, monkeypatch, capsys):
    table = FakeHardwareTurntable()
    runner = make_runner(table, responses, monkeypatch)

    value = runner._read_coordinate("coordinate: ", axis=axis)

    assert value == 0.0
    assert expected_message in capsys.readouterr().out
