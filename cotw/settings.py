"""User choices that must survive a restart.

Today that is only the save folder: when Windows keeps Documents somewhere the automatic
search does not find, the user points Waypoint at the right folder once from the
interface, and the choice is remembered. It lives in the writable state directory
(``%LOCALAPPDATA%\\Waypoint`` when packaged), never in the install folder.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from . import paths


def settings_file() -> Path:
    return paths.data_file("settings.json")


def load() -> dict[str, Any]:
    try:
        payload = json.loads(settings_file().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return payload if isinstance(payload, dict) else {}


def get(key: str, default: Any = None) -> Any:
    return load().get(key, default)


def update(**values: Any) -> dict[str, Any]:
    """Merge ``values`` into the file; a ``None`` value removes the key."""
    payload = load()
    for key, value in values.items():
        if value is None:
            payload.pop(key, None)
        else:
            payload[key] = value
    try:
        settings_file().write_text(
            json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
        )
    except OSError:
        pass
    return payload
