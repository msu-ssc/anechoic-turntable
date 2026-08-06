"""Static checks for the version-controlled firmware build description."""

from __future__ import annotations

import re
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).parents[1]
DEBUG_DIRECTORY = REPOSITORY_ROOT / "firmware/Debug"
PROJECT_CONFIGURATION = REPOSITORY_ROOT / "firmware/.cproject"
BUILD_DESCRIPTIONS = (
    DEBUG_DIRECTORY / "makefile",
    DEBUG_DIRECTORY / "sources.mk",
    DEBUG_DIRECTORY / "objects.mk",
    DEBUG_DIRECTORY / "objects.list",
    DEBUG_DIRECTORY / "Core/Src/subdir.mk",
    DEBUG_DIRECTORY / "Core/Startup/subdir.mk",
    DEBUG_DIRECTORY / "Drivers/STM32F4xx_HAL_Driver/Src/subdir.mk",
)


def test_required_cubeide_build_descriptions_are_present() -> None:
    """A clean checkout contains every file needed by GNU make."""
    assert all(path.is_file() for path in BUILD_DESCRIPTIONS)


def test_firmware_build_descriptions_are_portable() -> None:
    """Generated build descriptions contain no developer-specific absolute paths."""
    combined = "\n".join(path.read_text(encoding="utf-8") for path in BUILD_DESCRIPTIONS)

    assert "/home/" not in combined
    assert "/Users/" not in combined
    assert re.search(r"(?im)(?:^|[\"'])\s*[A-Z]:[\\/]", combined) is None
    assert '-T"../STM32F407VETX_FLASH.ld"' in combined


def test_cubeide_project_preserves_relative_linker_script() -> None:
    """CubeIDE regeneration cannot reintroduce a workspace-specific linker path."""
    project_configuration = PROJECT_CONFIGURATION.read_text(encoding="utf-8")

    assert project_configuration.count('value="../STM32F407VETX_FLASH.ld"') == 2
    assert "${workspace_loc:/${ProjName}/STM32F407VETX_FLASH.ld}" not in project_configuration


def test_firmware_build_preserves_unoptimized_profile() -> None:
    """The published firmware build remains explicitly unoptimized."""
    compile_rules = "\n".join(path.read_text(encoding="utf-8") for path in BUILD_DESCRIPTIONS if path.name == "subdir.mk" and "Startup" not in path.parts)

    assert " -O0 " in compile_rules
    assert " -O1 " not in compile_rules
    assert " -O2 " not in compile_rules
    assert " -O3 " not in compile_rules
    assert " -Os " not in compile_rules
    assert "-fcyclomatic-complexity" not in compile_rules


def test_firmware_version_command_uses_canonical_version_header() -> None:
    """The firmware reports its canonical version for the exact VERSION command."""
    main_source = (REPOSITORY_ROOT / "firmware/Core/Src/main.c").read_text(encoding="utf-8")

    assert '#include "firmware_version.h"' in main_source
    assert 'strcmp(command_to_process, "CMD:VERSION") == 0' in main_source
    assert '"MSG:VERSION:" FIRMWARE_VERSION ";\\r\\n"' in main_source


def test_counter_commands_use_exact_frames_and_existing_degree_targets() -> None:
    """Counter commands parse exact fields before entering existing movement."""

    main_source = (REPOSITORY_ROOT / "firmware/Core/Src/main.c").read_text(encoding="utf-8")

    assert '"CMD:MOV_CNT:PAN="' in main_source
    assert '"CMD:SET_CNT:PAN="' in main_source
    assert '"CMD:CNT:PAN="' not in main_source
    assert "move_yaw = ((float)azimuth_counter - 43200.0f) / 240.0f;" in main_source
    assert "move_pitch = ((float)elevation_counter - 21600.0f) / 240.0f;" in main_source
    assert "if (is_move_command || is_counter_move_command)" in main_source
