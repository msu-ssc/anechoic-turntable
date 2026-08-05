# LEMS Anechoic chamber turntable firmware

This is code written by Dr. Elijah Jensen. It was given to David Mayo by Jody
Caudill on 2025-02-17.

## Controller compatibility

The Python controller sends requested physical elevation directly as firmware
pitch; it no longer performs elevation-regime SET operations. Compatible
firmware therefore requires the expanded TIM1 encoder period of `43200`, with
zero elevation at count `21600`, as configured in `chambermotorcontrol.ioc` and
`Core/Src/main.c`.

Do not use the direct-coordinate controller with the historical TIM1 period of
`14400`. Its elevation counter cannot represent the controller's complete
`[-90°, 45°]` move range without rollover. The current bounds are inclusive and
do not yet provide an overshoot margin at exact counter endpoints.

## Command-line build

The version-controlled STM32CubeIDE managed-build descriptions under `Debug/`
allow a clean checkout to build the firmware without the complete IDE:

```shell
make -C firmware/Debug clean all
arm-none-eabi-size firmware/Debug/chambermotorcontrol.elf
```

The complete build contract—including the pinned compiler, `-O0` profile,
tracked generated inputs, relative linker configuration, regeneration process,
and verification boundaries—is documented in
[Firmware build](../docs/firmware-build.md).

## Portable CMake build

The CMake presets work on Windows, Linux, and macOS when `cmake`, `ninja`, and
the pinned ST `arm-none-eabi` toolchain are available on `PATH`:

```shell
cd firmware
cmake --preset Debug
cmake --build --preset Debug
```

CMake uses the HAL and CMSIS sources under `Drivers/` in a normal checkout. If
CubeMX has removed those local files, it also checks the standard
`STM32Cube/Repository/STM32Cube_FW_F4_V1.28.1` directory below the current
user's home directory. As a final portable override, `STM32CUBE_F4_PATH` may
name the STM32Cube F4 package directory. No developer-specific absolute path is
stored in the project.

The output is `build/Debug/chambermotorcontrol.elf`. This CMake build is useful
for local development; the release-reproducible build contract remains the
CubeIDE-generated GNU Make build described above.

## Firmware releases

`Core/Inc/firmware_version.h` is the canonical firmware version and
`CHANGELOG.md` is the firmware release history. Pull requests select a semantic
version bump with one `release:firmware:*` label and provide the corresponding
note in the pull-request template. After merge, automation builds the exact
firmware release commit and publishes:

- tag `firmware-v<version>`;
- artifact `turntable_firmware_<version>.elf`;
- artifact `turntable_firmware_<version>.elf.sha256`.

The firmware includes this version in the executable and reports it in response
to `CMD:VERSION;` as `MSG:VERSION:<version>;` followed by CRLF. Release
provenance also includes the tag, release commit, asset name, and checksum.
