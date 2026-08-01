# AGENTS.md — Repository instructions for coding agents

These instructions apply to any automated coding agent operating in this
repository.

## Context

This repository is the complete device-level compatibility unit for the MSU
anechoic chamber turntable. It contains:

- STM32 turntable firmware in `firmware/`;
- the reusable Python serial controller in `src/anechoic_turntable/`;
- wire-protocol parsing and formatting;
- physical position and tilt-regime logic;
- the interactive firmware-development shell;
- controller, protocol, and shell tests;
- device/controller documentation.

The turntable is physical laboratory equipment driven by motors. Incorrect
commands, coordinate handling, timeout behavior, or stop behavior can damage
equipment or create a safety hazard.

Implications:

- Prefer correctness, traceability, and safe failure behavior over speed.
- Minimize behavioral changes unless explicitly requested.
- Make protocol changes atomically across firmware, controller, tests, and
  documentation.
- Never assume simulated serial tests prove hardware behavior.

## Architectural boundary

This repository owns device-level behavior and compatibility.

## Information

- Start with `README.md`.
- Python controller behavior is documented in `docs/controller.md`.
- `docs/protocol.md` is the authoritative firmware–controller protocol
  contract.
- Firmware-specific overview information belongs in `firmware/README.md`.
- Firmware build and release-artifact details are in `docs/firmware-build.md`.
- Tests live in `tests/`.

## Operating mode

- **Design first.** Default to analysis and design. Implement only when the user
  explicitly asks for a change.
- **Ask before guessing.** Ask targeted questions when ambiguity would affect
  hardware behavior, coordinate meaning, wire compatibility, or public API.
- **Make incremental changes.** Prefer small, reviewable edits with focused
  verification.
- **Keep behavior explicit.** Avoid hidden I/O, surprising motor commands, and
  implicit coordinate-frame changes.

## Git and external-state rules

- Never push directly to `main`.
- The sole exception is the post-merge release GitHub Action. It may push its
  generated firmware and controller version/changelog chore commits and tags
  directly to `main`. Humans and all other automation must still use pull
  requests.
- Work on a feature branch and use a pull request when publication is requested.
- Do not create or change remotes, publish a package, flash firmware, energize
  hardware, or operate the physical table unless the user explicitly requests
  that action.
- Do not modify or delete neighboring repositories as part of work here.
- Preserve unrelated working-tree changes.

Every pull request to `main` must select at least one release label. At most one
label may be selected from each component family:

- `release:firmware:major`, `release:firmware:minor`, or
  `release:firmware:patch`;
- `release:controller:major`, `release:controller:minor`, or
  `release:controller:patch`.

Firmware and controller labels may be combined. If neither component is being
released, use `release:none` by itself.

The pull-request template supplies separate release notes for firmware and the
controller. A note is required for each selected component release.

While a component is at version `0.Y.Z`, breaking changes and new features use
that component's `minor` label, and backward-compatible bug fixes use its
`patch` label.
After `1.0.0`, use normal Semantic Versioning compatibility rules.

## Dependency management

Use **uv** for Python package management and execution.

- Sync the development environment: `uv sync --group dev`
- Add a runtime dependency: `uv add <package>`
- Add a development dependency: `uv add --dev <package>`
- Run Python: `uv run python ...`
- Run the diagnostic shell: `uv run anechoic-turntable`

The local interpreter is normally `./.venv/bin/python`.

Do not hand-edit `uv.lock` or use `pip` to manage this project environment.

## Pre-commit

This repository uses pre-commit to enforce Ruff linting and formatting.

- Install hooks in a fresh clone: `uv run pre-commit install`
- Run all hooks manually: `uv run pre-commit run --all-files`
- If hooks modify files, review the changes and rerun them until they pass.

## Required verification

For Python changes, run:

```shell
uv run pre-commit run --all-files
uv run pytest
uv run ruff check src tests
```

Also run a focused smoke test when changing package exports or entry points.
Use `git diff --check` before considering work complete.

Firmware changes require proportionate firmware build verification when the
toolchain is available. Clearly distinguish:

- static/source inspection;
- host-side unit tests;
- successful firmware compilation;
- bench or hardware-in-the-loop testing.

Never claim a stronger verification level than was actually performed.

## Testing

- New behavior requires focused tests.
- Tests must not require physical hardware unless explicitly marked and
  requested as hardware-in-the-loop tests.
- Use fake serial connections to exercise framing, controller state, commands,
  timeouts, and error handling.
- Use fake controller connections to test the interactive shell.
- Keep tests small, deterministic, and minimally mocked.
- Prefer parametrization for strict parsers and boundary cases.

For a newly discovered bug, reproduce it with a failing test before implementing
the fix when practical.

## Python architecture and invariants

The Python controller is intentionally threaded and non-blocking:

- `serial_listener.py` owns continuous serial reads and line framing.
- `controller.py` owns controller state, command sequencing, timeouts, event
  history, and serial writes.
- `turntable.py` is the thread-safe public API.
- `messages.py` owns received wire-message parsing.
- `positions.py` and `regimes.py` own device-level coordinate behavior.
- `repl.py` is the primary interactive firmware diagnostic tool.

