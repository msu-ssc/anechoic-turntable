import threading
import time
from dataclasses import FrozenInstanceError

import pytest
from pydantic import ValidationError

import anechoic_turntable as turntable2
from anechoic_turntable.controller import _estimate_axis_time


class FakeSerial:
    def __init__(
        self,
        *,
        respond_to_moves=True,
        respond_to_sets=True,
        acknowledge_commands=True,
        firmware_version="2.0.8",
        counters=(43200, 21600),
    ):
        self.respond_to_moves = respond_to_moves
        self.respond_to_sets = respond_to_sets
        self.acknowledge_commands = acknowledge_commands
        self.firmware_version = firmware_version
        self.counters = counters
        self.writes = []
        self.closed = False
        self._input = bytearray()
        self._lock = threading.Lock()

    @property
    def in_waiting(self):
        with self._lock:
            return len(self._input)

    def read(self, size=1):
        with self._lock:
            data = bytes(self._input[:size])
            del self._input[:size]
            return data

    def write(self, data):
        with self._lock:
            self.writes.append(data)
        command = self._command_name(data)
        if self.acknowledge_commands and command is not None:
            self.emit(f"MSG:ACK:{command};\r\n".encode())
        if data.startswith(b"CMD:SET:") and self.respond_to_sets:
            coordinates = data.removeprefix(b"CMD:SET:").removesuffix(b";")
            yaw, pitch = (float(value) for value in coordinates.split(b","))
            self.emit_internal_position(yaw=yaw, pitch=pitch)
        elif data.startswith(b"CMD:MOV:") and self.respond_to_moves:
            coordinates = data.removeprefix(b"CMD:MOV:").removesuffix(b";")
            yaw, pitch = (float(value) for value in coordinates.split(b","))
            self.emit_internal_position(yaw=yaw, pitch=pitch)
        elif data.startswith(b"CMD:MOV_CNT:PAN=") and self.respond_to_moves:
            values = data.removeprefix(b"CMD:MOV_CNT:PAN=").removesuffix(b";")
            pan, tilt = values.split(b",TILT=")
            yaw = (int(pan) - 43200) / 240
            pitch = (int(tilt) - 21600) / 240
            self.emit_internal_position(yaw=yaw, pitch=pitch)
        elif data == b"CMD:VERSION;" and self.firmware_version is not None:
            self.emit(f"MSG:VERSION:{self.firmware_version};\r\n".encode())
        elif data == b"CMD:CNT;":
            self.emit(f"MSG:CNT:PAN={self.counters[0]},TILT={self.counters[1]};\r\n".encode())
        elif data.startswith(b"CMD:SET_CNT:PAN="):
            values = data.removeprefix(b"CMD:SET_CNT:PAN=").removesuffix(b";")
            pan, tilt = values.split(b",TILT=")
            self.counters = (int(pan), int(tilt))
            self.emit(f"MSG:CNT:PAN={self.counters[0]},TILT={self.counters[1]};\r\n".encode())
        return len(data)

    @staticmethod
    def _command_name(data):
        if data == b"p":
            return "EMERGENCY_STOP"
        for command in ("MOV_CNT", "SET_CNT", "VERSION", "SET", "MOV", "CNT"):
            if data.startswith(f"CMD:{command}".encode()):
                return command
        return None

    def close(self):
        self.closed = True

    def emit(self, message):
        with self._lock:
            self._input.extend(message)

    def emit_internal_position(self, *, yaw, pitch):
        self.emit(f"Pos= El: {pitch:.2f} , Az: {yaw:.2f} \r\n".encode())


