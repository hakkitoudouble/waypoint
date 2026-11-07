#!/usr/bin/env python3
"""The "where are my saves?" path: folder resolution, best account, remembered choice.

Run:  python tools/verify_setup.py

Every check builds its own temporary tree, so this runs on any machine — no game, no
save, no network. It is the regression guard for the 1.0.2 fix (Documents redirected to
OneDrive, several accounts in Saves, the folder the user pastes into the panel).
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from cotw import save, settings  # noqa: E402
from cotw.server import Handler, _resolve_custom_save_dir  # noqa: E402

RESULTS: list[bool] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    RESULTS.append(bool(ok))
    line = ("PASS  " if ok else "FAIL  ") + name
    if detail:
        line += "   " + str(detail)
    print(line)


def account_folder(base: Path, steam_id: str, *, age: float, reserves: int) -> Path:
    """A fake ``…/Saves/<steamid>/`` folder, with population files stamped ``age`` s ago."""
    folder = base / save.SAVE_ROOT_RELATIVE / steam_id
    folder.mkdir(parents=True)
    stamp = 1_700_000_000 - age
    for index in range(reserves):
        path = folder / f"animal_population_{index}"
        path.write_bytes(b"\0" * 32)
        os.utime(path, (stamp, stamp))
    return folder


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        older = account_folder(base, "76561190000000001", age=90_000, reserves=2)
        newest = account_folder(base, "76561190000000002", age=10, reserves=5)
        saves_root = base / save.SAVE_ROOT_RELATIVE

        print("== which account folder wins ==")
        # find_save_dirs(documents) restricts the search to one Documents folder
        found = save.find_save_dirs(base)
        check("both accounts are found", len(found) == 2, str([p.name for p in found]))
        check("the most recently written account wins", save.best_save_dir(found) == newest,
              str(save.best_save_dir(found)))
        check("the alphabetical first would be the wrong one", sorted(found)[0] == older,
              str(sorted(found)[0].name))
        check("no folder at all gives None", save.best_save_dir([]) is None)

        print("\n== what the user may paste ==")
        for label, pasted in (
            ("the account folder", str(newest)),
            ("the Saves folder above it", str(saves_root)),
            ("the Documents folder above that", str(base)),
            ("the same, with quotes and spaces", f'  "{newest}"  '),
            ("the same, with a trailing backslash", str(newest) + "\\"),
            ("the same, with %VARS%", "%COTW_TEST_DOCUMENTS%\\Avalanche Studios\\COTW\\Saves"),
        ):
            os.environ["COTW_TEST_DOCUMENTS"] = str(base)
            resolved, error = _resolve_custom_save_dir(pasted)
            check(f"{label} resolves to the account folder", resolved == newest,
                  f"{resolved} ({error})")

        print("\n== what is refused, and how it says so ==")
        empty = base / "empty"
        empty.mkdir()
        resolved, error = _resolve_custom_save_dir(str(empty))
        check("a folder without population files is refused", resolved is None, error or "")
        check("the refusal names what is missing", error is not None
              and "animal_population_" in error, error or "")
        resolved, error = _resolve_custom_save_dir(str(base / "nope"))
        check("a folder that does not exist is refused", resolved is None, error or "")
        check("that refusal says it does not exist", error == "that folder does not exist",
              error or "")
        resolved, error = _resolve_custom_save_dir("   ")
        check("an empty path is refused", resolved is None and error == "empty path", error or "")

        print("\n== the remembered folder ==")
        os.environ["WAYPOINT_DATA_DIR"] = str(base / "state")
        settings.update(save_dir=str(newest))
        check("it is stored", settings.get("save_dir") == str(newest), str(settings.get("save_dir")))
        check("it is a file in the state directory", settings.settings_file().is_file(),
              str(settings.settings_file()))

        Handler.save_dir = None
        Handler.save_dir_source = None
        directory, source = Handler._effective_save_dir()
        check("it wins over the automatic search", directory == newest and source == "saved",
              f"{directory} ({source})")

        settings.update(save_dir=None)
        check("forgetting it removes the key", settings.get("save_dir") is None,
              str(settings.get("save_dir")))
        Handler.save_dir = None
        Handler.save_dir_source = None

    print()
    if all(RESULTS):
        print("RESULT: PASS  (%d checks)" % len(RESULTS))
        return 0
    print("RESULT: FAIL  (%d of %d checks failed)"
          % (sum(1 for ok in RESULTS if not ok), len(RESULTS)))
    return 1


if __name__ == "__main__":
    sys.exit(main())
