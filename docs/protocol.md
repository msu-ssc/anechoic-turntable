# Turntable Firmware–Controller Protocol Contract
PROTOCOL_VERSION=2.2.0

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
- firmware-to-controller position, version, and encoder-counter reports;
- raw coordinate semantics;
- command repetition and completion behavior;
- timeout and error expectations.

The controller sends physical pan/tilt directly as the yaw/pitch coordinates in
the historical wire fields named `Az` and `El`.

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

The controller's public API uses physical **pan** and **tilt**. The diagnostic
shell exposes those values as `az` and `el`. Pan and yaw are numerically equal,
as are tilt and pitch.

The firmware MUST treat command coordinates as yaw and pitch. Neither firmware
nor controller applies tilt regimes or physical coordinate offsets.

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

Encoder counters are unsigned 32-bit integers encoded as canonical decimal
ASCII. Zero is `0`; nonzero values have no leading zeroes. Signs, separators,
whitespace, decimal points, and exponential notation are forbidden. The
inclusive range is `0` through `4294967295`.

## Controller-to-firmware frames

SET, MOV, VERSION, and CNT are semicolon-terminated frames. They contain no
spaces or newline:

```text
CMD:SET:<yaw>,<pitch>;
CMD:MOV:<yaw>,<pitch>;
CMD:VERSION;
CMD:CNT;
CMD:CNT:PAN=<pan-counter>,TILT=<tilt-counter>;
```

The terminating semicolon is part of the frame and MUST NOT be included in
either numeric field.

Canonical examples:

```text
CMD:SET:0.000,0.000;
CMD:SET:20.000,10.000;
CMD:MOV:15.000,-40.000;
CMD:VERSION;
CMD:CNT;
CMD:CNT:PAN=12345,TILT=5555;
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

The controller sends those requested values directly as yaw and pitch. Firmware
used with this controller MUST represent the complete range without relying on
controller-managed coordinate resets. The current compatible configuration
uses TIM1 period `43200` with elevation zero at count `21600`.

The bounds are inclusive. They do not provide margin against encoder-counter
rollover if physical motion overshoots an exact representable endpoint.

### VERSION

`CMD:VERSION;` requests the running firmware version. It MUST NOT change the
coordinate reference, motion target, motor state, or reporting cadence. The
firmware MUST respond once for every valid request with the version response
specified below.

### CNT

`CMD:CNT;` requests the current pan and tilt encoder-counter values. It MUST
NOT alter either counter, the coordinate reference, motion target, motor state,
or reporting cadence.

`CMD:CNT:PAN=<pan-counter>,TILT=<tilt-counter>;` immediately stops both axes,
cancels the active move, and writes the supplied raw encoder-counter values.
The `PAN` field addresses the azimuth timer counter and `TILT` addresses the
elevation timer counter. This diagnostic operation changes the firmware
coordinate frame; after sending it, the controller MUST discard its trusted
physical position and require SET or explicit position confirmation before a
normal move.

Firmware MUST respond once to each valid CNT query or set command with the CNT
response specified below. For a set command, the response MUST contain the
values read back from the timer registers after the write, which may differ
from the request if a hardware counter is narrower than 32 bits.

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
- the diagnostic TUI disconnects from a live controller.

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
CMD:MOV:15.000,-40.000;CMD:MOV:15.000,-40.000;CMD:MOV:15.000,-40.000;
```

Firmware MUST parse each semicolon-terminated frame independently and MUST
tolerate duplicate SET and MOV frames. Repeating an identical frame MUST be
idempotent: it must not alter the meaning of the requested reference or target.

The repetition count is controller-configurable and MUST NOT be used by
firmware as part of framing or validation.

The controller writes each VERSION request and each CNT command exactly once.
Firmware MUST still treat repeated VERSION and CNT frames independently and
return one response per request.

## Firmware-to-controller counter responses

Firmware MUST answer each valid CNT command with exactly one CRLF-terminated
response:

```text
MSG:CNT:PAN=<pan-counter>,TILT=<tilt-counter>;\r\n
```

Both values use the unsigned 32-bit encoding specified above. For example:

```text
MSG:CNT:PAN=12345,TILT=5555;\r\n
```

The controller parses an exact conforming response as a counter event.
Malformed or otherwise non-matching lines remain diagnostic/other events. A
counter response does not count as a position report and therefore does not
reset the communication timeout.

## Firmware-to-controller version responses

Firmware MUST answer a valid VERSION request with exactly one CRLF-terminated
response:

```text
MSG:VERSION:<major>.<minor>.<patch>;\r\n
```

Each version component MUST be a non-negative decimal integer without leading
zeroes, except that zero itself is encoded as `0`. Pre-release and build
metadata are not part of this protocol. For example:

```text
MSG:VERSION:2.0.8;\r\n
```

The controller parses an exact conforming response as a version event.
Malformed or otherwise non-matching lines remain diagnostic/other events. A
version response does not count as a position report and therefore does not
reset the communication timeout.

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
Pos= El: -40.00 , Az: 15.00 \r\n
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

The controller serializes SET, MOV, VERSION, CNT, and diagnostic raw
operations. It does not begin the next queued operation until position reports
confirm an active SET or MOV operation. VERSION and CNT operations do not wait
for their responses before the next queued command is eligible to begin.

Each normal move produces one MOV frame (repeated according to the configured
repetition count) with the requested physical pan and tilt. The controller MUST
NOT insert intermediate MOV or SET operations.

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

1. Historical single-character manual-control inputs (`a`, `d`, `w`, and `s`)
   are recognized by firmware but are not part of the controller protocol.

Compatibility tests should be added when these deviations are corrected so
they do not recur.
