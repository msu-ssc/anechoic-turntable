"""Static checks for the version-controlled firmware build description."""

from __future__ import annotations

import re
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).parents[1]
DEBUG_DIRECTORY = REPOSITORY_ROOT / "firmware/Debug"
PROJECT_CONFIGURATION = REPOSITORY_ROOT / "firmware/.cproject"
CMAKE_CONFIGURATION = REPOSITORY_ROOT / "firmware/cmake/stm32cubemx/CMakeLists.txt"
VSCODE_CONFIGURATION = REPOSITORY_ROOT / ".vscode/settings.json"
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


def test_cmake_build_description_is_machine_independent() -> None:
    """CMake uses repository or environment-relative paths, not a developer path."""
    cmake_configuration = CMAKE_CONFIGURATION.read_text(encoding="utf-8")

    assert "/home/" not in cmake_configuration
    assert "/Users/" not in cmake_configuration
    assert re.search(r"(?im)(?:^|[\"'])\s*[A-Z]:[\\/]", cmake_configuration) is None
    assert "${CMAKE_CURRENT_SOURCE_DIR}/../../Drivers" in cmake_configuration
    assert "../../Core/Startup/startup_stm32f407vetx.s" in cmake_configuration

    gcc_toolchain = (REPOSITORY_ROOT / "firmware/cmake/gcc-arm-none-eabi.cmake").read_text(encoding="utf-8")
    assert "STM32F407VETX_FLASH.ld" in gcc_toolchain
    assert "STM32F407xx_FLASH.ld" not in gcc_toolchain


def test_vscode_cmake_configuration_is_machine_independent() -> None:
    """The shared VS Code configuration does not name a host tool installation."""
    vscode_configuration = VSCODE_CONFIGURATION.read_text(encoding="utf-8")

    assert '"cmake.sourceDirectory": "${workspaceFolder}/firmware"' in vscode_configuration
    assert '"cmake.cmakePath"' not in vscode_configuration
    assert '"PATH"' not in vscode_configuration


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
