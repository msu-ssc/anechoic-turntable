from __future__ import annotations

import csv
import threading
from types import SimpleNamespace

import pytest
from textual.widgets import Button
from textual.widgets import Label

from anechoic_turntable import PanTilt
from anechoic_turntable import TurntableActivity
from anechoic_turntable import TurntableState
from anechoic_turntable.pwm_experiment import ExperimentConfig
from anechoic_turntable.pwm_experiment import PwmExperimentApp
from anechoic_turntable.pwm_experiment import PwmExperimentRunner
from anechoic_turntable.pwm_experiment import _default_output_path
from anechoic_turntable.pwm_experiment import linspace


class FakeTurntable:
    port = "/dev/fake-pwm"

    def __init__(self) -> None:
        self.position = PanTilt(0, 0)
        self.pwm = 0
        self.pwm_commands: list[int] = []
        self.abort_count = 0
        self.confirm_count = 0
        self.closed = False

    def move_to(self, *, pan, tilt) -> None:
        self.position = PanTilt(pan, tilt)

    def current_position(self) -> PanTilt:
        if self.pwm:
            self.position = PanTilt(self.position.pan + (0.025 if self.pwm > 0 else -0.025), self.position.tilt)
        return self.position

    def get_complete_state(self):
        return SimpleNamespace(
            state=TurntableState.STOPPED,
            activity=TurntableActivity.IDLE,
            queued_command_count=0,
            corrected_position=self.position,
        )

    def set_azimuth_pwm(self, power: int) -> None:
        self.pwm = power
        self.pwm_commands.append(power)

    def abort(self) -> None:
        self.pwm = 0
        self.abort_count += 1

    def confirm_position(self) -> None:
        self.confirm_count += 1

    def close(self) -> None:
        self.closed = True


def compact_config(tmp_path) -> ExperimentConfig:
    return ExperimentConfig(
        output_path=tmp_path / "results.csv",
        tilt_min=-1,
        tilt_max=1,
        tilt_count=2,
        pan_min=-1,
        pan_max=1,
        pan_count=2,
        iterations=1,
        pwm_min=100,
        pwm_max=100,
        pwm_step=5,
        pulse_seconds=0.05,
        settle_seconds=0,
        approach_degrees=1,
        movement_counts=1,
        maximum_displacement_degrees=0.1,
    )


def test_linspace_includes_both_endpoints() -> None:
    assert linspace(-1, 1, 3) == (-1, 0, 1)
    with pytest.raises(ValueError, match="at least two"):
        linspace(0, 1, 1)


def test_runner_records_each_successful_direction_and_stops_output(tmp_path) -> None:
    table = FakeTurntable()
    config = compact_config(tmp_path)
    state_updates = []
    log_messages = []

    PwmExperimentRunner(
        table,  # type: ignore[arg-type]
        config,
        threading.Event(),
        state_callback=lambda status, progress, pwm: state_updates.append((status, progress, pwm)),
        log_callback=log_messages.append,
    ).run()

    with config.output_path.open(newline="", encoding="utf-8") as result_file:
        rows = list(csv.DictReader(result_file))
    assert len(rows) == 8
    assert {row["direction_name"] for row in rows} == {"left", "right"}
    assert all(row["started_moving"] == "True" for row in rows)
    assert table.pwm == 0
    assert table.abort_count >= len(rows)
    assert state_updates[-1][0] == "complete"
    assert any("trying PWM -100" in message for message in log_messages)
    assert any("PWM -100: movement detected" in message for message in log_messages)
    assert any("threshold PWM magnitude 100" in message for message in log_messages)


def test_default_output_path_creates_local_directory(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)

    output_path = _default_output_path()

    assert output_path.parent == tmp_path / "local"
    assert output_path.parent.is_dir()
    assert output_path.name.startswith("azimuth_pwm_experiment_")
    assert output_path.suffix == ".csv"


def test_config_requires_room_for_repeatable_approach(tmp_path) -> None:
    config = compact_config(tmp_path)
    invalid = ExperimentConfig(**{**config.__dict__, "pan_min": -179.5, "approach_degrees": 1})

    with pytest.raises(ValueError, match="approach distance"):
        invalid.validate()


def test_experiment_tui_shows_live_values_and_large_stop_button(tmp_path) -> None:
    async def exercise() -> None:
        table = FakeTurntable()
        table.position = PanTilt(12.5, -4.0)
        app = PwmExperimentApp(compact_config(tmp_path), connector=lambda: table, refresh_interval=60)  # type: ignore[arg-type]

        async with app.run_test(size=(100, 32)) as pilot:
            await pilot.pause()
            app._set_ui_state("applying PWM", "candidate=130", -130)
            app.refresh_display()

            assert "pan=12.500" in str(app.query_one("#position", Label).render())
            assert str(app.query_one("#pwm", Label).render()) == "Current PWM: -130"
            stop_button = app.query_one("#stop-experiment", Button)
            assert str(stop_button.label) == "STOP EXPERIMENT"
            assert stop_button.region.height == 5

            await pilot.click("#stop-experiment")
            assert table.abort_count == 1

        assert table.closed
        assert table.abort_count == 2

    import asyncio

    asyncio.run(exercise())


def test_experiment_tui_start_button_confirms_position_and_runs(tmp_path) -> None:
    async def exercise() -> None:
        table = FakeTurntable()
        config = compact_config(tmp_path)
        app = PwmExperimentApp(config, connector=lambda: table, refresh_interval=0.01)  # type: ignore[arg-type]

        async with app.run_test(size=(100, 32)) as pilot:
            await pilot.pause()
            start_button = app.query_one("#start", Button)
            assert not start_button.disabled
            assert app._turntable is table
            assert not app._experiment_running
            clicked = await pilot.click("#start", offset=(10, 2))
            assert clicked
            await pilot.pause()

            assert table.confirm_count == 1

    import asyncio

    asyncio.run(exercise())
