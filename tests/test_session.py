import threading

from anechoic_turntable.session import TurntableSession


class FakeTurntable:
    port = "/dev/fake0"

    def __init__(self):
        self.aborted = False
        self.closed = False
        self.raw_writes = []

    def abort(self):
        self.aborted = True

    def close(self):
        self.closed = True

    def send_raw(self, payload):
        self.raw_writes.append(payload)


def test_connection_finishing_after_close_is_stopped_and_discarded():
    discovery_started = threading.Event()
    finish_discovery = threading.Event()
    table = FakeTurntable()
    results = []

    def connector():
        discovery_started.set()
        assert finish_discovery.wait(timeout=1)
        return table

    session = TurntableSession(connector=connector)
    connection_thread = threading.Thread(target=lambda: results.append(session.connect()))
    connection_thread.start()
    assert discovery_started.wait(timeout=1)

    session.close()
    finish_discovery.set()
    connection_thread.join(timeout=1)

    assert not connection_thread.is_alive()
    assert results[0].error is not None
    assert not session.connected
    assert table.aborted
    assert table.closed


def test_session_sends_exact_ascii_and_stops_connected_turntable():
    table = FakeTurntable()
    session = TurntableSession(connector=lambda: table)
    assert session.connect().connected

    session.send_raw("CMD:MOV:0.000,-70.00;")
    session.stop()

    assert table.raw_writes == [b"CMD:MOV:0.000,-70.00;"]
    assert table.aborted


def test_session_raw_rejects_non_ascii():
    table = FakeTurntable()
    session = TurntableSession(connector=lambda: table)
    assert session.connect().connected

    try:
        session.send_raw("CMD:MOV:0,−70;")
    except ValueError as exc:
        assert str(exc) == "raw command must contain only ASCII characters"
    else:
        raise AssertionError("non-ASCII raw command was accepted")

    assert table.raw_writes == []
