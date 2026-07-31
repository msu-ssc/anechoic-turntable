"""Tests for controller and compatibility version metadata."""

from __future__ import annotations

import importlib.metadata
import importlib.util
from pathlib import Path
from types import ModuleType

import pytest

import anechoic_turntable

REPOSITORY_ROOT = Path(__file__).parents[1]


def _load_release_version_tool() -> ModuleType:
    spec = importlib.util.spec_from_file_location("release_version", REPOSITORY_ROOT / "tools/release_version.py")
    if spec is None or spec.loader is None:
        raise RuntimeError("Unable to load the release-version helper")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


release_version = _load_release_version_tool()


def test_public_controller_version_matches_installed_package() -> None:
    """The public controller version is also the installed distribution version."""
    assert anechoic_turntable.__version__ == anechoic_turntable.CONTROLLER_VERSION
    assert importlib.metadata.version("anechoic-turntable") == anechoic_turntable.CONTROLLER_VERSION


def test_protocol_snapshot_matches_canonical_contract() -> None:
    """The packaged protocol snapshot matches the authoritative protocol document."""
    assert release_version.read_protocol_version(REPOSITORY_ROOT) == anechoic_turntable.PROTOCOL_VERSION


def test_reference_firmware_snapshot_matches_available_header() -> None:
    """The firmware snapshot matches the header or its documented unknown fallback."""
    assert release_version.read_reference_firmware_version(REPOSITORY_ROOT) == anechoic_turntable.REFERENCE_FIRMWARE_VERSION


@pytest.mark.parametrize(
    ("current", "bump_type", "expected"),
    [
        ("1.2.3", "major", "2.0.0"),
        ("1.2.3", "minor", "1.3.0"),
        ("1.2.3", "patch", "1.2.4"),
        ("0.0.0", "minor", "0.1.0"),
    ],
)
def test_bump_version(current: str, bump_type: str, expected: str) -> None:
    """Release labels apply deterministic semantic-version triplet bumps."""
    assert release_version.bump_version(current, bump_type) == expected


def test_missing_firmware_header_uses_unknown_version(tmp_path: Path) -> None:
    """A source tree without the firmware header reports an unknown reference version."""
    assert release_version.read_reference_firmware_version(tmp_path) == "0.0.0"


def test_malformed_existing_firmware_header_is_rejected(tmp_path: Path) -> None:
    """An existing malformed canonical header cannot silently produce a release."""
    header = tmp_path / release_version.FIRMWARE_VERSION_HEADER
    header.parent.mkdir(parents=True)
    header.write_text('#define FIRMWARE_VERSION "banana"\n', encoding="utf-8")

    with pytest.raises(ValueError, match="valid firmware version"):
        release_version.read_reference_firmware_version(tmp_path)


def test_synchronize_versions_reads_canonical_sources(tmp_path: Path) -> None:
    """A release bump snapshots protocol and firmware canonical values."""
    version_module = tmp_path / release_version.VERSION_MODULE
    version_module.parent.mkdir(parents=True)
    version_module.write_text(
        'CONTROLLER_VERSION = "1.2.3"\nPROTOCOL_VERSION = "1.0.0"\nREFERENCE_FIRMWARE_VERSION = "1.1.0"\n__version__ = CONTROLLER_VERSION\n',
        encoding="utf-8",
    )
    protocol_document = tmp_path / release_version.PROTOCOL_DOCUMENT
    protocol_document.parent.mkdir(parents=True)
    protocol_document.write_text("# Contract\nPROTOCOL_VERSION=2.0.0\n", encoding="utf-8")
    firmware_header = tmp_path / release_version.FIRMWARE_VERSION_HEADER
    firmware_header.parent.mkdir(parents=True)
    firmware_header.write_text('#define FIRMWARE_VERSION "3.4.5"\n', encoding="utf-8")

    assert release_version.synchronize_versions(tmp_path, "minor") == "1.3.0"
    assert version_module.read_text(encoding="utf-8") == ('CONTROLLER_VERSION = "1.3.0"\nPROTOCOL_VERSION = "2.0.0"\nREFERENCE_FIRMWARE_VERSION = "3.4.5"\n__version__ = CONTROLLER_VERSION\n')


def test_append_changelog_entry_preserves_existing_history(tmp_path: Path) -> None:
    """A release appends one readable entry without replacing prior history."""
    changelog = tmp_path / "CHANGELOG.md"
    changelog.write_text("# Changelog\n\nEarlier history.\n", encoding="utf-8")

    release_version.append_changelog_entry(changelog, "1.2.3", "2026-07-31", "Useful change\n")

    assert changelog.read_text(encoding="utf-8") == ("# Changelog\n\nEarlier history.\n\n## 1.2.3 — 2026-07-31\n\nUseful change\n")
