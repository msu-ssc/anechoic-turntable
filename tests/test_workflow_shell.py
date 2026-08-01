"""Syntax checks for shell scripts embedded in GitHub Actions workflows."""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_DIRECTORY = REPOSITORY_ROOT / ".github" / "workflows"
RUN_BLOCK_PATTERN = re.compile(r"^(?P<indent> *)run:\s*\|[+-]?\s*$")


@dataclass(frozen=True)
class WorkflowShellScript:
    """A shell script extracted from a workflow's literal ``run`` block."""

    workflow_path: Path
    line_number: int
    source: str

    @property
    def test_id(self) -> str:
        """Return a useful pytest parameter identifier."""
        relative_path = self.workflow_path.relative_to(REPOSITORY_ROOT)
        return f"{relative_path}:{self.line_number}"


def extract_workflow_shell_scripts() -> list[WorkflowShellScript]:
    """Extract literal ``run: |`` blocks from all workflow YAML files."""
    scripts: list[WorkflowShellScript] = []

    for workflow_path in sorted(WORKFLOW_DIRECTORY.glob("*.yml")):
        lines = workflow_path.read_text(encoding="utf-8").splitlines()
        for line_index, line in enumerate(lines):
            match = RUN_BLOCK_PATTERN.match(line)
            if match is None:
                continue

            block_indentation = len(match.group("indent"))
            content_indentation = block_indentation + 2
            source_lines: list[str] = []

            for source_line in lines[line_index + 1 :]:
                leading_spaces = len(source_line) - len(source_line.lstrip(" "))
                if source_line.strip() and leading_spaces <= block_indentation:
                    break
                source_lines.append(source_line[content_indentation:])

            scripts.append(
                WorkflowShellScript(
                    workflow_path=workflow_path,
                    line_number=line_index + 1,
                    source="\n".join(source_lines) + "\n",
                )
            )

    return scripts


WORKFLOW_SHELL_SCRIPTS = extract_workflow_shell_scripts()


@pytest.mark.parametrize(
    "script",
    WORKFLOW_SHELL_SCRIPTS,
    ids=[script.test_id for script in WORKFLOW_SHELL_SCRIPTS],
)
def test_workflow_shell_script_has_valid_bash_syntax(
    script: WorkflowShellScript,
) -> None:
    """Require every embedded workflow shell script to pass ``bash -n``."""
    result = subprocess.run(
        ["bash", "-n"],
        input=script.source,
        capture_output=True,
        check=False,
        text=True,
    )

    assert result.returncode == 0, result.stderr
