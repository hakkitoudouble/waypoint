"""Build the Windows release of Waypoint.

    python build.py                 # dist/Waypoint/  +  dist/Waypoint-<ver>-win64.zip
    python build.py --no-zip        # folder only (faster while iterating)
    python build.py --clean         # wipe dist/ and build/ first

Needs PyInstaller (``pip install pyinstaller``) and nothing else: numpy is pulled in
automatically, the icon is committed under ``assets/`` so Pillow is not required here.

What it produces, inside ``dist/``:

    Waypoint/                     the app folder (exe + _internal + docs)
    Waypoint-<ver>-win64.zip      what you upload to Nexus / attach to a GitHub release
    SHA256SUMS.txt                checksums of the archives

The package is a **onedir** build on purpose: it starts in well under a second, does
not unpack itself to %TEMP% on every run (less antivirus noise), and the _internal
folder keeps the read-only web assets visible next to the exe.
"""

from __future__ import annotations

import argparse
import hashlib
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DIST = ROOT / "dist"
BUILD = ROOT / "build"
ICON = ROOT / "assets" / "waypoint.ico"
APP_NAME = "Waypoint"

#: what ships next to the executable
DOCS = ["README.md", "INSTALL.txt", "CHANGELOG.md", "LICENSE"]

VERSION_INFO = """VSVersionInfo(
  ffi=FixedFileInfo(
    filevers={vtuple}, prodvers={vtuple},
    mask=0x3f, flags=0x0, OS=0x40004, fileType=0x1, subtype=0x0, date=(0, 0)
  ),
  kids=[
    StringFileInfo([
      StringTable('040904B0', [
        StringStruct('CompanyName', 'Waypoint'),
        StringStruct('FileDescription', 'Waypoint - COTW population and need-zone companion'),
        StringStruct('FileVersion', '{version}'),
        StringStruct('InternalName', 'Waypoint'),
        StringStruct('LegalCopyright', 'Code: MIT. Game-derived assets remain their owners\\' property.'),
        StringStruct('OriginalFilename', 'Waypoint.exe'),
        StringStruct('ProductName', 'Waypoint'),
        StringStruct('ProductVersion', '{version}')
      ])
    ]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
"""


def version() -> str:
    namespace: dict[str, object] = {}
    exec((ROOT / "cotw" / "__init__.py").read_text(encoding="utf-8"), namespace)
    return str(namespace["__version__"])


def run(cmd: list[str]) -> None:
    print("$ " + " ".join(cmd))
    subprocess.run(cmd, cwd=ROOT, check=True)


def size_mb(path: Path) -> float:
    if path.is_file():
        return path.stat().st_size / 1e6
    return sum(f.stat().st_size for f in path.rglob("*") if f.is_file()) / 1e6


def build_executable() -> Path:
    """Run PyInstaller and return the produced app folder."""
    ver = version()
    # PyInstaller unpacks filevers/prodvers as a 4-tuple (major, minor, patch, build).
    parts = [int(p) for p in ver.split(".")[:3]]
    while len(parts) < 4:
        parts.append(0)

    BUILD.mkdir(exist_ok=True)
    version_file = BUILD / "version_info.txt"
    version_file.write_text(
        VERSION_INFO.format(version=ver, vtuple=tuple(parts)), encoding="utf-8"
    )

    sep = ";" if sys.platform == "win32" else ":"
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm", "--clean", "--onedir", "--console",
        "--name", APP_NAME,
        "--icon", str(ICON),
        "--version-file", str(version_file),
        "--add-data", f"{ROOT / 'web'}{sep}web",
        "--add-data", f"{ROOT / 'cotw' / 'data'}{sep}cotw/data",
        "--distpath", str(DIST),
        "--workpath", str(BUILD / "pyinstaller"),
        "--specpath", str(BUILD),
        "--noupx",
        # trim what a save reader never needs
        "--exclude-module", "tkinter",
        "--exclude-module", "unittest",
        "--exclude-module", "pydoc",
        "--exclude-module", "pytest",
        "--exclude-module", "setuptools",
        str(ROOT / "waypoint.py"),
    ]
    run(cmd)
    app = DIST / APP_NAME
    if not (app / f"{APP_NAME}.exe").is_file():
        raise SystemExit(f"PyInstaller did not produce {app / (APP_NAME + '.exe')}")
    return app


def copy_docs(app: Path) -> None:
    for name in DOCS:
        source = ROOT / name
        if source.is_file():
            shutil.copy2(source, app / name)


def make_zip(folder: Path, zip_path: Path) -> None:
    """Zip ``folder`` with its own name as the top-level directory."""
    if zip_path.exists():
        zip_path.unlink()
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in sorted(folder.rglob("*")):
            if path.is_dir() or "__pycache__" in path.parts or path.suffix == ".pyc":
                continue
            archive.write(path, Path(folder.name) / path.relative_to(folder))


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--no-zip", action="store_true", help="skip the archive")
    parser.add_argument("--clean", action="store_true", help="delete dist/ and build/ first")
    args = parser.parse_args(argv)

    ver = version()
    print(f"Waypoint {ver} — building for Windows\n")

    if args.clean:
        for path in (DIST, BUILD):
            if path.exists():
                print(f"removing {path}")
                shutil.rmtree(path)

    app = build_executable()
    copy_docs(app)
    print(f"\napp folder : {app}  ({size_mb(app):.1f} MB)")

    archives: list[Path] = []
    if not args.no_zip:
        archive = DIST / f"{APP_NAME}-{ver}-win64.zip"
        make_zip(app, archive)
        archives.append(archive)
        print(f"archive    : {archive}  ({size_mb(archive):.1f} MB)")

        sums = DIST / "SHA256SUMS.txt"
        sums.write_text(
            "\n".join(f"{sha256(p)}  {p.name}" for p in archives) + "\n", encoding="utf-8"
        )
        print(f"checksums  : {sums}")

    print("\nReady. Upload the zip to Nexus Mods, or attach it to a GitHub release.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
