# Anechoic Turntable

This repository contains the complete device-level software for the MSU
anechoic chamber turntable:

- [`src/anechoic_turntable/`](src/anechoic_turntable/) provides the reusable
  Python serial controller, wire-protocol handling, and physical position logic.
- [`firmware/`](firmware/) contains the STM32 turntable firmware.

See the [controller guide](docs/controller.md) for the Python API, the
[travel-time estimate model](docs/travel-time-estimates.md) for movement timing,
and [firmware documentation](firmware/README.md) for firmware-specific
information.

The [firmware–controller protocol contract](docs/protocol.md) is the
authoritative source for UART framing, commands, reports, coordinate semantics,
and compatibility behavior. It must be kept up to date whenever firmware or
controller protocol behavior changes.

## Terminal controller

Start the terminal UI with:

```shell
uv run anechoic-turntable-tui
```

The Move and Set sections provide pan, tilt, and timeout inputs. The
move timeout is optional: when blank, subtle placeholder text shows the current
automatic estimate. Go home moves to pan 0° and tilt 0° with an
automatic timeout; Confirm approves the currently reported position without
sending a SET command. The Raw
and Parsed panels show received serial events, with a message-type filter for
the parsed stream. The Commands panel shows both operator/controller output and
the exact bytes written to the serial connection. Parsed ACK and NAK events and
the latest or pending command acknowledgement are shown in the diagnostic
streams and controller summary.

The top panel includes a connect/disconnect button, prominent state and
position-established indicators, and the latest firmware version reported by
the device. The command field supports Up/Down history navigation and accepts
`connect`, `disconnect`, `version`, `info`, `confirm`,
`set pan=<number> tilt=<number>`, `mov pan=<number> tilt=<number>`,
`set_cnt pan=<integer> tilt=<integer>`, `mov_cnt pan=<integer> tilt=<integer>`,
`counter?`, `raw`, `stop`, `help`, and `exit`. The counter commands directly
set, move to, or query firmware encoder counters for diagnostics; setting
counters clears the controller's trusted position. `stop` and the red
emergency-stop button immediately cancel queued work and send the firmware stop
byte five consecutive times. Controller-triggered safety stops use the same
default count. `version` requests and displays the running firmware version.
`raw` sends its ASCII argument exactly once without protocol or coordinate
validation; it is
for controlled firmware diagnostics only, and normal movement remains disabled
until the position is set or confirmed again. Serial-port discovery runs in the
background so the display remains responsive. Closing the TUI attempts a safe
stop before closing the serial connection.

## Basic functionality HWIL test

Run the operator-guided basic functionality HWIL test only while physically
present with the turntable:

```shell
uv run anechoic-turntable-hwil-basic
```

Pass `--port /dev/...` to select a serial port instead of auto-discovery, and
`--report PATH` to choose the JSON result path. The test first checks position
telemetry and the running firmware version. It then guides the operator through
an interactive centering loop. The operator may confirm an already-correct
reported position without sending SET; the runner still performs the approved
go-home movement. Otherwise, each approved attempt declares the
operator's estimated physical pan/tilt with SET and moves to `(+0, +0)`. The loop
continues until the operator confirms physical center.

After centering, the test exercises small pan and tilt movements, returning to
home after each axis. Every move displays its target, estimated duration, hard
timeout, command writes, acknowledgements, and position reports. The operator
must approve each move and confirm its rounded physical result. Directions,
targets, and confirmation prompts are rounded to the nearest degree; the
subdued live position trace updates at about 3 Hz with three decimal places.
Each movement trace line shows the current position and the remaining signed
pan/tilt delta to the target. All operator-facing angles include an explicit
`+` or `-` sign.
Ctrl-C, a declined
action, a controller failure, or normal completion all attempt an immediate
stop before the connection closes. The generated JSON report records versions,
centering attempts, results, confirmations, and the serial trace.

The final checks start from home. The first commands pan `+30°` and automatically sends
the emergency stop as soon as reported pan passes `+5°`. Its live trace shows
pan remaining until the abort threshold rather than pan remaining to the
commanded target. After the operator confirms that the stop was immediate and
safe, an operator-approved movement returns the table home. The second check
commands tilt `-30°`, stops after reported tilt passes `-5°`, receives the same
operator confirmation, and returns home again.

This is supervised physical-equipment testing, not part of the normal `pytest`
suite. Follow the safety guidance in [Hardware test procedures](docs/test_procedures.md)
before running it.

## Development

Create the development environment and run the checks with:

```shell
uv sync --group dev
uv run pre-commit install
uv run pytest
uv run ruff check src tests
```

Run every pre-commit check against the repository with:

```shell
uv run pre-commit run --all-files
```

## Versions and releases

The repository tracks three independent semantic versions:

- `CONTROLLER_VERSION` is the Python controller and package version. Its
  canonical value is in `src/anechoic_turntable/_version.py`.
- `PROTOCOL_VERSION` identifies the firmware–controller wire contract. Its
  canonical declaration is at the top of `docs/protocol.md`.
- `REFERENCE_FIRMWARE_VERSION` records the firmware version in the source tree
  used to make a controller release. Its canonical definition is
  `FIRMWARE_VERSION` in `firmware/Core/Inc/firmware_version.h`. A missing header
  is recorded as the unknown version `0.0.0`.

`__version__` is an alias for `CONTROLLER_VERSION`. The release workflow reads
the canonical protocol and firmware values and copies them into the Python
version module so an installed package exposes stable release-time snapshots
without reading repository files at import time.

Every pull request to `main` must select at least one release label. At most one
label may be selected from each component family:

- `release:firmware:major`, `release:firmware:minor`, or
  `release:firmware:patch`;
- `release:controller:major`, `release:controller:minor`, or
  `release:controller:patch`.

Firmware and controller labels may be combined. A pull request that releases
neither component must use `release:none`, which cannot be combined with a
component release label.

The pull-request template provides separate firmware and controller release-note
sections. A note is required for every selected component release.
Automation calculates exact versions from their canonical files; contributors
must not put an exact future version in the pull request.

After merge, one workflow prepares and preflights all requested releases before
publishing release state. For a combined release it creates the firmware
version/changelog commit first and the controller commit second, then atomically
pushes `main` with tags such as `firmware-v2.3.4` and `CONTROLLER_v1.2.3`.
GitHub Releases are created in the same order. Firmware releases contain
`turntable_firmware_<version>.elf` and its SHA-256 checksum; controller releases
contain an installable wheel and source distribution. These generated release
commits are the only exception to the rule against direct pushes to `main`.

The firmware and controller follow [Semantic Versioning](https://semver.org/).
At `1.0.0` and later, major releases contain incompatible changes, minor
releases add backward-compatible functionality, and patch releases contain
backward-compatible fixes. The normal compatibility guarantee does not apply to
`0.Y.Z` development releases: breaking changes and new features increment the
minor version, while backward-compatible bug fixes increment the patch version.

See [Firmware build](docs/firmware-build.md) for the reproducible command-line
build, CubeIDE regeneration rules, pinned toolchain, and release artifact flow.
