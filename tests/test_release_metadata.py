"""Tests for pull-request release metadata validation."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

REPOSITORY_ROOT = Path(__file__).parents[1]


def _load_release_metadata_tool() -> ModuleType:
    spec = importlib.util.spec_from_file_location("release_metadata", REPOSITORY_ROOT / "tools/release_metadata.py")
    if spec is None or spec.loader is None:
        raise RuntimeError("Unable to load the release-metadata helper")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


release_metadata = _load_release_metadata_tool()


def _event(
    *,
    firmware: str | None = "minor",
    controller: str | None = None,
    release_none: bool = False,
    body: str | None = None,
) -> dict[str, object]:
    if body is None:
        body = """## Summary

Implementation details.

## Release notes

### Firmware

Build firmware releases automatically.

#### Safety

The compiler remains at `-O0`.

### Controller

<!-- Leave empty when the controller is not released. -->
"""
    labels = []
    if firmware is not None:
        labels.append({"name": f"release:firmware:{firmware}"})
    if controller is not None:
        labels.append({"name": f"release:controller:{controller}"})
    if release_none:
        labels.append({"name": "release:none"})
    return {
        "pull_request": {
            "labels": labels,
            "body": body,
        }
    }


def test_parse_release_metadata_supports_independent_components() -> None:
    """Labels control bumps while matching Markdown sections supply notes."""
    metadata = release_metadata.parse_pull_request_event(_event())

    assert metadata.firmware_bump == "minor"
    assert metadata.controller_bump == "no_bump"
    assert metadata.firmware_note == "Build firmware releases automatically.\n\n#### Safety\n\nThe compiler remains at `-O0`."
    assert metadata.controller_note == ""


def test_parse_release_metadata_accepts_combined_component_releases() -> None:
    """One firmware and one controller bump may be selected together."""
    body = """## Release notes

### Firmware

Firmware change.

### Controller

Controller change.
"""

    metadata = release_metadata.parse_pull_request_event(_event(controller="patch", body=body))

    assert metadata.firmware_bump == "minor"
    assert metadata.controller_bump == "patch"


def test_parse_release_metadata_accepts_release_none_by_itself() -> None:
    """The shared no-release label supplies no component bump."""
    metadata = release_metadata.parse_pull_request_event(_event(firmware=None, release_none=True))

    assert metadata.firmware_bump == "no_bump"
    assert metadata.controller_bump == "no_bump"


def test_parse_release_metadata_requires_at_least_one_release_label() -> None:
    """A pull request cannot omit all release metadata."""
    with pytest.raises(ValueError, match="Select at least one release label"):
        release_metadata.parse_pull_request_event(_event(firmware=None))


@pytest.mark.parametrize("component", ["firmware", "controller"])
def test_parse_release_metadata_rejects_multiple_labels_in_one_family(component: str) -> None:
    """Each component family permits at most one semantic bump."""
    event = _event(firmware=None, controller=None)
    labels = event["pull_request"]["labels"]  # type: ignore[index]
    labels.extend(
        [
            {"name": f"release:{component}:minor"},
            {"name": f"release:{component}:patch"},
        ]
    )

    with pytest.raises(ValueError, match=f"at most one {component} release label"):
        release_metadata.parse_pull_request_event(event)


def test_parse_release_metadata_rejects_release_none_with_component_label() -> None:
    """The no-release sentinel cannot contradict a component bump."""
    with pytest.raises(ValueError, match="release:none cannot be combined"):
        release_metadata.parse_pull_request_event(_event(release_none=True))


def test_parse_release_metadata_rejects_old_no_bump_component_label() -> None:
    """Only major, minor, and patch exist in component label families."""
    with pytest.raises(ValueError, match="Unsupported firmware release label"):
        release_metadata.parse_pull_request_event(_event(firmware="no_bump"))


def test_parse_release_metadata_rejects_missing_note_for_bump() -> None:
    """A component release requires an explicit human-readable note."""
    body = """## Release notes

### Firmware

<!-- No note supplied. -->

### Controller

No controller release.
"""

    with pytest.raises(ValueError, match="firmware release-note section is required"):
        release_metadata.parse_pull_request_event(_event(body=body))


def test_parse_release_metadata_ignores_same_named_heading_outside_release_notes() -> None:
    """Only component headings inside the release-note section are parsed."""
    body = """### Firmware

Design discussion.

## Release notes

### Firmware

Actual release note.

### Controller
"""

    metadata = release_metadata.parse_pull_request_event(_event(body=body))

    assert metadata.firmware_note == "Actual release note."


def test_write_metadata_creates_note_files_and_scalar_outputs(tmp_path: Path) -> None:
    """Workflow output keeps multiline notes in files rather than command strings."""
    metadata = release_metadata.parse_pull_request_event(_event())
    github_output = tmp_path / "github-output"

    release_metadata.write_metadata(metadata, tmp_path / "notes", github_output)

    assert (tmp_path / "notes/firmware-release-note.txt").read_text(encoding="utf-8").startswith("Build firmware")
    assert (tmp_path / "notes/controller-release-note.txt").read_text(encoding="utf-8") == "\n"
    assert github_output.read_text(encoding="utf-8") == ("firmware_bump=minor\ncontroller_bump=no_bump\nany_release=true\n")


def test_write_metadata_marks_release_none_as_no_release(tmp_path: Path) -> None:
    """The shared no-release label skips all post-merge release work."""
    metadata = release_metadata.parse_pull_request_event(_event(firmware=None, release_none=True))
    github_output = tmp_path / "github-output"

    release_metadata.write_metadata(metadata, tmp_path / "notes", github_output)

    assert github_output.read_text(encoding="utf-8") == ("firmware_bump=no_bump\ncontroller_bump=no_bump\nany_release=false\n")
