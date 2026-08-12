# Travel-time estimates

`Turntable.estimate_time(pan=..., tilt=...)` estimates how many seconds a move
will take from the most recently reported physical position. A current position
report is required. The estimate does not command movement and does not include
a timeout safety margin.

The package-level `estimate_movement_time()` function applies the same model
between any two positions without requiring a `Turntable` instance or current
position report. It accepts either `current=PanTilt(...)` and
`target=PanTilt(...)`, or the four scalar arguments `current_pan`,
`current_tilt`, `target_pan`, and `target_tilt`.

For an absolute axis change `d` in degrees, the controller uses these empirical
curves:

| Axis | `d < 2°` | `d >= 2°` |
| --- | --- | --- |
| Pan | `0.5713 + 1.0117 * sqrt(d)` | `0.3940 * d + 1.2141` |
| Tilt | `-0.1949 + 2.8896 * sqrt(d)` | `0.9038 * d + 2.0841` |

The curves account for acceleration and deceleration and assume each axis
starts and ends at rest. They were derived from measurements documented in
[msu-ssc/lems-anechoic issue #35](https://github.com/msu-ssc/lems-anechoic/issues/35).

Pan and tilt move concurrently, so the move estimate is the larger of the two
axis estimates, not their sum. When `move_to()` has no explicit `move_timeout`,
the controller calculates its deadline when the queued move starts:

```text
timeout = estimate_time * 1.5 + 5 seconds
```

The multiplier and fixed margin tolerate normal variation; they are not a
guarantee of hardware travel time. A caller may supply a positive explicit
timeout when a different operational margin is required.
