"""Validate release labels and extract component notes from a pull request."""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

BUMP_TYPES = ("major", "minor", "patch")
COMPONENTS = ("firmware", "controller")
RELEASE_NONE_LABEL = "release:none"
HTML_COMMENT_PATTERN = re.compile(r"<!--.*?-->", re.DOTALL)
HEADING_PATTERN = re.compile(r"^(?P<marks>#{1,6})[ \t]+(?P<title>.*?)[ \t]*#*[ \t]*$", re.MULTILINE)


@dataclass(frozen=True)
class ReleaseMetadata:
    """Validated release choices and notes for one pull request."""

    firmware_bump: str
    controller_bump: str
    firmware_note: str
    controller_note: str


def select_bump(labels: list[str], component: str) -> str:
    """Return at most one component bump selected by a pull-request label."""
    if component not in COMPONENTS:
        raise ValueError(f"Unknown release component: {component}")

    prefix = f"release:{component}:"
    selected = [label.removeprefix(prefix) for label in labels if label.startswith(prefix)]
    invalid = [bump for bump in selected if bump not in BUMP_TYPES]
    if invalid:
        raise ValueError(f"Unsupported {component} release label: {prefix}{invalid[0]}")
    if len(selected) > 1:
        raise ValueError(f"Expected at most one {component} release label ({', '.join(prefix + bump for bump in BUMP_TYPES)}); found {len(selected)}")
    return selected[0] if selected else "no_bump"


def extract_release_note(body: str, component: str) -> str:
    """Extract one component's Markdown section under the PR release notes."""
    release_headings = [match for match in HEADING_PATTERN.finditer(body) if len(match.group("marks")) == 2 and match.group("title").strip().casefold() == "release notes"]
    if len(release_headings) != 1:
        raise ValueError(f"Expected exactly one '## Release notes' section; found {len(release_headings)}")

    release_heading = release_headings[0]
    release_end = len(body)
    for following in HEADING_PATTERN.finditer(body, release_heading.end()):
        if len(following.group("marks")) <= 2:
            release_end = following.start()
            break
    release_body = body[release_heading.end() : release_end]

    expected_title = component.casefold()
    matches = [match for match in HEADING_PATTERN.finditer(release_body) if len(match.group("marks")) == 3 and match.group("title").strip().casefold() == expected_title]
    if len(matches) != 1:
        raise ValueError(f"Expected exactly one '### {component.title()}' release-note section; found {len(matches)}")

    match = matches[0]
    end = len(release_body)
    for following in HEADING_PATTERN.finditer(release_body, match.end()):
        if len(following.group("marks")) <= 3:
            end = following.start()
            break

    return HTML_COMMENT_PATTERN.sub("", release_body[match.end() : end]).strip()


def parse_pull_request_event(event: dict[str, Any]) -> ReleaseMetadata:
    """Validate a GitHub pull-request event and return its release metadata."""
    try:
        pull_request = event["pull_request"]
        labels = [entry["name"] for entry in pull_request.get("labels", [])]
        body = pull_request.get("body") or ""
    except (KeyError, TypeError) as error:
        raise ValueError("Event does not contain a valid pull_request object") from error

    firmware_bump = select_bump(labels, "firmware")
    controller_bump = select_bump(labels, "controller")
    release_none_count = labels.count(RELEASE_NONE_LABEL)
    any_component_release = firmware_bump != "no_bump" or controller_bump != "no_bump"

    if release_none_count and any_component_release:
        raise ValueError(f"{RELEASE_NONE_LABEL} cannot be combined with a component release label")
    if not release_none_count and not any_component_release:
        raise ValueError("Select at least one release label: release:none, release:firmware:<bump>, or release:controller:<bump>")

    firmware_note = extract_release_note(body, "firmware")
    controller_note = extract_release_note(body, "controller")

    if firmware_bump != "no_bump" and not firmware_note:
        raise ValueError("The firmware release-note section is required for a firmware release")
    if controller_bump != "no_bump" and not controller_note:
        raise ValueError("The controller release-note section is required for a controller release")

    return ReleaseMetadata(firmware_bump, controller_bump, firmware_note, controller_note)


def write_metadata(metadata: ReleaseMetadata, output_directory: Path, github_output: Path | None = None) -> None:
    """Write notes to files and scalar metadata to an optional GitHub output file."""
    output_directory.mkdir(parents=True, exist_ok=True)
    (output_directory / "firmware-release-note.txt").write_text(f"{metadata.firmware_note}\n", encoding="utf-8")
    (output_directory / "controller-release-note.txt").write_text(f"{metadata.controller_note}\n", encoding="utf-8")

    if github_output is not None:
        any_release = metadata.firmware_bump != "no_bump" or metadata.controller_bump != "no_bump"
        with github_output.open("a", encoding="utf-8") as output:
            output.write(f"firmware_bump={metadata.firmware_bump}\n")
            output.write(f"controller_bump={metadata.controller_bump}\n")
            output.write(f"any_release={'true' if any_release else 'false'}\n")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--event-path", type=Path, required=True)
    parser.add_argument("--output-directory", type=Path, required=True)
    parser.add_argument("--github-output", type=Path)
    return parser


def main() -> None:
    """Validate one event and write release metadata for a workflow."""
    arguments = _build_parser().parse_args()
    try:
        event = json.loads(arguments.event_path.read_text(encoding="utf-8"))
        metadata = parse_pull_request_event(event)
        write_metadata(metadata, arguments.output_directory, arguments.github_output)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        raise SystemExit(f"Release metadata is invalid: {error}") from error


if __name__ == "__main__":
    main()
