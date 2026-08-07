# Changelog

Controller releases are recorded here by the post-merge release workflow.

## 0.1.0 — 2026-07-31

Implement automated releases with dynamic versions

## 0.2.0 — 2026-07-31

Create automation to include Python wheel as part of release pipeline

## 0.2.1 — 2026-07-31

Remove build artifact from git tracking

## 0.3.0 — 2026-08-01

Add support for the `CMD:VERSION?` command

## 0.4.0 — 2026-08-01

Add version command to protocol

## 0.5.0 — 2026-08-01

Removed REPL

Made several backwards compatible changes to the controller TUI:
- Redesigned layout with panels.
- Removed redundant clutter.
- Added Raw and filterable Parsed event streams for received messages.
- Added command output and exact transmitted-byte history.
- Added dedicated Move and Set controls
- Surfaced timeout inputs for commands

## 0.6.0 — 2026-08-03

Make default move timeout be dynamic based on empirical measurements of travel time.

## 0.7.0 — 2026-08-06

Add `CMD:CNT;` and `CMD:CNT:PAN=12345,TILT=12345;` commands to get/set encoder position

## 0.8.0 — 2026-08-06

Add counter SET and MOV commands

## 0.9.0 — 2026-08-06

Add controller-side support for ACK/NAK messages from firmware.

(Note that this is considered only a minor change because external interfaces that completely ignore these ACKs and NAKs would still function exactly the same.)

## 0.10.0 — 2026-08-07

Controller now accepts new-style position output like `MSG:POS:PAN=123.456,TILT=-87.654;`

This is considered a major change only because the underlying firmware change is a breaking change. There is no change to the controller's external interface.

## 0.11.0 — 2026-08-07

Several small TUI improvements
- Add "connect"/"disconnect" button.
- Add "version" text command
- Add command scrolling
- Filter out position messages by default
- Include text on "other" events
- Make state display more prominent

## 0.12.0 — 2026-08-07

Add controller handling of
- Firmware NAK for invalid MOV and SET commands
- Unsolicited messages when movement is stopped because of a jump in movement

## 0.13.0 — 2026-08-07

Standardize everything on pan/tilt terminology

## 0.14.0 — 2026-08-07

Add ZMQ publishing of turntable position
