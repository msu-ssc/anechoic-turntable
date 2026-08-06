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

Firmware also accepts `CMD:CNT;` to query the raw encoder counters and
`CMD:CNT:PAN=<pan-counter>,TILT=<tilt-counter>;` to stop motion and set them
directly. Both commands return
`MSG:CNT:PAN=<pan-counter>,TILT=<tilt-counter>;` followed by CRLF. These are
diagnostic operations; setting counters changes the coordinate frame. See
[`docs/protocol.md`](../docs/protocol.md) for exact framing and numeric rules.

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
