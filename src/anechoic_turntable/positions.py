"""Coordinate types used by the threaded turntable controller."""

from __future__ import annotations

import dataclasses


@dataclasses.dataclass(frozen=True)
class PanTilt:
    """A turntable position in degrees."""

    pan: float
    tilt: float
