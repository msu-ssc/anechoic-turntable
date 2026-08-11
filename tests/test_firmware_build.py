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
    assert 'strcmp(commandToProcess, "CMD:VERSION") == 0' in main_source
    assert '"MSG:VERSION:" FIRMWARE_VERSION ";\\r\\n"' in main_source


def test_counter_commands_use_exact_frames_and_existing_degree_targets() -> None:
    """Counter commands parse exact fields before entering existing movement."""

    main_source = (REPOSITORY_ROOT / "firmware/Core/Src/main.c").read_text(encoding="utf-8")
    global_constants = (REPOSITORY_ROOT / "firmware/Core/Inc/globalvars.h").read_text(encoding="utf-8")

    assert '"CMD:MOV_CNT:PAN="' in main_source
    assert '"CMD:SET_CNT:PAN="' in main_source
    assert '"CMD:CNT:PAN="' not in main_source
    assert "static const uint32_t PAN_ZERO_DEGREE_COUNTER = 50000U;" in global_constants
    assert "static const uint32_t TILT_ZERO_DEGREE_COUNTER = 30000U;" in global_constants
    assert "(float)PAN_ZERO_DEGREE_COUNTER" in main_source
    assert "(float)TILT_ZERO_DEGREE_COUNTER" in main_source
    assert "requestedPan = panCounterToDegrees(panCounter);" in main_source
    assert "requestedTilt = tiltCounterToDegrees(tiltCounter);" in main_source
    assert "TIM1->CNT = tiltDegreesToCounter(setTiltDegrees);" in main_source
    assert "TIM2->CNT = panDegreesToCounter(setPanDegrees);" in main_source
    assert "case COMMAND_MOV_CNT:" in main_source
    assert "case COMMAND_MOV:" in main_source


def test_firmware_uses_expanded_tilt_counter_period() -> None:
    """Generated firmware and Cube configuration use the same TIM1 period."""

    main_source = (REPOSITORY_ROOT / "firmware/Core/Src/main.c").read_text(encoding="utf-8")
    cube_configuration = (REPOSITORY_ROOT / "firmware/chambermotorcontrol.ioc").read_text(encoding="utf-8")

    assert "htim1.Init.Period = 60000;" in main_source
    assert "TIM1.Period=60000" in cube_configuration


def test_firmware_position_report_uses_exact_pan_tilt_frame_and_precision() -> None:
    """Position reports preserve encoder resolution in the current wire frame."""
    main_source = (REPOSITORY_ROOT / "firmware/Core/Src/main.c").read_text(encoding="utf-8")

    assert '"MSG:POS:PAN=%.3f,TILT=%.3f\\r\\n"' in main_source


def test_firmware_acknowledges_accepted_and_rejected_commands() -> None:
    """Command results and emergency stop use exact ACK/NAK framing."""

    main_source = (REPOSITORY_ROOT / "firmware/Core/Src/main.c").read_text(encoding="utf-8")

    assert '"MSG:ACK:%s;\\r\\n"' in main_source
    assert '"MSG:NAK:%s,%s;\\r\\n"' in main_source
    assert 'sendAcknowledgement("EMERGENCY_STOP", true, NULL);' in main_source
    assert 'sendAcknowledgement("UNKNOWN", false, "UNABLE_TO_PARSE");' in main_source
    assert "commandRejected = commandParsed" in main_source
    assert '? "OUT_OF_BOUNDS"' in main_source


def test_firmware_resets_completion_state_when_accepting_a_move() -> None:
    """A new MOV or MOV_CNT cannot inherit target-reached flags."""

    main_source = (REPOSITORY_ROOT / "firmware/Core/Src/main.c").read_text(encoding="utf-8")

    assert "float requestedPan = 0.0f;" in main_source
    assert "float requestedTilt = 0.0f;" in main_source
    assert "float move_pan = 0.0f;" not in main_source
    assert "float move_tilt = 0.0f;" not in main_source
    movement_activation = re.search(
        r"case COMMAND_MOV:\s+\{.*?"
        r"commandedPanDegrees = requestedPan;\s+"
        r"commandedTiltDegrees = requestedTilt;\s+"
        r"panTargetReached = false;\s+"
        r"tiltTargetReached = false;\s+"
        r"movementActive = true;",
        main_source,
        re.DOTALL,
    )
    assert movement_activation is not None


