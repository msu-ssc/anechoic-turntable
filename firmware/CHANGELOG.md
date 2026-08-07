# Changelog

Firmware releases are recorded here

## 1.0.0 — Unknown, but sometime before 2025

The original firmware written by Dr. Elijah Jensen, Jody Caudill, and possibly others

## 2.0.0 — 2026-07-28

BUGFIX: Fix set command error where non-zero user values are parsed but ignored.

Note that this was the first firmware change of any kind in at least 2 years. This release is designated a major version change (rather than a patch change, which bugfixes would usually get) in order to denote a clean break in project continuity.

## 2.0.1 — 2026-07-31

BUGFIX: Correct elevation encoder counter period

Moving elevation down past -30.000 degrees and then attempting to move back up to a higher elevation would previously result in the table improperly resetting its counter, which would lead to runaway elevation movement. Setting the counter period properly solves this problem.

## 2.0.2 — 2026-07-31

BUGFIX: Reject oversized command frames without overflowing the receive buffer.

## 2.0.3 — 2026-07-31

BUGFIX: Safely null-terminate completed command strings.

## 2.0.4 — 2026-07-31

BUGFIX: Parse the complete pitch value instead of dropping its final character.

## 2.0.5 — 2026-07-31

BUGFIX: Reject malformed command frames instead of partially parsing them.

## 2.0.6 — 2026-07-31

BUGFIX: Clear partial and pending commands when receiving an immediate stop.

## 2.0.7 — 2026-07-31

BUGFIX: Prevent UART interrupts from overwriting commands while they are processed.

## 2.0.8 — 2026-07-31

BUGFIX: Transmit only the formatted bytes in firmware messages.

## 2.1.0 — 2026-08-01

Add support for the `CMD:VERSION?` command

## 2.2.0 — 2026-08-06

Add `CMD:CNT;` and `CMD:CNT:PAN=12345,TILT=12345;` commands to get/set encoder position

## 2.3.0 — 2026-08-06

Add counter SET and MOV commands

## 2.4.0 — 2026-08-06

Add firmware ACK/NAK response to all commands.

(Note that this is considered only a minor change because external interfaces that completely ignore these ACKs and NAKs would still function exactly the same.)

## 3.0.0 — 2026-08-07

Firmware now outputs position in a format like `MSG:POS:PAN=123.456,TILT=-87.654;`

## 3.1.0 — 2026-08-07

Firmware can now detect and handle
- MOV and SET commands that are out of bounds
- Discontinuities in movements (generally caused by invalid counter wrapping)
-

## 3.1.1 — 2026-08-07

Fixed the maximum and minimum values for the tilt.

## 3.1.2 — 2026-08-07

Modify firmware angle determination calculations to allow "wiggle room" near -180 degrees pan and -90 degrees tilt, so as to avoid underflowing if a movement to an extreme coordinate overshoots slightly.

## 3.2.0 — 2026-08-07

Standardize everything on pan/tilt terminology
