"""Where Waypoint keeps its state, and where it finds its bundled resources.

Read-only resources (``web/`` and ``cotw/data/``) ship with the app. Writable state —
the daily population history, the recent-spawns shortlist, the radar's entity cache —
must NOT live inside the install directory: a packaged app may sit in Program Files
(no write access) or be replaced wholesale by an update, and losing the shortlist on
every update would defeat the point of keeping it.

* from a checkout: ``<project>/work/`` (unchanged, so the tools keep finding it);
* frozen (``Waypoint.exe``): ``%LOCALAPPDATA%\\Waypoint\\``;
* ``WAYPOINT_DATA_DIR`` overrides both — handy for tests, or for a portable install
  on a USB stick.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

APP_NAME = "Waypoint"
APP_TITLE = "Waypoint"

#: the checkout, or the PyInstaller bundle root when frozen
PROJECT_ROOT = Path(__file__).resolve().parent.parent


def frozen() -> bool:
    """True inside a PyInstaller executable."""
    return bool(getattr(sys, "frozen", False))


def bundle_root() -> Path:
    """Root of the read-only resources."""
    if frozen():
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).resolve().parent))
    return PROJECT_ROOT


def resource_dir(name: str) -> Path:
    """A bundled folder, e.g. ``resource_dir("web")`` or ``resource_dir("cotw/data")``."""
    return bundle_root() / name


def data_dir() -> Path:
    """The writable state directory (created on demand)."""
    override = os.environ.get("WAYPOINT_DATA_DIR")
    if override:
        path = Path(override)
    elif frozen():
        base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA") or Path.home()
        path = Path(base) / APP_NAME
    else:
        path = PROJECT_ROOT / "work"
    path.mkdir(parents=True, exist_ok=True)
    return path


def data_file(name: str) -> Path:
    """A file inside :func:`data_dir`."""
    return data_dir() / name
