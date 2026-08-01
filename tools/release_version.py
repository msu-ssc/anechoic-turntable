"""Synchronize release versions from their canonical repository files."""

from __future__ import annotations

import argparse
import re
from datetime import datetime
from datetime import timezone
from pathlib import Path

VERSION_MODULE = Path("src/anechoic_turntable/_version.py")
PROTOCOL_DOCUMENT = Path("docs/protocol.md")
FIRMWARE_VERSION_HEADER = Path("firmware/Core/Inc/firmware_version.h")
CONTROLLER_CHANGELOG = Path("CHANGELOG.md")
FIRMWARE_CHANGELOG = Path("firmware/CHANGELOG.md")

SEMVER_TEXT = r"(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)"
CONTROLLER_PATTERN = re.compile(rf'^CONTROLLER_VERSION = "(?P<version>{SEMVER_TEXT})"$', re.MULTILINE)
PROTOCOL_PATTERN = re.compile(rf"^PROTOCOL_VERSION=(?P<version>{SEMVER_TEXT})$", re.MULTILINE)
FIRMWARE_PATTERN = re.compile(rf'^#define FIRMWARE_VERSION "(?P<version>{SEMVER_TEXT})"$', re.MULTILINE)


def _read_required_version(path: Path, pattern: re.Pattern[str], description: str) -> str:
    """Read one strictly formatted semantic version from a required file."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as error:
        raise ValueError(f"Unable to read {description} from {path}: {error}") from error

    match = pattern.search(text)
    if match is None:
        raise ValueError(f"Unable to find a valid {description} in {path}")
    return match.group("version")


def read_controller_version(repository_root: Path) -> str:
    """Read the canonical controller version from the Python version module."""
    return _read_required_version(repository_root / VERSION_MODULE, CONTROLLER_PATTERN, "controller version")


def read_protocol_version(repository_root: Path) -> str:
    """Read the canonical protocol version from the protocol contract."""
    return _read_required_version(repository_root / PROTOCOL_DOCUMENT, PROTOCOL_PATTERN, "protocol version")


def read_reference_firmware_version(repository_root: Path) -> str:
    """Read the repository firmware version, or return 0.0.0 when unavailable."""
    header = repository_root / FIRMWARE_VERSION_HEADER
    try:
        text = header.read_text(encoding="utf-8")
    except OSError:
        return "0.0.0"

    match = FIRMWARE_PATTERN.search(text)
    if match is None:
        raise ValueError(f"Unable to find a valid firmware version in {header}")
    return match.group("version")


def read_firmware_version(repository_root: Path) -> str:
    """Read the required canonical firmware version."""
    return _read_required_version(repository_root / FIRMWARE_VERSION_HEADER, FIRMWARE_PATTERN, "firmware version")


def bump_version(version: str, bump_type: str) -> str:
    """Apply a major, minor, or patch bump to a release-version triplet."""
    match = re.fullmatch(SEMVER_TEXT, version)
    if match is None:
        raise ValueError(f"Not a simple semantic release version: {version!r}")

    major, minor, patch = (int(part) for part in version.split("."))
    if bump_type == "major":
        major, minor, patch = major + 1, 0, 0
    elif bump_type == "minor":
        minor, patch = minor + 1, 0
    elif bump_type == "patch":
        patch += 1
    else:
        raise ValueError(f"Unsupported bump type: {bump_type!r}")
    return f"{major}.{minor}.{patch}"


def _replace_assignment(text: str, name: str, version: str) -> str:
    pattern = re.compile(rf'^{re.escape(name)} = "[^"]+"$', re.MULTILINE)
    updated, count = pattern.subn(f'{name} = "{version}"', text, count=1)
    if count != 1:
        raise ValueError(f"Expected exactly one {name} assignment in {VERSION_MODULE}")
    return updated


def synchronize_controller_versions(repository_root: Path, bump_type: str) -> str:
    """Bump the controller and snapshot canonical compatibility versions."""
    version_path = repository_root / VERSION_MODULE
    controller_version = bump_version(read_controller_version(repository_root), bump_type)
    protocol_version = read_protocol_version(repository_root)
    firmware_version = read_reference_firmware_version(repository_root)

    text = version_path.read_text(encoding="utf-8")
    text = _replace_assignment(text, "CONTROLLER_VERSION", controller_version)
    text = _replace_assignment(text, "PROTOCOL_VERSION", protocol_version)
    text = _replace_assignment(text, "REFERENCE_FIRMWARE_VERSION", firmware_version)
    version_path.write_text(text, encoding="utf-8")
    return controller_version


def synchronize_versions(repository_root: Path, bump_type: str) -> str:
    """Backward-compatible alias for synchronizing controller versions."""
    return synchronize_controller_versions(repository_root, bump_type)


def bump_firmware_version(repository_root: Path, bump_type: str) -> str:
    """Bump the canonical firmware version header."""
    header = repository_root / FIRMWARE_VERSION_HEADER
    firmware_version = bump_version(read_firmware_version(repository_root), bump_type)
    text = header.read_text(encoding="utf-8")
    updated, count = FIRMWARE_PATTERN.subn(f'#define FIRMWARE_VERSION "{firmware_version}"', text, count=1)
    if count != 1:
        raise ValueError(f"Expected exactly one FIRMWARE_VERSION definition in {FIRMWARE_VERSION_HEADER}")
    header.write_text(updated, encoding="utf-8")
    return firmware_version


def append_changelog_entry(changelog: Path, version: str, release_date: str, note: str) -> None:
    """Append one component release entry to the changelog."""
    existing = changelog.read_text(encoding="utf-8") if changelog.exists() else "# Changelog\n"
    changelog.write_text(
        f"{existing.rstrip()}\n\n## {version} — {release_date}\n\n{note.strip()}\n",
        encoding="utf-8",
    )


def prepare_controller_release(repository_root: Path, bump_type: str, release_date: str, note: str) -> str:
    """Prepare canonical files for one controller release."""
    version = synchronize_controller_versions(repository_root, bump_type)
    append_changelog_entry(repository_root / CONTROLLER_CHANGELOG, version, release_date, note)
    return version


def prepare_firmware_release(repository_root: Path, bump_type: str, release_date: str, note: str) -> str:
    """Prepare canonical files for one firmware release."""
    version = bump_firmware_version(repository_root, bump_type)
    append_changelog_entry(repository_root / FIRMWARE_CHANGELOG, version, release_date, note)
    return version


def _add_release_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("bump_type", choices=("major", "minor", "patch"))
    parser.add_argument("--release-date", default=datetime.now(timezone.utc).date().isoformat())
    parser.add_argument("--release-note-file", type=Path, required=True)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository-root", type=Path, default=Path.cwd())
    subparsers = parser.add_subparsers(dest="command", required=True)

    controller_parser = subparsers.add_parser("controller", help="prepare a controller release")
    _add_release_arguments(controller_parser)
    firmware_parser = subparsers.add_parser("firmware", help="prepare a firmware release")
    _add_release_arguments(firmware_parser)
    return parser


def main() -> None:
    """Run the release-version helper."""
    arguments = _build_parser().parse_args()
    repository_root = arguments.repository_root.resolve()
    note = arguments.release_note_file.read_text(encoding="utf-8")
    if arguments.command == "controller":
        version = prepare_controller_release(repository_root, arguments.bump_type, arguments.release_date, note)
    else:
        version = prepare_firmware_release(repository_root, arguments.bump_type, arguments.release_date, note)
    print(version)


if __name__ == "__main__":
    main()