Preserve these invariants:

- Do not add a second serial reader.
- Do not bypass controller queues by writing commands directly from public API
  or shell code.
- Protect shared state consistently with the existing locks and queues.
- Public movement and SET methods remain non-blocking unless an API change is
  explicitly designed and approved.
- `abort()` remains immediate: it invalidates queued work and attempts the stop
  write before returning.
- Connection shutdown during interactive use must attempt a safe stop before
  closing the serial connection.
- Communication loss and operation timeouts must fail safe.

## Firmware and wire protocol

`docs/protocol.md` is authoritative for the contract between firmware and the
Python controller. It MUST be kept up to date. Any change to UART framing,
commands, reports, coordinate semantics, repetition, timing, acknowledgements,
or error behavior must update the contract in the same change.

The `PROTOCOL_VERSION` declaration in `docs/protocol.md` is the canonical wire
protocol version. Treat both the contract and its version as safety-critical:
before changing either one, explicitly confirm with the user that the protocol
contract and, when applicable, its version should change. Do not infer
permission from an adjacent controller or firmware change.

`src/anechoic_turntable/_version.py` is the canonical source for the controller
version and contains release snapshots of the protocol and reference firmware
versions. The post-merge release Action copies `PROTOCOL_VERSION` from the
protocol contract and `FIRMWARE_VERSION` from
`firmware/Core/Inc/firmware_version.h` into that module. If the firmware header
is unavailable, the reference firmware snapshot is `0.0.0`.

The current firmware uses STM32 USART1 at 9600 baud, 8 data bits, no parity, and
one stop bit. Treat electrical assumptions and pin mappings as hardware facts
that must be verified before changing documentation or code.

The existing command protocol includes:

- `CMD:SET:<azimuth>,<elevation>;`
- `CMD:MOV:<azimuth>,<elevation>;`
- `p` for immediate stop.

Position reports use the historical format:

```text
Pos= El: <pitch> , Az: <yaw>
```

Protocol parsers and formatters should be strict, deterministic, and tested
against exact bytes. When adding a firmware command, update the Python
controller, diagnostic shell when appropriate, tests, and documentation in the
same change.

The STM32 project contains generated/vendor code. Prefer edits in the intended
user-code regions and avoid broad formatting or mechanical rewrites of
`firmware/Drivers/`, startup files, generated HAL code, or project metadata.

## Coordinates and naming

Keep the coordinate layers distinct:

- **Yaw/pitch** are relative firmware/internal coordinates.
- **Pan/tilt** are physical, regime-compensated controller coordinates.
- The diagnostic shell spells physical pan/tilt as **az/el** for operator-facing
  commands.

Do not casually rename these concepts or mix values across layers. SET changes
the declared coordinate frame; MOV requests physical movement through the
controller's regime logic.

## Diagnostic shell

The interactive shell is the primary firmware-development diagnostic tool.

- Build it on the standard-library `cmd.Cmd` framework.
- Add commands as conventional `do_<command>` methods with useful docstrings so
  built-in help remains accurate.
- Do not replace `cmd.Cmd` dispatch with a custom REPL loop.
- Do not override standard `cmd.Cmd` behavior without a concrete, documented
  reason.
- Keep command parsing isolated from command execution and unit-test it.
- Reject malformed or ambiguous arguments rather than guessing.
- Route device operations through the public `Turntable` API.
- Catch recoverable device/validation failures at the command boundary so one
  bad command does not terminate a diagnostic session.

## Coding standards

### General

- Prefer small, cohesive modules and explicit side effects.
- Prefer long, descriptive names over abbreviations except established device
  terminology such as az/el.
- Include type hints for parameters and return values.
- Include clear docstrings; short docstrings are fine.
- Keep public APIs narrow and intentional.

### Imports

- Use absolute imports. Relative imports require a specific, documented reason.
- Group standard-library, third-party, and first-party imports with blank lines.
- Let Ruff organize import formatting.
- Include `from __future__ import annotations` in Python modules where
  appropriate.
- Guard imports used only for typing with `if TYPE_CHECKING:` when that avoids a
  runtime dependency or import cycle.

### Supported Python

- Support Python 3.10 and newer as declared in `pyproject.toml`.
- Do not use newer syntax or standard-library APIs without a compatible
  fallback.
- Keep the package portable; avoid OS-specific assumptions outside serial-port
  discovery and clearly isolated platform handling.

## Documentation

- Update `docs/controller.md` for controller API or behavior changes.
- Update `firmware/README.md` for firmware setup, build, flashing, wiring, and
  protocol details.
- Update the root `README.md` for installation, repository structure, and
  diagnostic-shell usage.
- Document physical safety assumptions and unverified hardware behavior
  explicitly.

## How to collaborate effectively

When asked to work on something:

1. Briefly restate the goal and important constraints.
2. Propose a small plan for non-trivial work.
3. Ask only blocking questions; otherwise make conservative, stated assumptions.
4. Implement in small steps after the user asks for implementation.
5. Report changed files, verification performed, and anything not verified.
