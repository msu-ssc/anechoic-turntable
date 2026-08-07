# Threaded Turntable Controller

`anechoic_turntable` is the non-blocking turntable interface. It uses one
thread to frame incoming serial messages and a second thread to maintain
controller state and send commands.

```python
import time

import anechoic_turntable as turntable2


with turntable2.find() as turntable:
    turntable.set_position(pan=0, tilt=0)
    turntable.move_to(pan=30, tilt=10)

    while turntable.current_state() != turntable2.TurntableState.STOPPED:
        snapshot = turntable.get_complete_state()
        event = snapshot.most_recent_position_event
        position = snapshot.corrected_position
        if event is not None and position is not None:
            print(f"{event.timestamp}, yaw={event.yaw}, pitch={event.pitch}, pan={position.pan}, tilt={position.tilt}")
        time.sleep(0.5)

    print(f"Finished moving. Final position = {turntable.current_position()}")
```

## Version metadata

The package exports `CONTROLLER_VERSION`, `PROTOCOL_VERSION`, and
`REFERENCE_FIRMWARE_VERSION`. The latter two are snapshots of the canonical
protocol contract and repository firmware version when the controller release
was made; they do not report the firmware actually installed on a connected
turntable. `__version__` is an alias for `CONTROLLER_VERSION` and matches the
installed Python distribution version.

`request_version()` queues `CMD:VERSION;` and returns immediately without
changing trusted position state. The corresponding exact firmware response is
available as `most_recent_event(kind="version")`, a
`ReceivedMessageVersion` whose `version` field contains the semantic version.
Version responses do not count as position communication for timeout purposes.

`request_counters()` queues `CMD:CNT;` without changing trusted position
state. `set_counters(pan=..., tilt=...)` accepts unsigned 32-bit integer encoder
counts and queues the corresponding SET_CNT frame. Exact responses are
available as `most_recent_event(kind="counter")`, a
`ReceivedMessageCounter` whose `pan` and `tilt` fields contain the raw counter
values read back by firmware. Counter responses do not count as position
communication for timeout purposes.

Directly setting encoder counters changes the firmware coordinate frame and
stops firmware motion. The controller therefore clears its trusted physical
position as it attempts the write. A subsequent normal move requires
`set_position()` or `confirm_position()` first. Counter operations use the
normal serialized command queue and wait behind an active SET, MOV, or MOV_CNT.

`move_to_counters(pan=..., tilt=..., move_timeout=300.0)` queues a tracked
MOV_CNT operation using unsigned 32-bit encoder-counter targets. The controller
sends the frame once and retries only if its acknowledgement is missing.
Firmware converts the targets to degrees
using pan zero `43200`, tilt zero `21600`, and `240` counts per degree, then
uses its normal MOV logic. The controller tracks the same converted target and
sends the immediate stop byte if the operation exceeds its timeout or loses
communication. MOV_CNT does not establish a trusted physical coordinate frame;
if position was not trusted before the operation, it remains untrusted after
completion. Counter targets bypass the physical bounds enforced by `move_to`,
so diagnostic operators must ensure targets are reachable and mechanically
safe.

`set_position` and `move_to` queue work and return immediately. Commands are
processed in order. `move_to` sends physical pan and tilt directly as firmware
yaw and pitch. By default, its timeout is calculated when the queued move
starts, so earlier queued moves are reflected in the starting position.
Every protocol command is written once, then the controller waits up to 0.25
seconds for its matching ACK or NAK. A missing acknowledgement is retried up to
three total attempts by default. A NAK, or exhaustion of those attempts, clears
queued work and enters `ERROR`; uncertain movement is stopped immediately.
`abort(*, repeat_count=5)` is the exception: it immediately invalidates the
active operation and every queued command, writes the stop byte consecutively
five times by default, and returns only after every requested write has been
attempted. `repeat_count` must be an integer greater than or equal to one. The
TUI emergency-stop and shutdown paths use the default. Automatic timeout,
communication-loss, command-rejection, and acknowledgement-exhaustion stops
also send five consecutive stop bytes.

`confirm_position()` is available when the firmware is already reporting a
trusted position and sending SET would be undesirable. It adopts the current
firmware yaw/pitch as physical pan/tilt and sends no command to the hardware.

Direct elevation commands require firmware configured with the expanded TIM1
encoder period (`43200`) and center count (`21600`). Do not use this controller
with the historical `14400`-period elevation firmware: a normal move outside
that firmware's narrow representable range can wrap the counter. The accepted
move limits remain inclusive, so motion beyond an exact endpoint can still
roll over; endpoint-margin improvements are separate future work.

