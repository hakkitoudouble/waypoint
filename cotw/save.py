"""Reader for Avalanche's "SAVE" container, as used by theHunter: Call of the Wild.

A save file is a thin wrapper around a zlib stream:

    offset 0x00  4  magic  b"SAVE"
    offset 0x04  4  version (0x00335D13 for COTW)
    offset 0x08  4  uncompressed payload size
    offset 0x0C  4  zero
    offset 0x10  4  block tag, b"COMP" for zlib-compressed
    offset 0x14  1  ?
    offset 0x15  1  ?
    offset 0x16  4  uncompressed payload size (repeated)
    offset 0x1A  4  zero
    offset 0x1E  2  zero
    offset 0x20  .. raw zlib stream

The decompressed payload is *not* the ADF document itself: it is prefixed by
5 opaque bytes (01 01 00 00 00) and every offset stored inside the ADF document
is relative to that 5-byte boundary. See cotw.adf for the payload parser.
"""

from __future__ import annotations

import os
import struct
import zlib
from dataclasses import dataclass
from pathlib import Path

MAGIC = b"SAVE"
TAG_COMP = b"COMP"
HEADER_SIZE = 0x20
PAYLOAD_PREFIX = 5

#: Where COTW keeps its saves, relative to the user's Documents folder.
SAVE_ROOT_RELATIVE = os.path.join("Avalanche Studios", "COTW", "Saves")


class SaveFormatError(Exception):
    """Raised when a file is not a SAVE container we understand."""


@dataclass(frozen=True)
class Container:
    """A parsed SAVE container."""

    version: int
    unpacked_size: int
    payload: bytes

    def __post_init__(self) -> None:
        if len(self.payload) != self.unpacked_size:
            raise SaveFormatError(
                f"payload is {len(self.payload)} bytes, header promised {self.unpacked_size}"
            )


def parse_container(raw: bytes) -> Container:
    """Decompress a SAVE container into its payload."""
    if len(raw) < HEADER_SIZE:
        raise SaveFormatError(f"file is only {len(raw)} bytes, too short for a SAVE header")
    if raw[:4] != MAGIC:
        raise SaveFormatError(f"bad magic {raw[:4]!r}, expected {MAGIC!r}")

    version = struct.unpack_from("<I", raw, 0x04)[0]
    unpacked_size = struct.unpack_from("<I", raw, 0x08)[0]
    tag = raw[0x10:0x14]

    if tag != TAG_COMP:
        raise SaveFormatError(f"unsupported block tag {tag!r}, expected {TAG_COMP!r}")

    stream = raw[HEADER_SIZE:]
    decompressor = zlib.decompressobj()
    try:
        payload = decompressor.decompress(stream)
    except zlib.error as exc:  # pragma: no cover - corrupt file path
        raise SaveFormatError(f"zlib error: {exc}") from exc

    if not decompressor.eof:
        raise SaveFormatError("zlib stream is truncated")

    return Container(version=version, unpacked_size=unpacked_size, payload=payload)


def read_container(path: str | os.PathLike[str]) -> Container:
    """Read and decompress a SAVE file from disk."""
    with open(path, "rb") as handle:
        return parse_container(handle.read())


def adf_payload(container: Container) -> bytes:
    """Return the payload with the 5-byte wrapper prefix stripped."""
    return container.payload[PAYLOAD_PREFIX:]


def _documents_known_folder() -> Path | None:
    """The user's Documents folder as Windows itself defines it.

    ``Path.home() / "Documents"`` is wrong on the many machines where Windows redirects
    Documents — to OneDrive, or to another drive. The shell knows the real location, so
    ask it (SHGetKnownFolderPath with FOLDERID_Documents) and fall back to the
    conventional paths when that fails (non-Windows, locked-down shell).
    """
    if os.name != "nt":
        return None
    try:
        import ctypes

        class GUID(ctypes.Structure):
            _fields_ = [
                ("Data1", ctypes.c_uint32),
                ("Data2", ctypes.c_uint16),
                ("Data3", ctypes.c_uint16),
                ("Data4", ctypes.c_ubyte * 8),
            ]

        # {FDD39AD0-238F-46AF-ADB4-6C85480369C7}
        documents = GUID(
            0xFDD39AD0, 0x238F, 0x46AF,
            (ctypes.c_ubyte * 8)(0xAD, 0xB4, 0x6C, 0x85, 0x48, 0x03, 0x69, 0xC7),
        )
        shell32 = ctypes.WinDLL("shell32", use_last_error=True)
        ole32 = ctypes.WinDLL("ole32")
        out = ctypes.c_wchar_p()
        shell32.SHGetKnownFolderPath.argtypes = [
            ctypes.POINTER(GUID), ctypes.c_uint32, ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_wchar_p),
        ]
        shell32.SHGetKnownFolderPath.restype = ctypes.c_long
        result = shell32.SHGetKnownFolderPath(ctypes.byref(documents), 0, None,
                                              ctypes.byref(out))
        if result != 0 or not out.value:
            return None
        try:
            return Path(out.value)
        finally:
            ole32.CoTaskMemFree(out)
    except Exception:  # noqa: BLE001 - any failure just means "use the fallbacks"
        return None


