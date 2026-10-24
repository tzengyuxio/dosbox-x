"""Drive DOSBox-X through its mcp_server debugger channel.

Started with ``-set "dosbox mcp_server=PORT"``, DOSBox-X connects to 127.0.0.1:PORT
(retrying every second) and runs each ``REQ <id> EXEC <command>`` line as a debugger
command, answering ``BEGIN <id> OK|ERR``, the output lines and ``END <id>``. Session
is the listening side; every call waits for its reply. Standard library only.

    session = Session(alive=lambda: proc.poll() is None)
    proc = subprocess.Popen([..., "-set", f"dosbox mcp_server={session.port}"])
    session.type("enter")
    png = session.shot(captures_dir)
"""

import socket
import time
from pathlib import Path
from typing import Callable, Iterable


class DosboxError(Exception):
    """A command was refused (ERR reply or unknown key)."""


class Stopped(DosboxError):
    """DOSBox-X went away, ``alive`` returned False, or a wait timed out."""


class Session:
    def __init__(self, port: int = 0, alive: Callable[[], bool] | None = None,
                 connect_timeout: float = 30.0, reply_timeout: float = 10.0):
        """Listen on 127.0.0.1:port (0 picks a free port, see ``self.port``).

        ``alive`` is polled while waiting; returning False raises Stopped.
        """
        self.server = socket.create_server(("127.0.0.1", port))
        self.server.settimeout(0.1)
        self.port = self.server.getsockname()[1]
        self.alive = alive or (lambda: True)
        self.connect_timeout = connect_timeout
        self.reply_timeout = reply_timeout
        self.connection: socket.socket | None = None
        self.received = b""
        self.next_id = 0

    def _check(self, deadline: float, what: str) -> None:
        if not self.alive():
            raise Stopped("DOSBox-X stopped")
        if time.monotonic() > deadline:
            raise Stopped(f"timed out waiting for {what}")

    def accept(self) -> None:
        """Wait until DOSBox-X connects."""
        deadline = time.monotonic() + self.connect_timeout
        while self.connection is None:
            self._check(deadline, "DOSBox-X to connect")
            try:
                self.connection, _ = self.server.accept()
            except TimeoutError:
                continue
            self.connection.settimeout(0.1)

    def execute(self, command: str) -> list[str]:
        """Run a debugger command and return its output lines; ERR raises DosboxError."""
        self.accept()
        self.next_id += 1
        request = str(self.next_id)
        self.connection.sendall(f"REQ {request} EXEC {command}\n".encode("latin-1"))
        deadline = time.monotonic() + self.reply_timeout
        lines: list[str] | None = None
        ok = False
        while True:
            while b"\n" in self.received:
                raw, self.received = self.received.split(b"\n", 1)
                line = raw.decode("latin-1").rstrip("\r")
                words = line.split()
                if words[:2] == ["BEGIN", request]:
                    ok, lines = words[2:3] == ["OK"], []
                elif words == ["END", request] and lines is not None:
                    if not ok:
                        raise DosboxError(f"{command}: {' '.join(lines)}")
                    return lines
                elif lines is not None:
                    lines.append(line)
            self._check(deadline, f"reply to {command!r}")
            try:
                data = self.connection.recv(65536)
            except TimeoutError:
                continue
            if not data:
                raise Stopped("DOSBox-X closed the connection")
            self.received += data

    def wait(self, seconds: float) -> None:
        """Sleep, still checking ``alive``."""
        end = time.monotonic() + seconds
        while (left := end - time.monotonic()) > 0:
            if not self.alive():
                raise Stopped("DOSBox-X stopped")
            time.sleep(min(left, 0.1))

    def key(self, chord: str, hold: int = 50) -> None:
        """Press a mapper key or a+b chord for ``hold`` ms; one upper-case letter adds lshift."""
        if len(chord) == 1 and chord.isupper():
            chord = "lshift+" + chord.lower()
        output = self.execute(f"KEY {chord} {hold}")
        if any(line.startswith("No mapper event") for line in output):
            raise DosboxError(f"unknown key {chord!r}")
        self.wait(hold / 1000)

    def type(self, keys: str | Iterable[str], pace: int = 300, hold: int = 50) -> None:
        """Press keys one after another (a string is split on spaces), ``pace`` ms apart."""
        for chord in keys.split() if isinstance(keys, str) else keys:
            self.key(chord, hold)
            self.wait(pace / 1000)

    def move(self, x: float, y: float) -> None:
        """Put the mouse at INT 33h coordinates."""
        self.execute(f"MOUSEMOVE {x} {y}")

    def button(self, n: int, down: bool) -> None:
        self.execute(f"MOUSEBUTTON {n} {'DOWN' if down else 'UP'}")

    def shot(self, captures: Path, raw: bool = True, timeout: float = 5.0) -> Path:
        """Take a screenshot and return the new PNG in the ``captures`` directory."""
        captures = Path(captures)
        before = set(captures.glob("*.png"))
        self.execute("SCREENSHOT RAW" if raw else "SCREENSHOT")
        deadline = time.monotonic() + timeout
        while True:
            new = sorted(set(captures.glob("*.png")) - before)
            if new:
                self.wait(0.2)  # let DOSBox-X finish writing the file
                return new[0]
            self._check(deadline, "the screenshot file")
            time.sleep(0.05)

    def video(self, start: bool) -> None:
        self.execute(f"VIDEOCAPTURE {'START' if start else 'STOP'}")

    def close(self) -> None:
        if self.connection is not None:
            self.connection.close()
            self.connection = None
        self.server.close()
