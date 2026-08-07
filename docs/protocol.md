# Turntable Firmware–Controller Protocol Contract
PROTOCOL_VERSION=3.1.0

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
- command acknowledgement, retry, and completion behavior;
- timeout and error expectations.

For SET and MOV, the controller sends physical pan/tilt directly as yaw/pitch
coordinates. MOV_CNT instead carries raw counter targets that firmware converts
to degrees.

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

- The `PAN` report field is called **yaw** inside the controller.
- The `TILT` report field is called **pitch** inside the controller.

The controller's public API uses physical **pan** and **tilt**. The diagnostic
shell exposes those values as `pan` and `tilt`. Pan and yaw are numerically equal,
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

Firmware position reports use exactly three digits after the decimal point as
specified below.

Encoder counters are unsigned 32-bit integers encoded as canonical decimal
ASCII. Zero is `0`; nonzero values have no leading zeroes. Signs, separators,
whitespace, decimal points, and exponential notation are forbidden. The
inclusive range is `0` through `4294967295`.

## Controller-to-firmware frames

SET, MOV, MOV_CNT, SET_CNT, VERSION, and CNT are semicolon-terminated frames.
They contain no spaces or newline:

```text
CMD:SET:<yaw>,<pitch>;
CMD:MOV:<yaw>,<pitch>;
CMD:MOV_CNT:PAN=<pan-counter>,TILT=<tilt-counter>;
CMD:SET_CNT:PAN=<pan-counter>,TILT=<tilt-counter>;
CMD:VERSION;
CMD:CNT;
```

The terminating semicolon is part of the frame and MUST NOT be included in
either numeric field.

Canonical examples:

