# Turntable Firmware–Controller Protocol Contract

This document is the authoritative contract between the STM32 turntable
firmware and the Python controller. If an implementation differs from this
document, the implementation is nonconforming unless this contract is
intentionally updated in the same change.

Changes to commands, framing, coordinate semantics, timing, or error behavior
must update this document together with firmware, controller, and tests.

The key words **MUST**, **MUST NOT**, **SHOULD**, **SHOULD NOT**, and **MAY** are
normative.

## Scope

This contract specifies:

- the UART transport;
- controller-to-firmware command frames;
- firmware-to-controller position reports;
- raw coordinate semantics;
- command repetition and completion behavior;
- timeout and error expectations.

Physical pan/tilt regime planning is controller behavior. The firmware operates
only on the raw yaw/pitch coordinates carried in the historical wire fields
named `Az` and `El`.

## Transport

The firmware and controller communicate through STM32 USART1:

| Property | Value |
| --- | --- |
| Baud rate | 9600 baud |
| Data bits | 8 |
| Parity | None |
| Stop bits | 1 |
| Hardware flow control | None |
| Firmware TX | PA9 / USART1_TX |
| Firmware RX | PA10 / USART1_RX |

The byte stream is ASCII. Binary values and character encodings other than
ASCII are not part of the protocol.

Electrical voltage levels, board power, and USB-to-UART adapter wiring are
hardware-integration concerns and must be verified for the specific board and
adapter before connection.

## Coordinate terminology

The protocol carries raw firmware coordinates measured in degrees:

- The `Az` field is called **yaw** inside the controller.
- The `El` field is called **pitch** inside the controller.

The controller's public API uses physical, regime-compensated **pan** and
**tilt**. The diagnostic shell exposes those physical values as `az` and `el`.
These operator-facing names do not change the raw wire semantics.

The firmware MUST treat command coordinates as raw yaw and pitch. It MUST NOT
apply tilt regimes or physical coordinate offsets. The controller is solely
responsible for converting between physical pan/tilt and raw yaw/pitch.

## Numeric encoding

Controller-to-firmware coordinates use this canonical ASCII form:

```text
-?[0-9]+\.[0-9]{3}
```

Requirements:

- Values MUST be finite decimal numbers.
- The controller MUST emit exactly three digits after the decimal point.
- The controller MUST use `.` as the decimal separator.
- The controller MUST NOT emit a leading `+`.
- Zero MUST be encoded as `0.000`, not `-0.000`.
- Exponential notation, `NaN`, and infinity are forbidden.

Examples:

```text
0.000
-13.250
180.000
```

Firmware position reports use exactly two digits after the decimal point as
specified below.

## Controller-to-firmware frames

SET and MOV are semicolon-terminated frames. They contain no spaces or newline:

```text
CMD:SET:<yaw>,<pitch>;
CMD:MOV:<yaw>,<pitch>;
```

The terminating semicolon is part of the frame and MUST NOT be included in
either numeric field.

Canonical examples:

```text
CMD:SET:0.000,0.000;
CMD:SET:20.000,10.000;
CMD:MOV:15.000,-13.000;
```

A canonical command is shorter than 64 bytes. Firmware MUST safely reject and
resynchronize after an oversized or malformed command. It MUST NOT move toward
a partially parsed target.

### SET

`CMD:SET` declares that the firmware's current raw position is the supplied yaw
and pitch. It changes the coordinate reference without intentionally moving the
motors.

After applying SET, the firmware MUST continue emitting position reports. A
report matching the requested raw yaw and pitch confirms completion.

The controller accepts public SET values within:

- pan/yaw: `[-180.0, 180.0]` degrees;
- tilt/pitch: `[-90.0, 90.0]` degrees.

### MOV

`CMD:MOV` commands the firmware to move both axes toward the supplied raw yaw
and pitch.

The firmware MUST:

- interpret the first value as yaw/azimuth and the second as pitch/elevation;
- continue emitting position reports while moving;
- stop driving each axis when it is within `0.1` degrees of its target;
- tolerate receiving the same MOV frame more than once.

The controller accepts physical move requests within:

- pan: `[-180.0, 180.0]` degrees;
- tilt: `[-90.0, 45.0]` degrees.

Those are public controller bounds, not necessarily the raw values sent in an
individual MOV during a tilt-regime transition. The controller constrains raw
regime pitch targets to `[-29.5, 29.5]` degrees.

### Immediate stop

Immediate stop is the single ASCII byte:

```text
p
```

It has no semicolon or newline.

On receipt, firmware MUST immediately disable motion on both axes and cancel
the active move. Position reporting MUST continue. No ACK is required.

The controller sends stop once when:

- `abort()` is requested;
- an active move loses communication;
- a SET or MOV operation times out;
- the interactive diagnostic shell disconnects from a live controller.

Bytes such as `a`, `d`, `w`, and `s` that may be recognized by historical
firmware are outside this contract. Normal controller operations MUST NOT send
them.

### Diagnostic raw writes

