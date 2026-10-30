"""Waypoint — start the local server and open the interface.

This is what ``Waypoint.exe`` runs, and a convenient alternative to
``python -m cotw.server`` from a checkout:

    python waypoint.py                 # port 8765, opens the browser
    python waypoint.py --no-browser    # server only
    python waypoint.py --port 9000
    python waypoint.py --data-dir D:\\Waypoint   # portable install (state next to it)

If something already answers on the port, it is treated as a running Waypoint: the
browser is opened on it and this process exits instead of fighting over the socket.
"""

from __future__ import annotations

import argparse
import os
import socket
import sys
import threading
import time
import urllib.request
import webbrowser
from pathlib import Path

from cotw import __version__, server
from cotw.paths import data_dir

BANNER = """
  Waypoint {version} - population & need zones for theHunter: Call of the Wild
"""

#: how long the launcher waits for the server before giving up on the browser
READY_TIMEOUT = 20.0


def _answers(port: int) -> bool:
    """True when a Waypoint server is already listening on ``port``."""
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/ping", timeout=1) as res:
            return res.status == 200
    except Exception:  # noqa: BLE001 - any failure means "not ours"
        return False


def _free_port(preferred: int, tries: int = 20) -> int:
    """The first port at or after ``preferred`` that nothing is listening on."""
    for port in range(preferred, preferred + tries):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                sock.bind(("127.0.0.1", port))
            except OSError:
                continue
            return port
    raise SystemExit(f"no free port between {preferred} and {preferred + tries - 1}")


def _open_when_ready(url: str, port: int) -> None:
    deadline = time.time() + READY_TIMEOUT
    while time.time() < deadline:
        if _answers(port):
            webbrowser.open(url)
            return
        time.sleep(0.2)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="Waypoint",
        description="Start Waypoint and open the interface in your browser.",
    )
    parser.add_argument("--port", type=int, default=8765,
                        help="preferred port (8765); the next free one is used if busy")
    parser.add_argument("--save-dir", type=Path, default=None,
                        help="COTW save folder, if it is not the usual Documents path")
    parser.add_argument("--no-browser", action="store_true",
                        help="do not open a browser window")
    parser.add_argument("--data-dir", type=Path, default=None,
                        help="where to keep the state files (default: %%LOCALAPPDATA%%\\Waypoint)")
    args = parser.parse_args(argv)

    # A Windows console may be on a legacy code page: never die on an accent.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")
        except Exception:  # noqa: BLE001 - not every stream supports it
            pass

    if args.data_dir is not None:
        os.environ["WAYPOINT_DATA_DIR"] = str(args.data_dir)

    if _answers(args.port):
        url = f"http://127.0.0.1:{args.port}/"
        print(f"Waypoint is already running on {url}")
        if not args.no_browser:
            webbrowser.open(url)
        return 0

    port = _free_port(args.port)
    url = f"http://127.0.0.1:{port}/"
    print(BANNER.format(version=__version__))
    print(f"  interface : {url}")
    print(f"  state     : {data_dir()}")
    if port != args.port:
        print(f"  note      : port {args.port} was busy, using {port}")
    print("  keep this window open - close it (or press Ctrl+C) to stop\n")

    if not args.no_browser:
        threading.Thread(target=_open_when_ready, args=(url, port), daemon=True).start()

    try:
        server.serve(port, args.save_dir)
    except OSError as exc:
        print(f"\nCould not start the server on port {port}: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
