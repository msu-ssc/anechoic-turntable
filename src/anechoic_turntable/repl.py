"""A small ``cmd.Cmd`` shell for the threaded turntable controller."""

from __future__ import annotations

import cmd
from collections.abc import Callable
from typing import Literal
from typing import TextIO

from anechoic_turntable.controller import TurntableError
from anechoic_turntable.session import CommandSyntaxError
from anechoic_turntable.session import Coordinates
from anechoic_turntable.session import NotConnectedError
from anechoic_turntable.session import TurntableSession
from anechoic_turntable.session import parse_coordinates
from anechoic_turntable.turntable import Turntable

__all__ = [
    "CommandSyntaxError",
    "Coordinates",
    "TurntableShell",
    "main",
    "parse_coordinates",
]


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
        self._session = TurntableSession(connector=connector)

    def do_connect(self, arguments: str) -> None:
        """Attempt to connect, stopping and replacing any current connection."""

        if not self._require_no_arguments("connect", arguments):
            return

        self._write("connecting...")
        result = self._session.connect()
        self._write_cleanup_warnings(result.cleanup_warnings)
        if result.error is not None:
            self._write(f"connection failed: {result.error}")
            return
        self._write(f"connected: {result.port}")

    def do_info(self, arguments: str) -> None:
        """Show the current controller state and physical position."""

        if not self._require_no_arguments("info", arguments):
            return
        snapshot = self._session.get_complete_state()
        if snapshot is None:
            self._write("state=disconnected")
            return

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

    def do_confirm(self, arguments: str) -> None:
        """Approve the currently reported azimuth and elevation."""

        if not self._require_no_arguments("confirm", arguments):
            return
        try:
            position = self._session.confirm_position()
        except (TurntableError, ValueError) as exc:
            self._write(f"error: {exc}")
            return
        self._write(f"position confirmed: az={position.pan:.3f} el={position.tilt:.3f}")

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

        self._write_cleanup_warnings(self._session.close())

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
        try:
            self._session.queue_position(command, coordinates)
        except (NotConnectedError, TurntableError, ValueError) as exc:
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

    def _write_cleanup_warnings(self, warnings: tuple[str, ...]) -> None:
        for warning in warnings:
            self._write(f"warning: {warning}")


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