```text
CMD:SET:0.000,0.000;
CMD:SET:20.000,10.000;
CMD:MOV:15.000,-40.000;
CMD:MOV_CNT:PAN=45600,TILT=20400;
CMD:SET_CNT:PAN=12345,TILT=5555;
CMD:VERSION;
CMD:CNT;
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

Firmware MUST reject an otherwise well-formed SET outside these inclusive
bounds with `OUT_OF_BOUNDS` and MUST NOT change either counter.

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

Firmware MUST reject an otherwise well-formed MOV outside these inclusive
bounds with `OUT_OF_BOUNDS` and MUST NOT begin that movement.

The controller sends those requested values directly as yaw and pitch. Firmware
used with this controller MUST represent the complete range without relying on
controller-managed coordinate resets. The current compatible configuration
uses TIM1 period `43200` with elevation zero at count `21600`.

The bounds are inclusive. They do not provide margin against encoder-counter
rollover if physical motion overshoots an exact representable endpoint.

### MOV_CNT

`CMD:MOV_CNT:PAN=<pan-counter>,TILT=<tilt-counter>;` commands both axes using
raw encoder-counter targets. Firmware MUST convert the counters to the same
yaw and pitch degree targets used by MOV:

```text
yaw = (pan-counter - 43200) / 240
pitch = (tilt-counter - 21600) / 240
```

After conversion, firmware MUST use the existing MOV movement logic and
position-report completion behavior without a separate counter-based motor
control mode. It MUST tolerate receiving the same MOV_CNT frame more than
once.

MOV_CNT is a diagnostic operation and does not establish a trusted physical
coordinate frame. The controller accepts unsigned 32-bit counter fields,
sends the frame once with acknowledgement-based retries, tracks the converted
degree target, and uses a 300-second timeout by default. On timeout or
communication loss it MUST send the immediate stop byte. The operator is
responsible for choosing targets that the configured timer periods and
physical mechanism can safely reach.

### SET_CNT

`CMD:SET_CNT:PAN=<pan-counter>,TILT=<tilt-counter>;` immediately stops both
axes, cancels the active move, and writes the supplied raw encoder-counter
values. The `PAN` field addresses the azimuth timer counter and `TILT`
addresses the elevation timer counter. This diagnostic operation changes the
firmware coordinate frame; after sending it, the controller MUST discard its
trusted physical position and require SET or explicit position confirmation
before a normal move.

Firmware MUST respond once to each valid SET_CNT command with the CNT response
specified below. The response MUST contain the values read back from the timer
registers after the write, which may differ from the request if a hardware
counter is narrower than 32 bits.

### VERSION

`CMD:VERSION;` requests the running firmware version. It MUST NOT change the
coordinate reference, motion target, motor state, or reporting cadence. The
firmware MUST respond once for every valid request with the version response
specified below.

### CNT

`CMD:CNT;` requests the current pan and tilt encoder-counter values. It MUST
NOT alter either counter, the coordinate reference, motion target, motor state,
or reporting cadence.

Firmware MUST respond once to each valid CNT query with the CNT response
specified below.

### Immediate stop

Immediate stop is the single ASCII byte:

```text
p
```

It has no semicolon or newline.

On receipt, firmware MUST immediately disable motion on both axes and cancel
the active move. Position reporting MUST continue. Firmware MUST emit
`MSG:ACK:EMERGENCY_STOP;\r\n`; transmission of this acknowledgement may occur
after the motors have been disabled and MUST NOT delay the immediate stop.

Every controller-side immediate stop writes `p` consecutively five times by
default. `abort(*, repeat_count=5)` immediately invalidates active and queued
work, then uses its keyword-only `repeat_count`; the method returns after every
requested write has been attempted. `repeat_count` MUST be an integer greater
than or equal to one. The diagnostic TUI emergency-stop and disconnect paths
use the default.

Firmware treats every `p` as an independent accepted emergency-stop command
and emits one `MSG:ACK:EMERGENCY_STOP;\r\n` for each byte. The controller does
not wait for these acknowledgements and does not retry an individual stop byte.

The same default of five consecutive writes applies when:

- an active move loses communication;
- a SET, MOV, or MOV_CNT operation times out;
- a MOV or MOV_CNT receives a NAK;
- a MOV or MOV_CNT exhausts its acknowledgement attempts.

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

## Command acknowledgement, retry, and idempotence

Firmware MUST emit exactly one acknowledgement for every accepted or rejected
command. Acknowledgements are CRLF-terminated exact frames:

```text
MSG:ACK:<command>;\r\n
MSG:NAK:<command>,<reason>;\r\n
```

`<command>` is one of `SET`, `MOV`, `MOV_CNT`, `SET_CNT`, `VERSION`, `CNT`,
`EMERGENCY_STOP`, or `UNKNOWN`. `UNKNOWN` is valid only in a NAK. `<reason>` is
one of:

- `UNABLE_TO_PARSE`: the command was malformed, incomplete, oversized, or
  unknown;
- `OUT_OF_BOUNDS`: an otherwise well-formed SET or MOV contained a coordinate
  outside its inclusive firmware bounds;
- `REJECTED`: the complete command was understood but was not accepted, for
  example because an emergency stop cancelled it or another complete frame
  could not be queued.

An ACK means the complete command was received, parsed, accepted, and applied.
For VERSION, CNT, and SET_CNT, firmware MUST send the ACK before the command's
specific VERSION or CNT response. A NAK means that the requested operation was
not performed. Firmware MUST fail safe and stop motion when rejecting input.

The controller sends a queued protocol command once and waits 0.25 seconds for
a matching ACK or NAK before retrying. By default, at most three total attempts
are made; `command_repetitions` configures this maximum attempt count. A
matching ACK prevents all further attempts. A mismatched or malformed
acknowledgement remains diagnostic data and MUST NOT release the pending
command.

After the configured attempts receive no acknowledgement, the controller MUST
fail the command, clear queued work, and enter `ERROR`. If MOV or MOV_CNT may
have been accepted, it MUST also send immediate stop. If SET or SET_CNT may
have been accepted, it MUST discard its trusted coordinate state.

Firmware MUST parse every semicolon-terminated frame independently and tolerate
retries. Repeating an identical valid frame MUST be idempotent: it must not
alter the meaning of the requested reference or target. Each accepted retry is
ACKed and produces any command-specific response independently.

## Firmware-to-controller counter responses

Firmware MUST answer each valid CNT or SET_CNT command with exactly one
CRLF-terminated response:

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
reset the communication timeout. The command ACK precedes this response.

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
reset the communication timeout. The command ACK precedes this response.

## Firmware-to-controller position reports

Firmware MUST continuously emit CRLF-terminated position reports with this
exact structure:

```text
MSG:POS:PAN=<yaw>,TILT=<pitch>\r\n
```

Each number MUST:

- contain an optional `-` sign;
- contain one to three digits before the decimal point;
- contain exactly three digits after the decimal point;
- use no leading `+` and no exponential notation.

Canonical examples:

```text
MSG:POS:PAN=0.000,TILT=0.000\r\n
MSG:POS:PAN=15.000,TILT=-40.000\r\n
```

The firmware MUST transmit only the bytes that form the report; it MUST NOT
append NUL bytes or uninitialized buffer contents.

The controller frames incoming messages at LF (`\n`). An exact matching
position report becomes a position event; other complete lines become
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

ACK confirms command acceptance, not physical completion. SET, MOV, and
MOV_CNT completion continues to be inferred from position reports.

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

The controller serializes SET, MOV, MOV_CNT, SET_CNT, VERSION, CNT, and
diagnostic raw operations. It does not begin the next queued protocol command
until the current command is ACKed. It also waits for position reports to
confirm an active SET, MOV, or MOV_CNT operation. VERSION, CNT, and SET_CNT do
not wait for their command-specific responses after ACK before the next queued
command is eligible to begin.

Each normal move produces one MOV frame with the requested physical pan and
tilt, with retries only when its acknowledgement is missing. The controller
MUST NOT insert intermediate MOV or SET operations.

Immediate stop is the exception to normal ordering and may be written while an
operation is active.

## Malformed and unknown input

For malformed, incomplete, oversized, or unknown commands, firmware MUST fail
safe:

- it MUST NOT begin movement toward a partially parsed value;
- it MUST NOT read or write outside command buffers;
- it SHOULD discard input through the next semicolon to resynchronize;
- it MUST continue position reporting;
- it MUST emit a NAK once the rejected frame can be classified or discarded.

Firmware uses the recognized command token in a NAK when possible. It uses
`UNKNOWN` when the token cannot be determined, including for an oversized
frame whose buffered prefix has been discarded. An unterminated partial frame
cannot be acknowledged until it is terminated, discarded as oversized, or
interrupted by emergency stop.

## Current implementation deviations

These are known differences between the authoritative contract and the current
firmware implementation. They are defects or technical debt, not protocol
features that future implementations should preserve.

1. Historical single-character manual-control inputs (`a`, `d`, `w`, and `s`)
   are recognized by firmware but are not part of the controller protocol.

Compatibility tests should be added when these deviations are corrected so
they do not recur.
