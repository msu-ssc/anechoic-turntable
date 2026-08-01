# Firmware build

This document describes the reproducible command-line build used for firmware
release artifacts. It covers compilation only: it does not authorize flashing
hardware or operating the turntable.

## Build contract

The release pipeline builds the STM32CubeIDE **Debug** configuration with GNU
Make. This name is inherited from CubeIDE; it is the intentional release-artifact
profile for this repository.

The important settings are:

- ST GNU Tools for STM32 bundle `14.3.1+st.2`, matching STM32CubeIDE 2.2.0;
- Cortex-M4 with `fpv4-sp-d16` and the hard-float ABI;
- debug information level `-g3` and the `DEBUG` definition;
- optimization level `-O0`;
- linker script `firmware/STM32F407VETX_FLASH.ld`;
- output `firmware/Debug/chambermotorcontrol.elf`.

Do not substitute the generic upstream Arm GNU Toolchain. During pipeline
validation, its nominally equivalent GCC 14.3 compiler produced a materially
different image. Do not change the optimization level or use the CubeIDE
Release configuration without proportionate bench or hardware-in-the-loop
validation.

## Inputs stored in Git

CubeIDE stores the durable project settings in `firmware/.cproject`. Its
managed-build generator turns that configuration into seven Make inputs that
must also be version-controlled:

- `firmware/Debug/makefile`;
- `firmware/Debug/sources.mk`;
- `firmware/Debug/objects.mk`;
- `firmware/Debug/objects.list`;
- `firmware/Debug/Core/Src/subdir.mk`;
- `firmware/Debug/Core/Startup/subdir.mk`;
- `firmware/Debug/Drivers/STM32F4xx_HAL_Driver/Src/subdir.mk`.

The compiler creates object files, dependency files, stack-usage data, maps,
listings, and the ELF in the same tree. Those outputs are ignored. The generated
Make inputs are deliberately retained so CI and a clean checkout do not need to
run the complete IDE merely to compile existing source.

`firmware/.settings/language.settings.xml` is Eclipse/CDT scanner-discovery
state. It contains environment hashes used for editor indexing and is not an
input to the Make build or the release artifact. The repository has ignore
rules for this file, but ignore rules do not suppress changes to a file that is
already tracked. If the file remains in Git's index, CubeIDE environment-hash
updates can therefore still appear in the working tree; removing it from the
index would not affect command-line firmware builds.

## Relative linker-script setting

CubeIDE can generate a developer-specific absolute linker path when the linker
script is expressed with `${workspace_loc:...}`. The project instead stores
`../STM32F407VETX_FLASH.ld` in both build configurations.

In CubeIDE, this is configured at **Project Properties → C/C++ Build → Settings
→ Tool Settings → MCU GCC Linker → General → Linker Script**. CubeIDE invokes
Make from the selected configuration directory, so `..` resolves to the
`firmware/` project directory both locally and in CI.

Cyclomatic-complexity output is disabled under **MCU GCC Compiler →
Miscellaneous**. The analysis output is not needed for a release and its ST-only
compiler flag makes the generated recipes less portable.

## Local command-line build

Put the pinned ST toolchain's `bin` directory on `PATH`, then run:

```shell
make -C firmware/Debug clean all
arm-none-eabi-size firmware/Debug/chambermotorcontrol.elf
```

The `clean` target removes ignored outputs but leaves the seven tracked Make
inputs intact. A successful build produces the ELF, map, size report, and
disassembly listing under `firmware/Debug/`.

## Regenerating the Make inputs

When firmware sources or CubeIDE build settings change:

1. Open the project in STM32CubeIDE 2.2.0 or a deliberately validated successor.
2. Confirm the Debug compiler uses `-O0`, cyclomatic complexity is disabled,
   and the linker script field is `../STM32F407VETX_FLASH.ld`.
3. Clean and build the Debug configuration so CubeIDE regenerates its Make
   inputs.
4. Review the seven tracked generated files. Reject absolute developer paths,
   unexpected sources, optimization changes, or toolchain changes.
5. Run `uv run pytest tests/test_firmware_build.py` and perform a clean
   command-line build with the pinned ST toolchain.

The static tests check that all seven files exist, contain no common absolute
developer paths, preserve `-O0`, omit the cyclomatic-complexity flag, and use
the relative linker script. They also check the durable `.cproject` setting so a
later CubeIDE regeneration cannot silently reintroduce the absolute path.

## Release artifact flow

For a merged pull request with a `release:firmware:*` label, the release workflow:

1. bumps `FIRMWARE_VERSION` in `firmware/Core/Inc/firmware_version.h`;
2. appends the PR's firmware release note to `firmware/CHANGELOG.md`;
3. creates the firmware release commit and `firmware-v<version>` tag;
4. installs and verifies the pinned ST compiler bundle;
5. runs the clean Make build against that exact release commit;
6. publishes `turntable_firmware_<version>.elf` and its SHA-256 checksum.

If the same pull request also releases the controller, firmware is prepared
first so the controller release snapshots the newly released firmware version.

## Verification boundary

A successful compile proves that the source and pinned toolchain can produce an
ELF. Static tests prove properties of the stored build descriptions. Neither
proves motor behavior, coordinate correctness, stop behavior, electrical
assumptions, or safe operation of the physical table. Those claims require
bench or hardware-in-the-loop testing and must be reported separately.
