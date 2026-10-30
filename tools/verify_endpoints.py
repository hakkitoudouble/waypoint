"""Exercise every HTTP endpoint across every reserve slot, including bad input.

The engine was verified on Emerald Coast; this checks that the server degrades
gracefully everywhere else — holes in the reserve id space, pristine reserves with no
population, unknown slots, and hostile paths. A 500 anywhere is a bug; a clean 404
with a JSON error body is correct behaviour.

Run:  python tools/verify_endpoints.py   (server must be running)
"""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request

BASE = "http://127.0.0.1:8791"
FAILURES: list[str] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    if ok:
        print(f"  PASS  {label}")
    else:
        print(f"  FAIL  {label}  {detail}")
        FAILURES.append(label)


def get(path: str) -> tuple[int, object]:
    try:
        with urllib.request.urlopen(BASE + path, timeout=30) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        try:
            return exc.code, json.loads(exc.read().decode("utf-8"))
        except Exception:  # noqa: BLE001
            return exc.code, None
    except Exception as exc:  # noqa: BLE001
        return 0, str(exc)


def main() -> int:
    status, listing = get("/api/reserves")
    check("/api/reserves responds", status == 200, str(status))
    if status != 200 or not isinstance(listing, dict):
        return 1
    reserves = listing.get("reserves", [])
    check("reserves listing is non-empty", bool(reserves), str(len(reserves)))

    print("\n== every reserve slot, population ==")
    server_errors = 0
    usable = 0
    for entry in reserves:
        index = entry["index"]
        status, payload = get(f"/api/population?reserve={index}")
        if status == 500:
            server_errors += 1
            print(f"  FAIL  reserve {index}: HTTP 500  {str(payload)[:80]}")
        elif status == 200 and isinstance(payload, dict):
            animals = payload.get("animals", [])
            name = payload.get("reserve", {}).get("name")
            if animals:
                usable += 1
            print(f"  ok    reserve {index:>2} {str(name):<28} animals={len(animals):<5} "
                  f"world=({payload.get('world', {}).get('min_x'):.0f}.."
                  f"{payload.get('world', {}).get('max_x'):.0f})")
        else:
            print(f"  ok    reserve {index:>2} clean {status}: {str(payload)[:70]}")
    check("no reserve slot produced a 500", server_errors == 0, str(server_errors))
    check("several reserves are usable", usable >= 5, str(usable))

    print("\n== need zones ==")
    status, allz = get("/api/needzones")
    check("/api/needzones responds", status == 200, str(status))
    if status == 200 and isinstance(allz, dict):
        buckets = allz.get("reserves", {})
        check("zone buckets listed", bool(buckets), str(buckets))
        total = sum(b.get("count", 0) for b in buckets.values())
        check("zone total is stable", total > 400, str(total))
        for key in buckets:
            status_z, payload_z = get(f"/api/needzones?reserve={key}")
            if status_z != 200:
                check(f"needzones reserve {key}", False, str(status_z))
            elif not payload_z.get("zones"):
                check(f"needzones reserve {key} has zones", False, "empty")
            else:
                world = payload_z["world"]
                inside = all(
                    world["min_x"] <= z["x"] <= world["max_x"]
                    and world["min_y"] <= z["z"] <= world["max_y"]
                    for z in payload_z["zones"]
                )
                check(f"needzones reserve {key}: all zones inside the box", inside, str(world))

    print("\n== hostile input ==")
    status, payload = get("/api/population?reserve=999")
    check("unknown reserve is a clean 404", status == 404, f"{status} {str(payload)[:60]}")
    status, payload = get("/api/population?reserve=abc")
    check("non-numeric reserve does not 500", status in (400, 404, 500) and status != 200,
          str(status))
    if status == 500:
        check("non-numeric reserve handled without a crash", False, "HTTP 500")

    status, _ = get("/api/does-not-exist")
    check("unknown API path is 404", status == 404, str(status))

    status, _ = get("/../../cotw/data/reserves.json")
    check("path traversal is refused", status in (403, 404), str(status))

    print()
    if FAILURES:
        print(f"FAIL: {len(FAILURES)} check(s) failed")
        for f in FAILURES:
            print(f"   - {f}")
        return 1
    print("PASS: every endpoint is robust across all reserve slots")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