`send_raw(payload)` is a diagnostic escape hatch that queues the supplied bytes
for exactly one write through the controller's normal serialized writer. It
does not validate framing, commands, or coordinate bounds. Because arbitrary
bytes can move the table or change the firmware coordinate frame without a
tracked controller operation, sending raw bytes clears the controller's trusted
physical-coordinate state. A subsequent normal move requires `set_position()`
or `confirm_position()` first. Use `abort()` rather than a raw `p` when an
immediate stop is required: abort bypasses queued work, while raw writes do not.

`estimate_time(pan=..., tilt=...)` returns the estimated travel time in seconds
from the current position to the requested physical position. It uses
empirically derived acceleration-aware curves for the pan and tilt axes, then
returns the larger estimate because both axes move concurrently. It does not
include a timeout safety margin.

When `move_timeout` is omitted or `None`, `move_to` uses
`estimate_time * 1.5 + 5 seconds`. A positive custom timeout can be provided for
an individual move. See [Travel-time estimates](travel-time-estimates.md) for
the empirical model and its limitations.

## Coordinate terminology

`turntable2` retains separate names and types for the wire and public API:

- **Yaw and pitch** are the numbers maintained and reported by the
  turntable firmware. A SET command declares them as the requested coordinates
  (pan from -180° through 180° and tilt from -90° through 90°). Raw
  `ReceivedMessagePosition` events therefore expose `yaw` and `pitch`.
- **Pan and tilt** are physical angles. Public command arguments and
  `current_position()` use `pan` and `tilt`.

There is no coordinate offset or elevation-regime conversion: pan equals yaw
and tilt equals pitch.

Firmware position reports label these values `PAN` and `TILT`; raw
`ReceivedMessagePosition` events retain the internal `yaw` and `pitch` names.

## Complete diagnostic state

`get_complete_state()` returns an immutable `TurntableCompleteState` captured
under the controller lock. It includes:

- `uncorrected_position`: the latest raw `YawPitch`;
- `corrected_position`: the latest physical `PanTilt` (numerically equal to the
  raw position);
- `most_recent_position_event`, `most_recent_event`, and the five
  `recent_events` used by live diagnostics;
- `most_recent_acknowledgement` and `pending_acknowledgement_command` for
  command acceptance diagnostics;
- `state`, `activity`, its detailed `activity_phase`, and `has_been_set`;
- the active operation's corrected `target_position`, `internal_target`, and
  timezone-aware `activity_timeout_at`;
- `last_communication_at`, elapsed communication time, the configured
  communication timeout, queue depth, whether the initial SET is pending,
  position-history and event counts, and the latest asynchronous error.

For example:

```python
snapshot = turntable.get_complete_state()
print(f"firmware: {snapshot.uncorrected_position}")
print(f"physical: {snapshot.corrected_position}")
print(f"timeout: {snapshot.activity_timeout_at}")
```

The observable states are:

- `NOT_SET`: communication is working, but the position has not been set.
- `STOPPED`: the table has been set and is not moving.
- `MOVING`: a move is active.
- `NO_COMMUNICATION`: no valid position has arrived before the communication
  timeout.
- `TIMED_OUT`: a SET or MOV operation exceeded its deadline and was aborted.
- `ERROR`: a serial write or controller operation failed.
- `CLOSED`: `close()` has stopped the controller.

Every received line becomes an immutable, hashable `ReceivedMessage`.
Successfully parsed position lines become `ReceivedMessagePosition` events.
Exact firmware version responses become `ReceivedMessageVersion` events, and
exact encoder-counter responses become `ReceivedMessageCounter` events.
Exact ACK and NAK frames become `ReceivedMessageAcknowledgement` events.
The exact `MSG:ERR:POSITION_DISCONTINUITY;` safety report becomes a
`ReceivedMessageError` event. The controller responds by sending an immediate
stop, invalidating pending work and its trusted position, and entering `ERROR`.
These events intentionally preserve raw firmware yaw and pitch. Use
`current_position()` or `get_complete_state().corrected_position` for physical
pan and tilt.

`position_history()` returns bounded `PositionSample` records containing the
raw `YawPitch` and corrected `PanTilt` observed at each position-event
timestamp. The web monitor uses these paired samples so its two coordinate
plots always describe the same observations.

`command_history()` returns bounded `CommandWrite` records for the actual
successful serial writes. Each record contains the timezone-aware write
timestamp and the exact bytes passed to the serial connection. Repeated
firmware commands are retained as separate records rather than reconstructed
or collapsed.
