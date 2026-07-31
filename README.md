# Anechoic Turntable

This repository contains the complete device-level software for the MSU
anechoic chamber turntable:

- [`src/anechoic_turntable/`](src/anechoic_turntable/) provides the reusable
  Python serial controller, wire-protocol handling, and physical position logic.
- [`firmware/`](firmware/) contains the STM32 turntable firmware.

See the [controller guide](docs/controller.md) for the Python API and
[firmware documentation](firmware/README.md) for firmware-specific information.

The [firmware–controller protocol contract](docs/protocol.md) is the
authoritative source for UART framing, commands, reports, coordinate semantics,
and compatibility behavior. It must be kept up to date whenever firmware or
controller protocol behavior changes.

## Interactive controller

Start the minimal interactive controller with:

```shell
uv run anechoic-turntable
```

Type `help` at the prompt to see the supported commands. `connect` discovers the
turntable on an available serial port. Azimuth maps to physical pan and
elevation maps to physical tilt. Reconnecting, exiting, EOF, and Ctrl-C send the
stop command before closing the serial connection.

For an auto-updating view of connection state, physical position, target, and
controller activity, start the terminal UI with:

```shell
uv run anechoic-turntable-tui
```

The command field accepts `connect`, `info`, `confirm`, `set`, `mov`, `raw`,
`stop`, `help`, and `exit`. `confirm` approves the currently reported azimuth
and elevation without sending a SET command. `stop` and the red emergency-stop
button immediately cancel queued work and send the firmware stop byte. `raw`
sends its ASCII argument exactly once without protocol or coordinate validation;
it is for controlled firmware diagnostics only, and normal movement remains
disabled until the position is set or confirmed again. Serial-port discovery
runs in the background so the display remains responsive. The diagnostic panels
show physical az/el, reported firmware az/el, and the five most recent framed
serial lines.

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

Every pull request to `main` must have exactly one of `version:major`,
`version:minor`, `version:patch`, or `version:no_bump`. After a versioned pull
request is merged, release automation commits the generated version and
changelog update directly to `main`, creates a tag such as
`CONTROLLER_v1.2.3`, and creates the corresponding GitHub Release with an
installable wheel and source distribution attached. This generated chore commit
is the only exception to the rule against direct pushes to `main`.

The controller follows [Semantic Versioning](https://semver.org/). At `1.0.0`
and later, major releases contain incompatible changes, minor releases add
backward-compatible functionality, and patch releases contain
backward-compatible fixes. The normal compatibility guarantee does not apply
to `0.Y.Z` development releases: breaking changes and new features increment
the minor version, while backward-compatible bug fixes increment the patch
version.
