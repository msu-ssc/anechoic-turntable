# Anechoic Turntable

This repository contains the complete device-level software for the MSU
anechoic chamber turntable:

- [`src/anechoic_turntable/`](src/anechoic_turntable/) provides the reusable
  Python serial controller, wire-protocol handling, and physical position logic.
- [`firmware/`](firmware/) contains the STM32 turntable firmware.

See the [controller guide](docs/controller.md) for the Python API and
[firmware documentation](firmware/README.md) for firmware-specific information.

## Interactive controller

Start the minimal interactive controller with:

```shell
uv run anechoic-turntable
```

Type `help` at the prompt to see the supported commands. `connect` discovers the
turntable on an available serial port. Azimuth maps to physical pan and
elevation maps to physical tilt. Reconnecting, exiting, EOF, and Ctrl-C send the
stop command before closing the serial connection.

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
