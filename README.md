# Anechoic Turntable

This repository contains the complete device-level software for the MSU
anechoic chamber turntable:

- [`src/anechoic_turntable/`](src/anechoic_turntable/) provides the reusable
  Python serial controller, wire-protocol handling, and physical position logic.
- [`firmware/`](firmware/) contains the STM32 turntable firmware.

See the [controller guide](docs/controller.md) for the Python API and
[firmware documentation](firmware/README.md) for firmware-specific information.

## Development

Create the development environment and run the checks with:

```shell
uv sync --group dev
uv run pytest
uv run ruff check src tests
```