def wait_for(predicate, *, timeout=1.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(0.005)
    raise AssertionError("condition was not met before timeout")


def make_turntable(fake, **kwargs):
    return turntable2.Turntable(
        serial_connection=fake,
        poll_interval=0.001,
        communication_timeout=kwargs.pop("communication_timeout", 1.0),
        acknowledgement_timeout=kwargs.pop("acknowledgement_timeout", 0.02),
        **kwargs,
    )


@pytest.mark.parametrize("acknowledgement_timeout", [0, -1, float("inf"), float("nan")])
def test_acknowledgement_timeout_must_be_finite_and_positive(acknowledgement_timeout):
    with pytest.raises(ValueError, match="acknowledgement_timeout"):
        make_turntable(FakeSerial(), acknowledgement_timeout=acknowledgement_timeout)


def test_received_messages_are_immutable_and_hashable():
    event = turntable2.parse_received_message(b"Pos= El: -12.34 , Az: 56.78 \r\n")

    assert isinstance(event, turntable2.ReceivedMessagePosition)
    assert event.kind == "position"
    assert event.yaw == 56.78
    assert event.pitch == -12.34
    assert event.timestamp.tzinfo is not None
    assert hash(event)
    with pytest.raises(ValidationError):
        event.yaw = 0


def test_non_position_input_becomes_an_other_event():
    event = turntable2.parse_received_message(b"garbage\r\n")

    assert type(event) is turntable2.ReceivedMessage
    assert event.kind == "other"
    assert event.message == b"garbage\r\n"


def test_version_response_becomes_a_typed_event():
    event = turntable2.parse_received_message(b"MSG:VERSION:2.0.8;\r\n")

    assert isinstance(event, turntable2.ReceivedMessageVersion)
    assert event.kind == "version"
    assert event.version == "2.0.8"
    assert hash(event)


def test_counter_response_becomes_a_typed_event():
    event = turntable2.parse_received_message(b"MSG:CNT:PAN=12345,TILT=5555;\r\n")

    assert isinstance(event, turntable2.ReceivedMessageCounter)
    assert event.kind == "counter"
    assert event.pan == 12345
    assert event.tilt == 5555
    assert hash(event)


@pytest.mark.parametrize(
    ("message", "status", "command", "reason"),
    [
        (b"MSG:ACK:MOV_CNT;\r\n", "ACK", "MOV_CNT", None),
        (b"MSG:ACK:EMERGENCY_STOP;\r\n", "ACK", "EMERGENCY_STOP", None),
        (b"MSG:NAK:MOV_CNT,UNABLE_TO_PARSE;\r\n", "NAK", "MOV_CNT", "UNABLE_TO_PARSE"),
        (b"MSG:NAK:UNKNOWN,REJECTED;\r\n", "NAK", "UNKNOWN", "REJECTED"),
    ],
)
def test_acknowledgement_becomes_a_typed_event(message, status, command, reason):
    event = turntable2.parse_received_message(message)

    assert isinstance(event, turntable2.ReceivedMessageAcknowledgement)
    assert event.kind == "acknowledgement"
    assert (event.status, event.command, event.reason) == (status, command, reason)
    assert hash(event)


@pytest.mark.parametrize(
    "message",
    [
        b"MSG:ACK:MOV\r\n",
        b"MSG:ACK:MOV;\n",
        b"MSG:ACK:BOGUS;\r\n",
        b"MSG:ACK:UNKNOWN;\r\n",
        b"MSG:ACK:MOV,REJECTED;\r\n",
        b"MSG:NAK:MOV;\r\n",
        b"MSG:NAK:MOV,BOGUS;\r\n",
        b"prefix MSG:ACK:MOV;\r\n",
    ],
)
def test_malformed_acknowledgement_becomes_an_other_event(message):
    assert type(turntable2.parse_received_message(message)) is turntable2.ReceivedMessage


@pytest.mark.parametrize(
    "message",
    [
        b"MSG:CNT:pan=12345,tilt=5555;\r\n",
        b"MSG:CNT:PAN=+1,TILT=2;\r\n",
        b"MSG:CNT:PAN=-1,TILT=2;\r\n",
        b"MSG:CNT:PAN=01,TILT=2;\r\n",
        b"MSG:CNT:PAN=4294967296,TILT=2;\r\n",
        b"MSG:CNT:PAN=1,TILT=2\r\n",
        b"prefix MSG:CNT:PAN=1,TILT=2;\r\n",
        b"MSG:CNT:PAN=1,TILT=2;\n",
    ],
)
def test_malformed_counter_response_becomes_an_other_event(message):
    assert type(turntable2.parse_received_message(message)) is turntable2.ReceivedMessage


@pytest.mark.parametrize(
    "message",
    [
        b"MSG:VERSION:2.0;\r\n",
        b"MSG:VERSION:02.0.8;\r\n",
        b"MSG:VERSION:+2.0.8;\r\n",
        b"MSG:VERSION:2.0.8\r\n",
        b"prefix MSG:VERSION:2.0.8;\r\n",
        b"MSG:VERSION:2.0.8;\n",
    ],
)
def test_malformed_version_response_becomes_an_other_event(message):
    assert type(turntable2.parse_received_message(message)) is turntable2.ReceivedMessage


def test_serial_listener_frames_fragmented_lines():
    fake = FakeSerial()
    turntable = make_turntable(fake)
    try:
        fake.emit(b"junk\r\nPos= El: 1")
        fake.emit(b"2.34 , Az: -5.67 \r\n")

        event = wait_for(lambda: turntable.most_recent_event(kind="position"))

        assert event.yaw == -5.67
        assert event.pitch == 12.34
        assert turntable.most_recent_event(kind="other").message == b"junk\r\n"
    finally:
        turntable.close()


def test_complete_state_includes_five_most_recent_serial_lines():
    fake = FakeSerial()
    turntable = make_turntable(fake)
    try:
        for index in range(1, 7):
            fake.emit(f"diagnostic {index}\r\n".encode())

        wait_for(lambda: turntable.get_complete_state().event_count == 6)

        assert [event.message for event in turntable.get_complete_state().recent_events] == [f"diagnostic {index}\r\n".encode() for index in range(2, 7)]
    finally:
        turntable.close()


def test_set_and_move_are_queued_with_direct_coordinates():
    fake = FakeSerial()
    turntable = make_turntable(fake)
    try:
        fake.emit_internal_position(yaw=4, pitch=2)
        wait_for(lambda: turntable.current_position() is not None)

        assert turntable.current_state() == turntable2.TurntableState.NOT_SET
        turntable.set_position(pan=0, tilt=0)
        turntable.move_to(pan=15, tilt=-40)

        wait_for(lambda: turntable.current_state() == turntable2.TurntableState.STOPPED and turntable.current_position() == turntable2.PanTilt(15, -40))

        assert b"CMD:SET:0.000,0.000;" in fake.writes
        assert b"CMD:MOV:15.000,-40.000;" in fake.writes
        assert not any(write.startswith(b"CMD:SET:") and write != b"CMD:SET:0.000,0.000;" for write in fake.writes)
        assert turntable.most_recent_event(kind="position").pitch == -40
        command_history = turntable.command_history()
        assert [write.command for write in command_history] == fake.writes
        assert all(write.timestamp.tzinfo is not None for write in command_history)
        assert list(command_history) == sorted(
            command_history,
            key=lambda write: write.timestamp,
        )

        complete_state = turntable.get_complete_state()
        assert complete_state.uncorrected_position == turntable2.YawPitch(yaw=15, pitch=-40)
        assert complete_state.corrected_position == turntable2.PanTilt(pan=15, tilt=-40)
        assert complete_state.most_recent_position_event.pitch == -40
        assert complete_state.activity == turntable2.TurntableActivity.IDLE
        assert complete_state.activity_timeout_at is None
        assert complete_state.position_history_count == len(turntable.position_history())
        assert complete_state.position_history_generation == 1
        assert turntable.position_history()[-1] == turntable2.PositionSample(
            timestamp=complete_state.most_recent_position_event.timestamp,
            internal_position=turntable2.YawPitch(yaw=15, pitch=-40),
            corrected_position=turntable2.PanTilt(pan=15, tilt=-40),
        )
        assert all(sample.internal_position.yaw == sample.corrected_position.pan for sample in turntable.position_history())
        assert all(sample.internal_position.pitch == sample.corrected_position.tilt for sample in turntable.position_history())
        assert all(sample.internal_position != turntable2.YawPitch(yaw=4, pitch=2) for sample in turntable.position_history())
    finally:
        turntable.close()


def test_next_command_waits_for_matching_acknowledgement_after_completion():
    fake = FakeSerial(acknowledge_commands=False)
    turntable = make_turntable(fake, acknowledgement_timeout=0.2)
    try:
        turntable.set_position(pan=0, tilt=0)
        turntable.request_version()
        wait_for(lambda: turntable.current_state() == turntable2.TurntableState.STOPPED)

        snapshot = turntable.get_complete_state()
        assert snapshot.pending_acknowledgement_command == "SET"
        assert b"CMD:VERSION;" not in fake.writes

        fake.emit(b"MSG:ACK:SET;\r\n")

        wait_for(lambda: b"CMD:VERSION;" in fake.writes)
    finally:
        turntable.close()


def test_confirm_trusts_the_current_position_without_sending_set():
    fake = FakeSerial()
    turntable = make_turntable(fake)
    try:
        fake.emit_internal_position(yaw=4, pitch=2)
        wait_for(lambda: turntable.current_position() is not None)

        turntable.confirm_position()

        state = turntable.get_complete_state()
        assert state.state == turntable2.TurntableState.STOPPED
        assert state.has_been_set
        assert state.corrected_position == turntable2.PanTilt(4, 2)
        assert not any(command.startswith(b"CMD:SET:") for command in fake.writes)

        turntable.move_to(pan=5, tilt=3)
        wait_for(lambda: b"CMD:MOV:5.000,3.000;" in fake.writes)
    finally:
        turntable.close()


def test_estimate_time_uses_the_slower_concurrent_axis_without_timeout_margin():
    fake = FakeSerial()
    turntable = make_turntable(fake)
    try:
        fake.emit_internal_position(yaw=0, pitch=0)
        wait_for(lambda: turntable.current_position() is not None)

        # Pan estimate: 0.3940 * 10 + 1.2141 = 5.1541 seconds.
        # Tilt estimate: 0.9038 * 5 + 2.0841 = 6.6031 seconds.
        assert turntable.estimate_time(pan=10, tilt=5) == pytest.approx(6.6031)
    finally:
        turntable.close()


def test_estimate_time_requires_a_current_position():
    fake = FakeSerial()
    turntable = make_turntable(fake)
    try:
        with pytest.raises(turntable2.TurntableError, match="current position report"):
            turntable.estimate_time(pan=10, tilt=5)
    finally:
        turntable.close()


def test_axis_time_estimate_rejects_an_invalid_axis():
    with pytest.raises(ValueError, match="Invalid axis: 'roll'"):
        _estimate_axis_time(10, axis="roll")  # type: ignore[arg-type]


def test_default_move_timeout_uses_estimate_with_safety_margin():
    fake = FakeSerial(respond_to_moves=False)
    turntable = make_turntable(fake)
    try:
        turntable.set_position(pan=-180, tilt=0)
        wait_for(lambda: turntable.current_state() == turntable2.TurntableState.STOPPED)

        estimated_time = turntable.estimate_time(pan=180, tilt=0)
        assert estimated_time == pytest.approx(143.0541)

        turntable.move_to(pan=180, tilt=0)
        wait_for(lambda: turntable.current_state() == turntable2.TurntableState.MOVING)
        state = turntable.get_complete_state()
        actual_timeout = (state.activity_timeout_at - state.captured_at).total_seconds()

        assert actual_timeout == pytest.approx(estimated_time * 1.5 + 5, abs=0.1)
        assert actual_timeout > 120
    finally:
        turntable.close()


def test_queued_move_estimates_timeout_from_position_when_it_starts():
    fake = FakeSerial(respond_to_moves=False)
    turntable = make_turntable(fake)
    try:
        turntable.set_position(pan=0, tilt=0)
        wait_for(lambda: turntable.current_state() == turntable2.TurntableState.STOPPED)

        turntable.move_to(pan=180, tilt=0)
        turntable.move_to(pan=-180, tilt=0)
        wait_for(lambda: b"CMD:MOV:180.000,0.000;" in fake.writes)

        fake.emit_internal_position(yaw=180, pitch=0)
        wait_for(lambda: b"CMD:MOV:-180.000,0.000;" in fake.writes)
        state = turntable.get_complete_state()
        actual_timeout = (state.activity_timeout_at - state.captured_at).total_seconds()
        expected_timeout = (0.3940 * 360 + 1.2141) * 1.5 + 5

        assert actual_timeout == pytest.approx(expected_timeout, abs=0.1)
    finally:
        turntable.close()


def test_complete_state_describes_active_move_and_timeout():
    fake = FakeSerial(respond_to_moves=False)
    turntable = make_turntable(fake)
    try:
        fake.emit_internal_position(yaw=0, pitch=0)
        turntable.set_position(pan=0, tilt=0)
        wait_for(lambda: turntable.current_state() == turntable2.TurntableState.STOPPED)

        turntable.move_to(pan=10, tilt=5, move_timeout=10)
        wait_for(lambda: turntable.current_state() == turntable2.TurntableState.MOVING)
        complete_state = turntable.get_complete_state()

        assert complete_state.state == turntable2.TurntableState.MOVING
        assert complete_state.activity == turntable2.TurntableActivity.MOVING
        assert complete_state.activity_phase == "direct"
        assert complete_state.uncorrected_position == turntable2.YawPitch(yaw=0, pitch=0)
        assert complete_state.corrected_position == turntable2.PanTilt(pan=0, tilt=0)
        assert complete_state.most_recent_position_event.yaw == 0
        assert complete_state.most_recent_position_event.pitch == 0
        assert complete_state.activity_timeout_at.tzinfo is not None
        assert complete_state.activity_timeout_at > complete_state.captured_at
        assert complete_state.communication_timeout == 1.0
        assert complete_state.target_position == turntable2.PanTilt(pan=10, tilt=5)
        assert complete_state.internal_target == turntable2.YawPitch(yaw=10, pitch=5)
        assert complete_state.queued_command_count == 0
        assert complete_state.has_been_set
        assert not complete_state.set_requested
        assert complete_state.last_error is None
        assert complete_state.event_count >= 1
        with pytest.raises(FrozenInstanceError):
            complete_state.state = turntable2.TurntableState.STOPPED
    finally:
        turntable.close()


def test_move_does_not_send_intermediate_move_or_set_commands():
    fake = FakeSerial(respond_to_moves=False)
    turntable = make_turntable(fake)
    try:
        fake.emit_internal_position(yaw=0, pitch=0)
        turntable.set_position(pan=0, tilt=0)
        wait_for(lambda: turntable.current_state() == turntable2.TurntableState.STOPPED)

        writes_before_move = len(fake.writes)
        turntable.move_to(pan=15, tilt=-40)
        wait_for(lambda: b"CMD:MOV:15.000,-40.000;" in fake.writes)

        complete_state = turntable.get_complete_state()
        assert complete_state.target_position == turntable2.PanTilt(pan=15, tilt=-40)
        assert complete_state.internal_target == turntable2.YawPitch(yaw=15, pitch=-40)
        assert fake.writes[writes_before_move:] == [b"CMD:MOV:15.000,-40.000;"]
    finally:
        turntable.close()


@pytest.mark.parametrize(
    "destination",
    [-90, 45],
)
def test_move_uses_direct_coordinates_across_full_elevation_range(destination):
    fake = FakeSerial()
    turntable = make_turntable(fake)
    try:
        fake.emit_internal_position(yaw=0, pitch=0)
        turntable.set_position(pan=0, tilt=0)
        turntable.move_to(pan=12, tilt=destination)

        wait_for(lambda: turntable.current_state() == turntable2.TurntableState.STOPPED and turntable.current_position() == turntable2.PanTilt(12, destination))

        expected_command = f"CMD:MOV:12.000,{destination:.3f};".encode()
        assert expected_command in fake.writes
    finally:
        turntable.close()


def test_move_requires_set_and_valid_physical_bounds():
    fake = FakeSerial()
    turntable = make_turntable(fake)
    try:
        with pytest.raises(turntable2.TurntableError, match="must be set"):
            turntable.move_to(pan=0, tilt=0)
        turntable.set_position(pan=0, tilt=0)
        with pytest.raises(ValueError, match="pan"):
            turntable.move_to(pan=181, tilt=0)
        with pytest.raises(ValueError, match="tilt"):
            turntable.move_to(pan=0, tilt=46)
    finally:
        turntable.close()


def test_nonzero_set_position_is_accepted_and_applied():
    fake = FakeSerial()
    turntable = make_turntable(fake)
    try:
        turntable.set_position(pan=20, tilt=10)
        wait_for(lambda: turntable.current_state() == turntable2.TurntableState.STOPPED)

        assert b"CMD:SET:20.000,10.000;" in fake.writes
        state = turntable.get_complete_state()
        assert state.corrected_position == turntable2.PanTilt(20, 10)
    finally:
        turntable.close()


@pytest.mark.parametrize(
    ("pan", "tilt"),
    [
        (-180, -90),
        (180, 90),
    ],
)
def test_set_position_accepts_inclusive_boundaries(pan, tilt):
    fake = FakeSerial()
    turntable = make_turntable(fake)
    try:
        turntable.set_position(pan=pan, tilt=tilt)
        wait_for(lambda: turntable.current_state() == turntable2.TurntableState.STOPPED)
        assert turntable.current_position() == turntable2.PanTilt(pan, tilt)
    finally:
        turntable.close()


@pytest.mark.parametrize(
    ("pan", "tilt", "message"),
    [
        (-180.001, 0, "pan"),
        (180.001, 0, "pan"),
        (0, -90.001, "tilt"),
        (0, 90.001, "tilt"),
        (float("nan"), 0, "pan"),
        (0, float("inf"), "tilt"),
    ],
)
def test_invalid_set_position_is_rejected_without_a_write(pan, tilt, message):
    fake = FakeSerial()
    turntable = make_turntable(fake)
    try:
        with pytest.raises(ValueError, match=message):
            turntable.set_position(pan=pan, tilt=tilt)
        assert fake.writes == []
    finally:
        turntable.close()


def test_complete_state_describes_active_nonzero_set():
    fake = FakeSerial(respond_to_sets=False)
    turntable = make_turntable(fake)
    try:
        turntable.set_position(pan=20, tilt=10, timeout=10)
        wait_for(lambda: turntable.get_complete_state().activity == turntable2.TurntableActivity.SETTING_POSITION)

        state = turntable.get_complete_state()
        assert state.target_position == turntable2.PanTilt(20, 10)
        assert state.internal_target == turntable2.YawPitch(20, 10)
    finally:
        turntable.close()


def test_abort_stops_the_active_move_and_cancels_queued_moves():
    fake = FakeSerial(respond_to_moves=False)
    turntable = make_turntable(fake)
    try:
        fake.emit_internal_position(yaw=0, pitch=0)
        turntable.set_position(pan=0, tilt=0)
        wait_for(lambda: turntable.current_state() == turntable2.TurntableState.STOPPED)
        turntable.move_to(pan=10, tilt=0)
        turntable.move_to(pan=20, tilt=0)
        wait_for(lambda: turntable.current_state() == turntable2.TurntableState.MOVING)
        writes_before_abort = len(fake.writes)

        turntable.abort()

        # ABORT bypasses the queue and performs the stop write before returning.
        assert fake.writes[writes_before_abort:] == [b"p"] * 5
        assert turntable.command_history()[-1].command == b"p"
        assert turntable.current_state() == turntable2.TurntableState.STOPPED
        acknowledgement = wait_for(lambda: event if (event := turntable.most_recent_event(kind="acknowledgement")) is not None and event.command == "EMERGENCY_STOP" else None)
        assert acknowledgement.status == "ACK"
        time.sleep(0.03)
        assert b"CMD:MOV:20.000,0.000;" not in fake.writes
    finally:
        turntable.close()


def test_abort_uses_custom_repeat_count():
    fake = FakeSerial()
    turntable = make_turntable(fake)
    try:
        turntable.abort(repeat_count=2)

        assert fake.writes == [b"p", b"p"]
        assert [write.command for write in turntable.command_history()] == [b"p", b"p"]
    finally:
        turntable.close()


@pytest.mark.parametrize("repeat_count", [0, -1, 1.5, True])
def test_abort_rejects_invalid_repeat_count_without_writing(repeat_count):
    fake = FakeSerial()
    turntable = make_turntable(fake)
    try:
        with pytest.raises(ValueError, match="repeat_count"):
            turntable.abort(repeat_count=repeat_count)

        assert fake.writes == []
    finally:
        turntable.close()


def test_abort_repeat_count_is_keyword_only():
    fake = FakeSerial()
    turntable = make_turntable(fake)
    try:
        with pytest.raises(TypeError):
            turntable.abort(2)  # type: ignore[misc]

        assert fake.writes == []
    finally:
        turntable.close()


def test_raw_command_is_written_once_without_coordinate_validation():
    fake = FakeSerial(respond_to_moves=False)
    turntable = make_turntable(fake)
    try:
        fake.emit_internal_position(yaw=0, pitch=0)
        turntable.set_position(pan=0, tilt=0)
        wait_for(lambda: turntable.current_state() == turntable2.TurntableState.STOPPED)
        writes_before_raw = len(fake.writes)

        turntable.send_raw(b"CMD:MOV:0.000,-70.00;")

        wait_for(lambda: len(fake.writes) > writes_before_raw)
        assert fake.writes[writes_before_raw:] == [b"CMD:MOV:0.000,-70.00;"]
        assert turntable.command_history()[-1].command == b"CMD:MOV:0.000,-70.00;"
        state = turntable.get_complete_state()
        assert state.state == turntable2.TurntableState.NOT_SET
        assert not state.has_been_set
        assert state.corrected_position is None
        assert state.position_history_generation == 2
    finally:
        turntable.close()


def test_version_request_is_written_once_and_preserves_trusted_position():
    fake = FakeSerial()
    turntable = make_turntable(fake)
    try:
        fake.emit_internal_position(yaw=0, pitch=0)
        turntable.set_position(pan=0, tilt=0)
        wait_for(lambda: turntable.current_state() == turntable2.TurntableState.STOPPED)
        writes_before_request = len(fake.writes)

        turntable.request_version()

        event = wait_for(lambda: turntable.most_recent_event(kind="version"))
        assert isinstance(event, turntable2.ReceivedMessageVersion)
        assert event.version == "2.0.8"
        assert fake.writes[writes_before_request:] == [b"CMD:VERSION;"]
        state = turntable.get_complete_state()
        assert state.state == turntable2.TurntableState.STOPPED
        assert state.has_been_set
        assert state.corrected_position == turntable2.PanTilt(0, 0)
    finally:
        turntable.close()


def test_counter_request_is_written_once_and_preserves_trusted_position():
    fake = FakeSerial(counters=(12345, 5555))
    turntable = make_turntable(fake)
    try:
        fake.emit_internal_position(yaw=0, pitch=0)
        turntable.set_position(pan=0, tilt=0)
        wait_for(lambda: turntable.current_state() == turntable2.TurntableState.STOPPED)
        writes_before_request = len(fake.writes)

        turntable.request_counters()

        event = wait_for(lambda: turntable.most_recent_event(kind="counter"))
        assert isinstance(event, turntable2.ReceivedMessageCounter)
        assert (event.pan, event.tilt) == (12345, 5555)
        assert fake.writes[writes_before_request:] == [b"CMD:CNT;"]
        state = turntable.get_complete_state()
        assert state.has_been_set
        assert state.corrected_position == turntable2.PanTilt(0, 0)
    finally:
        turntable.close()


def test_counter_set_is_written_once_and_invalidates_trusted_position():
    fake = FakeSerial()
    turntable = make_turntable(fake)
    try:
        fake.emit_internal_position(yaw=0, pitch=0)
        turntable.set_position(pan=0, tilt=0)
        wait_for(lambda: turntable.current_state() == turntable2.TurntableState.STOPPED)
        writes_before_set = len(fake.writes)

        turntable.set_counters(pan=12345, tilt=5555)

        event = wait_for(lambda: turntable.most_recent_event(kind="counter"))
        assert (event.pan, event.tilt) == (12345, 5555)
        assert fake.writes[writes_before_set:] == [b"CMD:SET_CNT:PAN=12345,TILT=5555;"]
        state = turntable.get_complete_state()
        assert state.state == turntable2.TurntableState.NOT_SET
        assert not state.has_been_set
        assert state.corrected_position is None
        with pytest.raises(turntable2.TurntableError, match="must be set"):
            turntable.move_to(pan=0, tilt=0)
    finally:
        turntable.close()


@pytest.mark.parametrize("pan, tilt", [(-1, 0), (0, -1), (2**32, 0), (0, 2**32), (1.5, 0)])
def test_counter_set_rejects_values_outside_uint32(pan, tilt):
    fake = FakeSerial()
    turntable = make_turntable(fake)
    try:
        with pytest.raises(ValueError, match="counter"):
            turntable.set_counters(pan=pan, tilt=tilt)
        assert fake.writes == []
    finally:
        turntable.close()


def test_counter_set_waits_behind_an_active_move():
    fake = FakeSerial(respond_to_moves=False)
    turntable = make_turntable(fake)
    try:
        fake.emit_internal_position(yaw=0, pitch=0)
        turntable.set_position(pan=0, tilt=0)
        wait_for(lambda: turntable.current_state() == turntable2.TurntableState.STOPPED)
        turntable.move_to(pan=10, tilt=0)
        wait_for(lambda: b"CMD:MOV:10.000,0.000;" in fake.writes)

        turntable.set_counters(pan=12345, tilt=5555)
        time.sleep(0.03)
        assert b"CMD:SET_CNT:PAN=12345,TILT=5555;" not in fake.writes

        fake.emit_internal_position(yaw=10, pitch=0)
        wait_for(lambda: b"CMD:SET_CNT:PAN=12345,TILT=5555;" in fake.writes)
    finally:
        turntable.close()


def test_counter_move_is_sent_once_after_ack_and_tracks_translated_target():
    fake = FakeSerial()
    turntable = make_turntable(fake)
    try:
        fake.emit_internal_position(yaw=0, pitch=0)
        wait_for(lambda: turntable.current_position() is not None)
        writes_before_move = len(fake.writes)

        turntable.move_to_counters(pan=45_600, tilt=20_400)

        wait_for(lambda: len(fake.writes) >= writes_before_move + 1)
        assert fake.writes[writes_before_move:] == [b"CMD:MOV_CNT:PAN=45600,TILT=20400;"]
        wait_for(lambda: turntable.current_state() == turntable2.TurntableState.NOT_SET)
        assert turntable.current_position() == turntable2.PanTilt(10, -5)
        assert not turntable.get_complete_state().has_been_set
    finally:
        turntable.close()


def test_counter_move_uses_300_second_default_timeout():
    fake = FakeSerial(respond_to_moves=False)
    turntable = make_turntable(fake)
    try:
        fake.emit_internal_position(yaw=0, pitch=0)
        wait_for(lambda: turntable.current_position() is not None)

        turntable.move_to_counters(pan=45_600, tilt=20_400)

        snapshot = wait_for(lambda: state if (state := turntable.get_complete_state()).activity_phase == "counter" else None)
        remaining = (snapshot.activity_timeout_at - snapshot.captured_at).total_seconds()
        assert remaining == pytest.approx(300, abs=1)
        assert snapshot.internal_target == turntable2.YawPitch(10, -5)
    finally:
        turntable.close()


def test_command_is_retried_only_while_acknowledgement_is_missing():
    fake = FakeSerial(respond_to_moves=False)
    turntable = make_turntable(fake, command_repetitions=3)
    try:
        fake.emit_internal_position(yaw=0, pitch=0)
        turntable.set_position(pan=0, tilt=0)
        wait_for(lambda: turntable.current_state() == turntable2.TurntableState.STOPPED)
        fake.acknowledge_commands = False
        writes_before_move = len(fake.writes)

        turntable.move_to(pan=10, tilt=0, move_timeout=1)

        wait_for(lambda: turntable.current_state() == turntable2.TurntableState.ERROR)
        move_frame = b"CMD:MOV:10.000,0.000;"
        assert fake.writes[writes_before_move:].count(move_frame) == 3
        assert fake.writes[writes_before_move:].count(b"p") == 5
        assert isinstance(turntable.last_error(), TimeoutError)
        assert "No acknowledgement received for MOV" in str(turntable.last_error())
    finally:
        turntable.close()


def test_matching_nak_fails_move_without_retry_and_stops_motion():
    fake = FakeSerial(respond_to_moves=False)
    turntable = make_turntable(fake, command_repetitions=3)
    try:
        fake.emit_internal_position(yaw=0, pitch=0)
        turntable.set_position(pan=0, tilt=0)
        wait_for(lambda: turntable.current_state() == turntable2.TurntableState.STOPPED)
        fake.acknowledge_commands = False
        writes_before_move = len(fake.writes)

        turntable.move_to(pan=10, tilt=0, move_timeout=1)
        wait_for(lambda: b"CMD:MOV:10.000,0.000;" in fake.writes)
        fake.emit(b"MSG:NAK:MOV,REJECTED;\r\n")

        wait_for(lambda: turntable.current_state() == turntable2.TurntableState.ERROR)
        assert fake.writes[writes_before_move:] == [b"CMD:MOV:10.000,0.000;", *([b"p"] * 5)]
        assert "Firmware rejected MOV: REJECTED" in str(turntable.last_error())
        event = turntable.most_recent_event(kind="acknowledgement")
        assert event.status == "NAK"
    finally:
        turntable.close()


def test_unmatched_acknowledgement_does_not_release_pending_command():
    fake = FakeSerial(respond_to_moves=False, acknowledge_commands=False)
    turntable = make_turntable(fake, command_repetitions=2)
    try:
        fake.emit_internal_position(yaw=0, pitch=0)
        turntable.set_position(pan=0, tilt=0, timeout=1)
        wait_for(lambda: b"CMD:SET:0.000,0.000;" in fake.writes)
        fake.emit(b"MSG:ACK:MOV;\r\n")

        wait_for(lambda: turntable.current_state() == turntable2.TurntableState.ERROR)
        assert fake.writes.count(b"CMD:SET:0.000,0.000;") == 2
        assert "No acknowledgement received for SET" in str(turntable.last_error())
    finally:
        turntable.close()


@pytest.mark.parametrize("pan, tilt", [(-1, 0), (0, -1), (2**32, 0), (0, 2**32), (True, 0)])
def test_counter_move_rejects_values_outside_uint32(pan, tilt):
    fake = FakeSerial()
    turntable = make_turntable(fake)
    try:
        with pytest.raises(ValueError, match="counter"):
            turntable.move_to_counters(pan=pan, tilt=tilt)
        assert fake.writes == []
    finally:
        turntable.close()


def test_raw_command_waits_behind_a_tracked_move():
    fake = FakeSerial(respond_to_moves=False)
    turntable = make_turntable(fake)
    try:
        fake.emit_internal_position(yaw=0, pitch=0)
        turntable.set_position(pan=0, tilt=0)
        wait_for(lambda: turntable.current_state() == turntable2.TurntableState.STOPPED)
        turntable.move_to(pan=10, tilt=0)
        wait_for(lambda: b"CMD:MOV:10.000,0.000;" in fake.writes)

        turntable.send_raw(b"diagnostic;")
        time.sleep(0.03)
        assert b"diagnostic;" not in fake.writes

        fake.emit_internal_position(yaw=10, pitch=0)
        wait_for(lambda: b"diagnostic;" in fake.writes)
    finally:
        turntable.close()


def test_move_timeout_aborts_and_is_observable():
    fake = FakeSerial(respond_to_moves=False)
    turntable = make_turntable(fake, communication_timeout=1.0)
    try:
        fake.emit_internal_position(yaw=0, pitch=0)
        turntable.set_position(pan=0, tilt=0)
        wait_for(lambda: turntable.current_state() == turntable2.TurntableState.STOPPED)

        turntable.move_to(pan=10, tilt=0, move_timeout=0.03)

        wait_for(lambda: turntable.current_state() == turntable2.TurntableState.TIMED_OUT)
        assert isinstance(turntable.last_error(), TimeoutError)
        assert fake.writes.count(b"p") == 5
    finally:
        turntable.close()


def test_set_timeout_cancels_a_move_queued_behind_it():
    fake = FakeSerial(respond_to_moves=False)

    def ignore_commands(data):
        with fake._lock:
            fake.writes.append(data)
        return len(data)

    fake.write = ignore_commands
    turntable = make_turntable(fake, communication_timeout=1.0)
    try:
        fake.emit_internal_position(yaw=5, pitch=5)
        wait_for(lambda: turntable.current_position() is not None)
        turntable.set_position(pan=0, tilt=0, timeout=0.03)
        turntable.move_to(pan=10, tilt=0)

        wait_for(lambda: turntable.current_state() == turntable2.TurntableState.TIMED_OUT)

        assert not any(command.startswith(b"CMD:MOV:") for command in fake.writes)
    finally:
        turntable.close()


def test_communication_timeout_resets_controller_to_not_set():
    fake = FakeSerial()
    turntable = make_turntable(fake, communication_timeout=0.03)
    try:
        fake.emit_internal_position(yaw=0, pitch=0)
        turntable.set_position(pan=0, tilt=0)
        wait_for(lambda: turntable.current_state() == turntable2.TurntableState.STOPPED)

        wait_for(lambda: turntable.current_state() == turntable2.TurntableState.NO_COMMUNICATION)
        with pytest.raises(turntable2.TurntableError, match="must be set"):
            turntable.move_to(pan=0, tilt=0)

        fake.emit_internal_position(yaw=0, pitch=0)
        wait_for(lambda: turntable.current_state() == turntable2.TurntableState.NOT_SET)
    finally:
        turntable.close()


def test_communication_loss_during_move_sends_default_stop_repetitions():
    fake = FakeSerial(respond_to_moves=False)
    turntable = make_turntable(fake, communication_timeout=0.05)
    try:
        fake.emit_internal_position(yaw=0, pitch=0)
        turntable.set_position(pan=0, tilt=0)
        wait_for(lambda: turntable.current_state() == turntable2.TurntableState.STOPPED)

        turntable.move_to(pan=10, tilt=0, move_timeout=1)

        wait_for(lambda: turntable.current_state() == turntable2.TurntableState.NO_COMMUNICATION)
        assert fake.writes.count(b"p") == 5
    finally:
        turntable.close()


def test_close_stops_threads_and_closes_serial_connection():
    fake = FakeSerial()
    turntable = make_turntable(fake)

    turntable.close()

    assert fake.closed
    assert turntable.current_state() == turntable2.TurntableState.CLOSED
    turntable.close()
