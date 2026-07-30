"""A small ``cmd.Cmd`` shell for the threaded turntable controller."""

from __future__ import annotations

import cmd
import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal
from typing import TextIO

from anechoic_turntable.controller import TurntableError
from anechoic_turntable.turntable import Turntable

_NUMBER = r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)"
_COORDINATE = re.compile(rf"(?P<axis>az|el)=(?P<value>{_NUMBER})\Z")


class CommandSyntaxError(ValueError):
    """Raised when coordinate arguments are malformed."""


@dataclass(frozen=True)
class Coordinates:
    """Physical azimuth and elevation parsed from command arguments."""

    azimuth: float
    elevation: float


def parse_coordinates(arguments: str) -> Coordinates:
    """Parse exactly one ``az=`` and one ``el=`` argument in either order."""

    tokens = arguments.split()
    if len(tokens) != 2:
        raise CommandSyntaxError("expected: az=<number> el=<number>")

    values: dict[str, float] = {}
    for token in tokens:
        match = _COORDINATE.fullmatch(token)
        if match is None:
            raise CommandSyntaxError("expected: az=<number> el=<number>")

        axis = match.group("axis")
        if axis in values:
            raise CommandSyntaxError(f"{axis}= may only be given once")
        values[axis] = float(match.group("value"))

    if values.keys() != {"az", "el"}:
        raise CommandSyntaxError("both az= and el= are required")

    return Coordinates(azimuth=values["az"], elevation=values["el"])


class TurntableShell(cmd.Cmd):
    """Interactive diagnostic shell for the turntable controller."""

    intro = "Anechoic turntable controller. Type 'help' for commands."
    prompt = "turntable> "

    def __init__(
        self,
        *,
        connector: Callable[[], Turntable] = Turntable.find,
        stdin: TextIO | None = None,
        stdout: TextIO | None = None,
    ) -> None:
        super().__init__(stdin=stdin, stdout=stdout)
        self._connector = connector
        self._turntable: Turntable | None = None

    def do_connect(self, arguments: str) -> None:
        """Attempt to connect, stopping and replacing any current connection."""

        if not self._require_no_arguments("connect", arguments):
            return

        self.close()
        self._write("connecting...")
        try:
            self._turntable = self._connector()
        except Exception as exc:  # noqa: BLE001 - keep the diagnostic shell alive
            self._write(f"connection failed: {exc}")
            return
        self._write(f"connected: {self._turntable.port}")

    def do_info(self, arguments: str) -> None:
        """Show the current controller state and physical position."""

        if not self._require_no_arguments("info", arguments):
            return
        if self._turntable is None:
            self._write("state=disconnected")
            return

        snapshot = self._turntable.get_complete_state()
        parts = [
            f"state={snapshot.state.value}",
            f"activity={snapshot.activity.value}",
        ]
        if snapshot.corrected_position is None:
            parts.extend(("az=?", "el=?"))
        else:
            parts.extend(
                (
                    f"az={snapshot.corrected_position.pan:.3f}",
                    f"el={snapshot.corrected_position.tilt:.3f}",
                )
            )
        if snapshot.target_position is not None:
            parts.extend(
                (
                    f"target_az={snapshot.target_position.pan:.3f}",
                    f"target_el={snapshot.target_position.tilt:.3f}",
                )
            )
        if snapshot.last_error is not None:
            parts.append(f"error={snapshot.last_error}")
        self._write(" ".join(parts))

    def do_set(self, arguments: str) -> None:
        """Set the reported position: set az=<number> el=<number>."""

        self._queue_position("set", arguments)

    def do_mov(self, arguments: str) -> None:
        """Move to a physical position: mov az=<number> el=<number>."""

        self._queue_position("mov", arguments)

    def do_exit(self, arguments: str) -> bool:
        """Stop the turntable, close the connection, and exit."""

        if not self._require_no_arguments("exit", arguments):
            return False
        self.close()
        return True

    def do_EOF(self, arguments: str) -> bool:
        """Stop the turntable, close the connection, and exit on EOF."""

        self._write("")
        return self.do_exit(arguments)

    def close(self) -> None:
        """Safely stop and close the current connection, if any."""

        turntable = self._turntable
        self._turntable = None
        if turntable is None:
            return

        try:
            turntable.abort()
        except Exception as exc:  # noqa: BLE001 - still close after a failed stop
            self._write(f"warning: stop failed: {exc}")
        try:
            turntable.close()
        except Exception as exc:  # noqa: BLE001 - report cleanup failure
            self._write(f"warning: disconnect failed: {exc}")

    def _queue_position(
        self,
        command: Literal["set", "mov"],
        arguments: str,
    ) -> None:
        try:
            coordinates = parse_coordinates(arguments)
        except CommandSyntaxError as exc:
            self._write(f"error: {exc}")
            return
        turntable = self._turntable
        if turntable is None:
            self._write("error: not connected")
            return

        try:
            operation = turntable.set_position if command == "set" else turntable.move_to
            operation(pan=coordinates.azimuth, tilt=coordinates.elevation)
        except (TurntableError, ValueError) as exc:
            self._write(f"error: {exc}")
            return
        self._write(f"{command} queued: az={coordinates.azimuth:.3f} el={coordinates.elevation:.3f}")

    def _require_no_arguments(self, command: str, arguments: str) -> bool:
        if arguments:
            self._write(f"error: {command} takes no arguments")
            return False
        return True

    def _write(self, message: str) -> None:
        print(message, file=self.stdout)


def main() -> None:
    """Run the interactive turntable diagnostic shell."""

    shell = TurntableShell()
    try:
        shell.cmdloop()
    except KeyboardInterrupt:
        print(file=shell.stdout)
    finally:
        shell.close()


if __name__ == "__main__":
    main()
