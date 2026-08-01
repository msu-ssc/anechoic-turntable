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
