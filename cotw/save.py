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


def find_save_dirs(documents: str | os.PathLike[str] | None = None) -> list[Path]:
    """Return every per-account save folder under Documents/Avalanche Studios/COTW/Saves."""
    if documents is None:
        documents = Path.home() / "Documents"
    root = Path(documents) / SAVE_ROOT_RELATIVE
    if not root.is_dir():
        return []
    return sorted(p for p in root.iterdir() if p.is_dir())


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