def documents_candidates() -> list[Path]:
    """Every folder that may hold Documents, most likely first, without duplicates."""
    candidates: list[Path] = []

    def add(path: Path | None) -> None:
        if path is None:
            return
        try:
            resolved = path.expanduser()
        except (OSError, RuntimeError):
            return
        if resolved not in candidates:
            candidates.append(resolved)

    add(_documents_known_folder())
    home = Path.home()
    add(home / "Documents")
    for variable in ("OneDrive", "OneDriveConsumer", "OneDriveCommercial"):
        value = os.environ.get(variable)
        if value:
            add(Path(value) / "Documents")
    try:
        for folder in sorted(home.glob("OneDrive*/Documents")):
            add(folder)
    except OSError:
        pass
    # Documents is sometimes moved to another drive instead of OneDrive.
    for drive in ("D:", "E:", "F:", "G:"):
        add(Path(drive + "\\") / "Documents")
    return candidates


def save_roots() -> list[Path]:
    """Every ``…/Avalanche Studios/COTW/Saves`` folder we would look in, in order."""
    roots: list[Path] = []
    for documents in documents_candidates():
        root = documents / SAVE_ROOT_RELATIVE
        if root not in roots:
            roots.append(root)
    return roots


def find_save_dirs(documents: str | os.PathLike[str] | None = None) -> list[Path]:
    """Every per-account save folder, searched in the locations :func:`save_roots` gives.

    Passing ``documents`` restricts the search to that one folder (the tests and
    ``--save-dir`` use it that way).
    """
    if documents is not None:
        roots = [Path(documents) / SAVE_ROOT_RELATIVE]
    else:
        roots = save_roots()
    found: list[Path] = []
    for root in roots:
        try:
            if not root.is_dir():
                continue
            found.extend(sorted(p for p in root.iterdir() if p.is_dir()))
        except OSError:
            continue
    return found


def best_save_dir(dirs: list[Path] | None = None) -> Path | None:
    """The account folder most likely to be the one being played.

    A machine can hold several (family sharing, an old account): pick the one whose
    population files were written most recently, then the biggest. The old code took the
    first alphabetically, which could be an account that has never been played — and then
    the app reported "no reserve found" on a machine that had perfectly good saves.
    """
    dirs = find_save_dirs() if dirs is None else dirs
    if not dirs:
        return None
    if len(dirs) == 1:
        return dirs[0]

    def rank(path: Path) -> tuple[float, int]:
        newest = 0.0
        total = 0
        for entry in list_population_files(path):
            try:
                stat = entry.stat()
            except OSError:
                continue
            newest = max(newest, stat.st_mtime)
            total += stat.st_size
        return (newest, total)

    return max(dirs, key=rank)


def list_population_files(save_dir: str | os.PathLike[str]) -> list[Path]:
    """Return animal_population_<N> files in a save folder, ordered by N."""
    found: list[tuple[int, Path]] = []
    for entry in Path(save_dir).glob("animal_population_*"):
        suffix = entry.name.rsplit("_", 1)[-1]
        if suffix.isdigit():
            found.append((int(suffix), entry))
    return [path for _, path in sorted(found)]


def reserve_index(path: str | os.PathLike[str]) -> int:
    """Reserve index N encoded in an animal_population_<N> filename."""
    suffix = Path(path).name.rsplit("_", 1)[-1]
    if not suffix.isdigit():
        raise ValueError(f"not a population file name: {path!r}")
    return int(suffix)