The diagnostic TUI MAY expose an explicitly named `raw` operation for firmware
development. This is an escape hatch from the normal command contract, not a
new firmware command:

- its ASCII payload is written exactly once without command, framing, or
  coordinate validation;
- it MUST use the controller's serialized write path rather than accessing the
  serial connection directly;
- it MUST wait behind any active tracked operation;
- after the write, the controller MUST discard its trusted coordinate frame and
  require SET or explicit position confirmation before another normal move;
- it MUST NOT replace immediate abort, because a queued raw `p` is not an
  immediate stop.

An operator using `raw` is responsible for the complete payload, including any
required semicolon. Unknown bytes and unsafe coordinate targets retain the
firmware behavior described elsewhere in this contract; the controller provides
no completion tracking for a raw command.

## Command repetition and idempotence

By default, the controller writes each SET and MOV frame three times. The
copies may be adjacent with no delay:

```text
CMD:MOV:15.000,-13.000;CMD:MOV:15.000,-13.000;CMD:MOV:15.000,-13.000;
```

Firmware MUST parse each semicolon-terminated frame independently and MUST
tolerate duplicate SET and MOV frames. Repeating an identical frame MUST be
idempotent: it must not alter the meaning of the requested reference or target.

The repetition count is controller-configurable and MUST NOT be used by
firmware as part of framing or validation.

## Firmware-to-controller position reports

Firmware MUST continuously emit CRLF-terminated position reports with this
exact structure:

```text
Pos= El: <pitch> , Az: <yaw> \r\n
```

Each number MUST:

- contain an optional `-` sign;
- contain one to three digits before the decimal point;
- contain exactly two digits after the decimal point;
- use no leading `+` and no exponential notation.

Canonical examples:

```text
Pos= El: 0.00 , Az: 0.00 \r\n
Pos= El: -13.00 , Az: 15.00 \r\n
```

The spaces shown above are required. The firmware MUST transmit only the bytes
that form the report; it MUST NOT append NUL bytes or uninitialized buffer
contents.

The controller frames incoming messages at LF (`\n`). A line containing a
matching position report becomes a position event; other complete lines become
diagnostic/other events.

Only a valid position report counts as live firmware communication. Arbitrary
diagnostic output does not reset the controller's communication timeout.

## Reporting cadence and discovery

The exact position-report frequency is not fixed, but valid reports MUST arrive
often enough to remain below the configured communication timeout.

With controller defaults:

- communication is considered lost after 1.0 second without a valid position
  report;
- serial-port discovery requires a valid position report within 2.0 seconds.

Firmware SHOULD emit several valid reports per second to provide margin for
serial scheduling and host latency.

## Acknowledgement and completion

The protocol defines no ACK or NACK frame. SET and MOV completion is inferred
from position reports.

The controller considers a raw target reached when both axes are within
`0.11` degrees of the expected raw yaw and pitch.

Default controller operation deadlines are:

- SET: 5 seconds;
- MOV: 120 seconds.

If an operation deadline expires, the controller sends immediate stop, clears
queued work, and enters its timed-out state.

If valid position reports stop for longer than the communication timeout, the
controller:

- sends immediate stop if a move is active;
- clears queued work and its trusted coordinate state;
- enters its no-communication state.

Firmware MAY emit CRLF-terminated diagnostic lines, but controller correctness
MUST NOT depend on them. Diagnostic lines MUST NOT imitate the position-report
prefix.

## Ordering

The controller serializes SET and MOV operations. It does not begin the next
queued operation until position reports confirm the current operation.

A tilt-regime transition can produce this sequence:

1. MOV to a raw transition position.
2. SET the raw position to `0.000,0.000`.
3. MOV to the next raw target.

Firmware MUST support this sequence without retaining hidden offsets or
application-level regime state.

Immediate stop is the exception to normal ordering and may be written while an
operation is active.

## Malformed and unknown input

For malformed, incomplete, oversized, or unknown commands, firmware MUST fail
safe:

- it MUST NOT begin movement toward a partially parsed value;
- it MUST NOT read or write outside command buffers;
- it SHOULD discard input through the next semicolon to resynchronize;
- it MUST continue position reporting;
- it MAY emit a diagnostic line.

Because no NACK is defined, the controller will detect failure through lack of
target confirmation or loss of valid position reports.

## Current implementation deviations

These are known differences between the authoritative contract and the current
firmware implementation. They are defects or technical debt, not protocol
features that future implementations should preserve.

1. The UART receive callback removes the semicolon before storing a command,
   while `parse_set_command()` and `parse_mov_command()` also subtract one
   character as if the semicolon were still present. This can discard the last
   character of the pitch value.
2. Firmware transmit calls currently send a fixed 42-byte buffer for both
   position and diagnostic output rather than the actual formatted length. This
   can append NUL or stale bytes after a CRLF-terminated line.
3. Historical single-character manual-control inputs (`a`, `d`, `w`, and `s`)
   are recognized by firmware but are not part of the controller protocol.

Compatibility tests should be added when these deviations are corrected so
they do not recur.