def test_firmware_stops_on_position_discontinuity() -> None:
    """A moving counter jump greater than one degree fails safe."""

    main_source = (REPOSITORY_ROOT / "firmware/Core/Src/main.c").read_text(encoding="utf-8")
    global_variables = (REPOSITORY_ROOT / "firmware/Core/Inc/globalvars.h").read_text(encoding="utf-8")

    assert "static const uint32_t MAX_POSITION_CHANGE_COUNTS = 240U;" in global_variables
    assert "positionDiscontinuityBaselineValid && movementActive" in main_source
    assert "change > maximumChange" in main_source
    assert '"MSG:ERR:POSITION_DISCONTINUITY;\\r\\n"' in main_source
    assert "previousPanCounter = TIM2->CNT;" in main_source
    assert "previousTiltCounter = TIM1->CNT;" in main_source


def test_firmware_stops_when_movement_times_out() -> None:
    """An active movement exceeding five minutes fails safe."""

    main_source = (REPOSITORY_ROOT / "firmware/Core/Src/main.c").read_text(encoding="utf-8")
    global_variables = (REPOSITORY_ROOT / "firmware/Core/Inc/globalvars.h").read_text(encoding="utf-8")

    assert "static const uint32_t MOVEMENT_TIMEOUT_MS = 300000U;" in global_variables
    assert "movementStartedTick = currentTick;" in main_source
    assert "movementActive && !targetReachedAtCurrentSample" in main_source
    assert "(uint32_t)(currentTick - movementStartedTick) >= MOVEMENT_TIMEOUT_MS" in main_source
    assert '"MSG:ERR:MOVEMENT_TIMEOUT;\\r\\n"' in main_source


def test_firmware_stops_when_a_commanded_axis_stalls() -> None:
    """Either commanded axis unchanged between three-second checks fails safe."""

    main_source = (REPOSITORY_ROOT / "firmware/Core/Src/main.c").read_text(encoding="utf-8")
    global_variables = (REPOSITORY_ROOT / "firmware/Core/Inc/globalvars.h").read_text(encoding="utf-8")

    assert "static const uint32_t MOVEMENT_STALL_CHECK_INTERVAL_MS = 3000U;" in global_variables
    assert "(int32_t)(currentTick - nextMovementCheckTick) >= 0" in main_source
    assert "panPositionCounter == panCounterAtLastMovementCheck" in main_source
    assert "tiltPositionCounter == tiltCounterAtLastMovementCheck" in main_source
    assert "panShouldMove" in main_source
    assert "tiltShouldMove" in main_source
    assert "nextMovementCheckTick = currentTick + MOVEMENT_STALL_CHECK_INTERVAL_MS;" in main_source
    assert "resetMovementStallWatchdog(currentTick);" in main_source
    assert '"MSG:ERR:MOVEMENT_STALLED;\\r\\n"' in main_source


def test_firmware_motor_control_uses_documented_named_constants() -> None:
    """Motor tuning values are named and the old opaque expressions are gone."""

    main_source = (REPOSITORY_ROOT / "firmware/Core/Src/main.c").read_text(encoding="utf-8")
    global_constants = (REPOSITORY_ROOT / "firmware/Core/Inc/globalvars.h").read_text(encoding="utf-8")

    for constant in (
        "PAN_PWM_CONTROL_WINDOW_DEG",
        "PAN_PWM_COEFFICIENT",
        "PAN_PWM_INTERCEPT",
        "TILT_PWM_CONTROL_WINDOW_DEG",
        "TILT_PWM_COEFFICIENT",
        "TILT_PWM_INTERCEPT",
        "TARGET_TOLERANCE_DEG",
        "MAX_PWM_POWER_LEVEL",
    ):
        assert constant in global_constants
        assert constant in main_source

    assert "pan_deviation*78+99" not in main_source
    assert "tilt_deviation*96+63" not in main_source
    assert "MYPROG_" not in main_source
