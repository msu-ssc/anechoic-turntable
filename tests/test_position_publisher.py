import datetime
import threading

import pytest

from anechoic_turntable.position_publisher import PositionPublisher
from anechoic_turntable.position_publisher import PositionUpdate
from anechoic_turntable.position_publisher import _format_position_update


def test_position_update_format_matches_the_public_json_shape():
    update = PositionUpdate(
        timestamp=datetime.datetime(2027, 1, 1, tzinfo=datetime.timezone.utc),
        state="moving",
        pan=123.456,
        tilt=-87.654,
    )

    assert _format_position_update(update) == b'{"timestamp":"2027-01-01T00:00:00.000000+00:00","state":"moving","pan":123.456,"tilt":-87.654}'


@pytest.mark.parametrize(
    "kwargs, message",
    [
        ({"host": ""}, "publish_host"),
        ({"port": 0}, "publish_port"),
        ({"port": 65_536}, "publish_port"),
        ({"port": True}, "publish_port"),
    ],
)
def test_position_publisher_rejects_invalid_endpoints(kwargs, message):
    with pytest.raises(ValueError, match=message):
        PositionPublisher(**kwargs)


def test_position_publisher_binds_and_sends_on_its_background_thread(monkeypatch):
    sent = []
    bound = []
    send_thread_names = []

    class FakeSocket:
        def setsockopt(self, option, value):
            pass

        def bind(self, endpoint):
            bound.append(endpoint)

        def send(self, payload, *, flags):
            sent.append(payload)
            send_thread_names.append(threading.current_thread().name)

        def close(self):
            pass

    class FakeContext:
        def socket(self, socket_type):
            return FakeSocket()

        def term(self):
            pass

    monkeypatch.setattr("anechoic_turntable.position_publisher.zmq.Context", FakeContext)
    publisher = PositionPublisher(host="127.0.0.1", port=9_876)
    publisher.publish(
        timestamp=datetime.datetime(2027, 1, 1, tzinfo=datetime.timezone.utc),
        state="stopped",
        pan=1.25,
        tilt=-2.5,
    )

    publisher.start()
    publisher.stop()
    publisher.join(timeout=1)

    assert not publisher.is_alive()
    assert bound == ["tcp://127.0.0.1:9876"]
    assert sent == [b'{"timestamp":"2027-01-01T00:00:00.000000+00:00","state":"stopped","pan":1.25,"tilt":-2.5}']
    assert send_thread_names == ["turntable-position-publisher"]
