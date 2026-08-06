"""Messages received from the turntable."""

from __future__ import annotations

import datetime
import re
from typing import Literal

from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field

_POSITION_PATTERN = re.compile(rb"Pos= El: (?P<pitch>-?\d{1,3}\.\d{2}) , Az: (?P<yaw>-?\d{1,3}\.\d{2})")
_VERSION_PATTERN = re.compile(rb"MSG:VERSION:(?P<version>(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*));\r\n\Z")
_COUNTER_PATTERN = re.compile(rb"MSG:CNT:PAN=(?P<pan>0|[1-9]\d*),TILT=(?P<tilt>0|[1-9]\d*);\r\n\Z")
_UINT32_MAX = 2**32 - 1


def _utc_now() -> datetime.datetime:
    return datetime.datetime.now(tz=datetime.timezone.utc)


class ReceivedMessage(BaseModel):
    """An immutable line received from the turntable."""

    model_config = ConfigDict(frozen=True)

    kind: Literal["position", "version", "counter", "other"] = "other"
    message: bytes
    timestamp: datetime.datetime = Field(default_factory=_utc_now)


class ReceivedMessagePosition(ReceivedMessage):
    """A raw position report containing the firmware's relative coordinates.

    The firmware labels these values ``Az`` and ``El`` on the wire. Within
    ``turntable2`` they are called yaw and pitch to distinguish them from the
    physical pan and tilt used by the public API.
    """

    kind: Literal["position"] = "position"
    yaw: float | None = None
    pitch: float | None = None


class ReceivedMessageVersion(ReceivedMessage):
    """A firmware semantic-version response."""

    kind: Literal["version"] = "version"
    version: str


class ReceivedMessageCounter(ReceivedMessage):
    """A firmware encoder-counter response."""

    kind: Literal["counter"] = "counter"
    pan: int
    tilt: int


def parse_received_message(
    message: bytes,
    *,
    timestamp: datetime.datetime | None = None,
) -> ReceivedMessage:
    """Parse one wire message into the smallest useful event."""

    timestamp = timestamp or _utc_now()
    version_match = _VERSION_PATTERN.fullmatch(message)
    if version_match is not None:
        return ReceivedMessageVersion(
            message=message,
            timestamp=timestamp,
            version=version_match.group("version").decode("ascii"),
        )

    counter_match = _COUNTER_PATTERN.fullmatch(message)
    if counter_match is not None:
        pan = int(counter_match.group("pan"))
        tilt = int(counter_match.group("tilt"))
        if pan <= _UINT32_MAX and tilt <= _UINT32_MAX:
            return ReceivedMessageCounter(
                message=message,
                timestamp=timestamp,
                pan=pan,
                tilt=tilt,
            )

    match = _POSITION_PATTERN.search(message)
    if match is None:
        return ReceivedMessage(message=message, timestamp=timestamp)

    try:
        yaw = float(match.group("yaw"))
        pitch = float(match.group("pitch"))
    except (TypeError, ValueError):
        return ReceivedMessage(message=message, timestamp=timestamp)

    return ReceivedMessagePosition(
        message=message,
        timestamp=timestamp,
        yaw=yaw,
        pitch=pitch,
    )
