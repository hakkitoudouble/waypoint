"""Run every check in the project, in order, and summarise the result.

Each layer has its own script (they are listed in README.md); this one exists so a
single command answers "is the app still good?" after a change, and so a failing
suite is reported as a suite instead of a wall of output.

    python tools/verify_all.py            # everything
    python tools/verify_all.py -k i18n    # only the suites matching "i18n"

Suites that talk to the HTTP server are skipped (not failed) when nothing answers on
the port — start it first:

    python -m cotw.server --port 8791
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PY = sys.executable
NODE_CANDIDATES = [
    "node",
    r"C:\Users\Maelo\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\node\bin\node.exe",
]
SERVER = "http://127.0.0.1:8791"


def find_node() -> str | None:
    for candidate in NODE_CANDIDATES:
        found = candidate if candidate.endswith(".exe") else shutil.which(candidate)
        if found and Path(found).is_file():
            return found
    return None


def server_up() -> bool:
    try:
        with urllib.request.urlopen(SERVER + "/api/reserves", timeout=3) as res:
            return res.status == 200
    except Exception:
        return False


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("-k", "--filter", default="", help="only run suites containing this")
    args = parser.parse_args()

    node = find_node()
    up = server_up()

    # (label, argv, env, needs-server)
    suites: list[tuple[str, list[str], dict[str, str], bool]] = [
        ("save containers", [PY, "tools/verify_save.py"], {}, False),
        ("ADF v4 grammar", [PY, "tools/verify_adf.py"], {}, False),
        ("population pipeline", [PY, "tools/verify_pipeline.py"], {}, False),
        ("fur algorithm", [PY, "tools/verify_furs.py"], {}, False),
        ("medal thresholds", [PY, "tools/verify_thresholds.py"], {}, False),
        ("alerts watcher", [PY, "tools/verify_alerts.py"], {}, False),
        ("delta + history", [PY, "tools/verify_delta.py"], {}, False),
        ("save folder setup", [PY, "tools/verify_setup.py"], {}, False),
        ("HTTP endpoints", [PY, "tools/verify_endpoints.py"], {}, True),
        ("radar discovery", [PY, "tools/verify_radar_discovery.py"], {}, True),
        ("web UI wiring", [PY, "tools/check_ui.py"], {}, False),
        ("i18n table", [PY, "tools/check_i18n.py"], {}, False),
    ]
    if node:
        suites += [
            ("UI boot (fr)", [node, "work/uiboot/boot.js"], {"COTW_LOCALE": "fr"}, True),
            ("UI boot (en)", [node, "work/uiboot/boot.js"], {"COTW_LOCALE": "en"}, True),
            ("UI boot (filters restored)", [node, "work/uiboot/boot.js"],
             {"COTW_SEED_FILTERS": "1"}, True),
            ("UI boot (no save folder)", [node, "work/uiboot/boot.js"],
             {"COTW_NO_SAVE": "1"}, True),
            ("i18n units", [node, "work/uiboot/i18n.js"], {}, False),
        ]
    else:
        print("! node was not found: the jsdom UI tests are skipped\n")

    selected = [s for s in suites if args.filter.lower() in s[0].lower()]
    if not selected:
        print(f"no suite matches {args.filter!r}")
        return 1
    if not up:
        print(f"! no server on {SERVER}: the HTTP and UI suites will be skipped")
        print("  start it with: python -m cotw.server --port 8791\n")

    results: list[tuple[str, str, float, str]] = []
    for label, argv, extra_env, needs_server in selected:
        if needs_server and not up:
            results.append((label, "SKIP", 0.0, "server not running"))
            print(f"  SKIP  {label}  (needs the server)")
            continue
        env = dict(os.environ)
        env.update(extra_env)
        env.setdefault("PYTHONIOENCODING", "utf-8")
        started = time.time()
        proc = subprocess.run(
            argv, cwd=ROOT, capture_output=True, text=True,
            encoding="utf-8", errors="replace", env=env,
        )
        elapsed = time.time() - started
        output = (proc.stdout or "") + (proc.stderr or "")
        ok = proc.returncode == 0
        results.append((label, "PASS" if ok else "FAIL", elapsed, output))
        print(f"  {'PASS' if ok else 'FAIL'}  {label}  ({elapsed:.1f} s)")
        if not ok:
            tail = [line for line in output.splitlines() if line.strip()][-12:]
            for line in tail:
                print("        " + line)

    passed = sum(1 for _, status, _, _ in results if status == "PASS")
    failed = [label for label, status, _, _ in results if status == "FAIL"]
    skipped = [label for label, status, _, _ in results if status == "SKIP"]

    print()
    print(f"{passed}/{len(results)} suite(s) passed"
          + (f", {len(skipped)} skipped" if skipped else ""))
    if failed:
        print("FAILED: " + ", ".join(failed))
        return 1
    if skipped:
        print("SKIPPED: " + ", ".join(skipped))
        return 2
    print("PASS: every suite is green")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
