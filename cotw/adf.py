"""Avalanche "ADF" version 4 reader (the format behind theHunter: Call of the Wild saves).

Dependency free (Python 3.7+).  The grammar below was recovered from
``AnimalPopulationScanner.exe`` with Capstone (see ``notes/adf-v4.md`` for the
addresses and the key instructions) and then cross-validated against all 60 ADF
documents shipped with the game: every document tiles its definition region
exactly, every name in the pool is referenced, and the parsed value trees match
the game's own layout.

Quick start::

    from cotw.adf import Adf, open_save

    doc = Adf(open_save(r"...\\animal_population_16"))
    doc.definitions[0].name            # 'AnimalPopulationReserveData_9'
    root = doc.parse_entry(0)          # nested dicts / lists / scalars
    root["Populations"][0]["NameHashId"]
    for animal in doc.iter_animals():  # flattened, one dict per animal
        print(animal["species_hash"], animal["gender"], animal["weight"])

Document layout (all offsets relative to the ADF base; every field is a
little-endian u32 unless stated otherwise)::

    +0x00  'ADF '            magic 0x41444620
    +0x04  version           4
    +0x08  1                 unknown, always 1
    +0x0C  instances_off     offset of the instance table
    +0x10  definition_count  number of Definition records
    +0x14  definitions_off   offset of the definition table
    +0x18  0
    +0x1C  0
    +0x20  name_count        name pool slots, *including* the dummy slot 0
    +0x24  names_off         offset of the name pool
    +0x28  total_size        == length of the document
    +0x2C  0
    +0x30  1
    +0x34..0x3F  zero
    +0x40  first data item: a NUL terminated ASCII string

Note that ``+0x10`` is the *definition* count, not the instance count: the
instance table's length is the byte gap between ``instances_off`` and
``definitions_off``.  Documents written by the game always hold a single
instance (the root object), and its offset is normally 100..104 (the header
string sits at 0x40 and the root object follows it).

    instance table entry (24 bytes)
    +0  u32 name_hash   (0x00D7146E in every document seen: "savegamedata")
    +4  u32 type_hash   -> Definition.type_hash of the root object
    +8  u32 offset      root object offset, relative to the ADF base
    +12 u32 size        root object size in bytes
    +16 u32 0
    +20 u32 0

    Definition (40 bytes) followed by ``field_count`` Field records (32 bytes)
        +0  u32 type              1 Structure, 2 Pointer, 3 Array,
                                  4 InlineArray, 5 Native, 7 DefaultedNative
        +4  u32 size              byte size of one instance of this type
        +8  u32 unknown08         small; 1/4/8/.. (not needed when reading)
        +12 u32 type_hash
        +16 u32 name_id           0 = unnamed, else index into the name pool
        +20 u32 zero
        +24 u32 flags             0x8000 | {0,1,2,3}
        +28 u32 element_type_hash Array/InlineArray/Pointer only, else 0
        +32 u32 unknown58         InlineArray: element count
                                  DefaultedNative: default value
        +36 u32 field_count       Structure: number of Field records
                                  Pointer: 16, otherwise 0

    Field ("DefinitionValue", 32 bytes)
        +0  u32 name_id           0 = unnamed
        +4  u32 zero
        +8  u32 type_hash
        +12 u32 size              stored size; for structure/array types it is
                                  advisory, use the target Definition instead
        +16 u32 offset            byte offset inside the parent Structure
        +20 u32 zero
        +24 u32 default_raw       auxiliary ("default value"), normally 0
        +28 u32 zero

    name pool
        name_count u8 length bytes at ``names_off``
        name_count NUL terminated strings at ``names_off + name_count``

      Slot 0 is a dummy: its length byte is 1 and its only character is the
      '0' that precedes the first real name.  ``name_id`` is therefore a direct
      0-based index into the pool and 0 means "unnamed".

    Structure fields are stored inline at their explicit offsets.  An Array or
    Pointer field occupies a 16 byte slot inside the parent Structure::

        +0 u32 offset   relative to the *instance* base (not to the parent)
        +4 u32 capacity allocation hint, unused when reading
        +8 u32 count    number of elements
        +12 u32 zero

    Array elements are contiguous, ``element_definition.size`` bytes each;
    InlineArray elements live directly at the field's own offset.  Native values
    are stored in place using their declared size.

The 16-byte slot is the single most important detail: reading only eight bytes
(the declared ``size``) silently loses the real element count, because the
count is the *third* dword.  For ``animal_population_16`` the ``Populations``
slot is ``(48, 16, 14, 0)``: capacity 16 but only 14 species, which is why a
capacity-based read runs past the population array and starts parsing the
adjacent ``AnimalGroupData_5`` records as if they were populations.
"""

from __future__ import annotations

import struct
import zlib

__all__ = [
    "Adf",
    "AdfError",
    "Definition",
    "Field",
    "Instance",
    "MAGIC",
    "NATIVE_TYPES",
    "NATIVE_BY_NAME",
    "SAVE_MAGIC",
    "parse_document",
    "open_save",
]

#: 'ADF ' — compared as an immediate by the scanner at 0x14005B85B.
MAGIC = 0x41444620
ADF_MAGIC = MAGIC
SUPPORTED_VERSION = 4

SAVE_MAGIC = b"SAVE"
SAVE_SIZE_OFFSET = 0x08
SAVE_TAG_OFFSET = 0x10
SAVE_TAG = b"COMP"
SAVE_STREAM_OFFSET = 0x20
#: Every ADF offset is relative to the byte after this 5 byte payload prefix
#: (`lea r12, [r13+5]` at 0x14005B831, `lea rbx, [rdi+5]` at 0x14005A4D9).
BASE = 5
WRAPPER_PREFIX = b"\x01\x01\x00\x00\x00"

HEADER_SIZE = 0x40
INSTANCE_RECORD_SIZE = 24
DEFINITION_RECORD_SIZE = 40
FIELD_RECORD_SIZE = 32
ARRAY_SLOT_SIZE = 16
MAX_DEPTH = 32

TYPE_STRUCTURE = 1
TYPE_POINTER = 2
TYPE_ARRAY = 3
TYPE_INLINE_ARRAY = 4
TYPE_NATIVE = 5
TYPE_DEFAULTED_NATIVE = 7

TYPE_NAMES = {
    TYPE_STRUCTURE: "Structure",
    TYPE_POINTER: "Pointer",
    TYPE_ARRAY: "Array",
    TYPE_INLINE_ARRAY: "InlineArray",
    TYPE_NATIVE: "Native",
    TYPE_DEFAULTED_NATIVE: "DefaultedNative",
}
DEF_STRUCTURE = TYPE_STRUCTURE
DEF_ARRAY = TYPE_ARRAY
DEF_NATIVE = TYPE_NATIVE

#: Native value type hashes.  The first eight come from Gibbed's
#: ``NativeValueType`` enum; UInt64 is not in that enum but is proven by the
#: ``A[uint64]`` array definition in the animal population documents, whose
#: element hash is 0xA139E01F.
_NATIVE_TABLE = (
    ("UInt8", 0x0CA2821D, 1, "<B"),
    ("Int8", 0x580D0A62, 1, "<b"),
    ("UInt16", 0x86D152BD, 2, "<H"),
    ("Int16", 0xD13FCF93, 2, "<h"),
    ("UInt32", 0x075E4E4F, 4, "<I"),
    ("Int32", 0x192FE633, 4, "<i"),
    ("UInt64", 0xA139E01F, 8, "<Q"),
    ("Float", 0x7515A207, 4, "<f"),
    ("String", 0x34B4DBF8, None, None),
)

#: hash -> (name, size, struct format); ``size`` is None for variable length types.
NATIVE_TYPES = {h: (n, s, f) for n, h, s, f in _NATIVE_TABLE}
#: name -> (hash, size, struct format)
NATIVE_BY_NAME = {n: (h, s, f) for n, h, s, f in _NATIVE_TABLE}
#: hash -> (struct format, width), the shape the original module exposed.
NATIVE_FORMATS = {h: (f[1:], s) for h, (n, s, f) in NATIVE_TYPES.items() if s}

NATIVE_U8 = NATIVE_BY_NAME["UInt8"][0]
NATIVE_I8 = NATIVE_BY_NAME["Int8"][0]
NATIVE_U16 = NATIVE_BY_NAME["UInt16"][0]
NATIVE_I16 = NATIVE_BY_NAME["Int16"][0]
NATIVE_U32 = NATIVE_BY_NAME["UInt32"][0]
NATIVE_I32 = NATIVE_BY_NAME["Int32"][0]
NATIVE_U64 = NATIVE_BY_NAME["UInt64"][0]
NATIVE_F32 = NATIVE_BY_NAME["Float"][0]
NATIVE_STRING = NATIVE_BY_NAME["String"][0]


class AdfError(Exception):
    """Raised when bytes do not follow the ADF v4 grammar."""


def _u32(buf, off):
    return struct.unpack_from("<I", buf, off)[0]


def _check(buf, off, size, what, limit=None):
    end = off + size
    if off < 0 or end > (len(buf) if limit is None else limit):
        raise AdfError("%s at %d (+%d) is outside the document (length %d)"
                       % (what, off, size, len(buf) if limit is None else limit))


def open_save(path):
    """Read a COTW save file and return its decompressed payload.

    The container is ``b"SAVE"`` at 0, ``b"COMP"`` at 0x10, the expected
    decompressed size as a u32 at 8 and a zlib stream at 0x20 (both memcmps are
    visible at 0x14005B6CF and 0x14005B710).  The returned bytes are the payload
    exactly as decompressed, i.e. they still start with the 5 byte wrapper; the
    :class:`Adf` constructor accepts both this and the bare document.
    """
    with open(path, "rb") as handle:
        raw = handle.read()
    if len(raw) < SAVE_STREAM_OFFSET:
        raise AdfError("%s: only %d bytes, too short for a SAVE container"
                       % (path, len(raw)))
    if raw[:4] != SAVE_MAGIC:
        raise AdfError("%s: bad magic %r, expected %r"
                       % (path, raw[:4], SAVE_MAGIC))
    if raw[SAVE_TAG_OFFSET:SAVE_TAG_OFFSET + 4] != SAVE_TAG:
        raise AdfError("%s: block tag %r at 0x%X, expected %r"
                       % (path, raw[SAVE_TAG_OFFSET:SAVE_TAG_OFFSET + 4],
                          SAVE_TAG_OFFSET, SAVE_TAG))
    expected = _u32(raw, SAVE_SIZE_OFFSET)
    try:
        payload = zlib.decompress(raw[SAVE_STREAM_OFFSET:])
    except zlib.error as exc:
        raise AdfError("%s: zlib decompression failed: %s" % (path, exc)) from None
    if len(payload) != expected:
        raise AdfError("%s: decompressed %d bytes but the header promised %d"
                       % (path, len(payload), expected))
    return payload


class Field:
    """One field of a Structure (an ADF ``DefinitionValue``)."""

    __slots__ = ("index", "name_id", "name", "type_hash", "size", "offset",
                 "offset_raw", "default_raw")

    def __init__(self, index, name_id, name, type_hash, size, offset,
                 offset_raw, default_raw):
        self.index = index
        self.name_id = name_id
        self.name = name
        self.type_hash = type_hash
        self.size = size
        self.offset = offset
        self.offset_raw = offset_raw
        self.default_raw = default_raw

    def __repr__(self):
        return "<Field %s %08X size=%d offset=%d>" % (
            self.name or "<unnamed>", self.type_hash, self.size, self.offset)


class Definition:
    """One ADF v4 ``Definition`` record."""

    __slots__ = ("index", "type", "size", "unknown08", "type_hash", "name_id",
                 "name", "flags", "element_type_hash", "unknown58",
                 "field_count", "fields", "offset")

    def __init__(self, index, type, size, unknown08, type_hash, name_id, name,
                 flags, element_type_hash, unknown58, field_count, fields,
                 offset):
        self.index = index
        self.type = type
        self.size = size
        self.unknown08 = unknown08
        self.type_hash = type_hash
        self.name_id = name_id
        self.name = name
        self.flags = flags
        self.element_type_hash = element_type_hash
        self.unknown58 = unknown58
        self.field_count = field_count
        self.fields = fields
        self.offset = offset

    @property
    def kind(self):
        return self.type

    @property
    def name_index(self):
        return self.name_id

    @property
    def is_structure(self):
        return self.type == TYPE_STRUCTURE

    @property
    def is_array(self):
        return self.type == TYPE_ARRAY

    @property
    def type_name(self):
        return TYPE_NAMES.get(self.type, "Unknown(%d)" % self.type)

    def field(self, name):
        """Look a field up by name (KeyError when absent)."""
        for fld in self.fields:
            if fld.name == name:
                return fld
        raise KeyError("%s has no field %r" % (self.name, name))

    def __repr__(self):
        return "<Definition %s %r size=%d fields=%d>" % (
            self.type_name, self.name or hex(self.type_hash), self.size,
            len(self.fields))


class Instance:
    """One entry of the instance table (the document's root object)."""

    __slots__ = ("index", "name_hash", "type_hash", "offset", "size")

    def __init__(self, index, name_hash, type_hash, offset, size):
        self.index = index
        self.name_hash = name_hash
        self.type_hash = type_hash
        self.offset = offset
        self.size = size

    def __repr__(self):
        return "<Instance %d type=%08X offset=%d size=%d>" % (
            self.index, self.type_hash, self.offset, self.size)


class Adf:
    """A parsed ADF version 4 document.

    ``data`` may be a bare ADF document or a full decompressed save payload
    (with the 5 byte wrapper prefix); the two are told apart by the magic.
    """

    def __init__(self, data):
        if not isinstance(data, (bytes, bytearray, memoryview)):
            raise TypeError("Adf() needs bytes, not %r" % type(data).__name__)
        self.payload = bytes(data)
        base = 0
        if len(self.payload) < 4:
            raise AdfError("document is only %d bytes" % len(self.payload))
        if _u32(self.payload, 0) != MAGIC:
            if len(self.payload) > BASE and _u32(self.payload, BASE) == MAGIC:
                base = BASE
            else:
                raise AdfError("no ADF magic: got %08X at 0 and %08X at %d"
                               % (_u32(self.payload, 0),
                                  _u32(self.payload, BASE) if len(self.payload) > BASE + 4 else 0,
                                  BASE))
        self.base = base
        self._doc = self.payload[base:]
        self.total_size = len(self._doc)
        self._parse_header()
        self.names = self._parse_names()
        self.definitions = self._parse_definitions()
        self.by_hash = {}
        for definition in self.definitions:
            self.by_hash.setdefault(definition.type_hash, definition)
        self.entries = self._parse_instances()
        self.instances = self.entries
        self.warnings = []
        self.instance_base = self.entries[0].offset

    # -- header ---------------------------------------------------------
    def _parse_header(self):
        doc = self._doc
        if self.total_size < HEADER_SIZE:
            raise AdfError("document is %d bytes, shorter than the %d byte header"
                           % (self.total_size, HEADER_SIZE))
        self.magic = _u32(doc, 0x00)
        self.version = _u32(doc, 0x04)
        self.unknown08 = _u32(doc, 0x08)
        self.instances_offset = _u32(doc, 0x0C)
        self.instance_table = self.instances_offset
        self.definition_count = _u32(doc, 0x10)
        self.definitions_offset = _u32(doc, 0x14)
        self.unknown18 = _u32(doc, 0x18)
        self.unknown1C = _u32(doc, 0x1C)
        self.name_count = _u32(doc, 0x20)
        self.names_offset = _u32(doc, 0x24)
        self.declared_size = _u32(doc, 0x28)
        self.unknown2C = _u32(doc, 0x2C)
        self.unknown30 = _u32(doc, 0x30)

        if self.magic != MAGIC:
            raise AdfError("bad magic %08X, expected %08X ('ADF ')"
                           % (self.magic, MAGIC))
        if self.version != SUPPORTED_VERSION:
            raise AdfError("unsupported ADF version %d, expected %d"
                           % (self.version, SUPPORTED_VERSION))
        if self.declared_size != self.total_size:
            raise AdfError("header size %d != document length %d"
                           % (self.declared_size, self.total_size))
        for label, value in (("instances_offset", self.instances_offset),
                             ("definitions_offset", self.definitions_offset),
                             ("names_offset", self.names_offset)):
            if not HEADER_SIZE <= value <= self.total_size:
                raise AdfError("header %s %d is outside the document (%d)"
                               % (label, value, self.total_size))
        if not (self.instances_offset <= self.definitions_offset
                <= self.names_offset):
            raise AdfError("tables are out of order: instances=%d definitions=%d "
                           "names=%d" % (self.instances_offset,
                                         self.definitions_offset,
                                         self.names_offset))
        terminator = self._doc.find(b"\x00", HEADER_SIZE)
        if terminator < 0:
            raise AdfError("the descriptive string at 0x40 is not terminated")
        self.header_string = bytes(self._doc[HEADER_SIZE:terminator]).decode("latin-1")

    # -- name pool ------------------------------------------------------
    def _parse_names(self):
        doc = self._doc
        count = self.name_count
        if count == 0:
            raise AdfError("the name pool is empty (name_count == 0)")
        table = self.names_offset
        if table + count > self.total_size:
            raise AdfError("the %d byte name length table at %d runs past the "
                           "document (%d)" % (count, table, self.total_size))
        lengths = list(doc[table:table + count])
        cursor = table + count
        names = []
        for index, length in enumerate(lengths):
            end = cursor + length
            if end >= self.total_size:
                raise AdfError("name %d (length %d at %d) runs past the document"
                               % (index, length, cursor))
            if doc[end] != 0:
                raise AdfError("name %d at %d (length %d) is not NUL terminated"
                               % (index, cursor, length))
            names.append(bytes(doc[cursor:end]).decode("latin-1"))
            cursor = end + 1
        if cursor != self.total_size:
            raise AdfError("the name pool ended at %d but the document ends at %d"
                           % (cursor, self.total_size))
        return names

    def name_of(self, name_id):
        """Resolve a name pool index (0 means 'unnamed')."""
        if name_id == 0:
            return ""
        if 0 < name_id < len(self.names):
            return self.names[name_id]
        raise AdfError("name id %d is outside the pool (0..%d)"
                       % (name_id, len(self.names) - 1))

    # -- definitions ----------------------------------------------------
    def _parse_definitions(self):
        doc = self._doc
        region_end = self.names_offset
        cursor = self.definitions_offset
        if self.definition_count == 0:
            raise AdfError("the document contains no definitions")
        definitions = []
        for index in range(self.definition_count):
            start = cursor
            _check(doc, start, DEFINITION_RECORD_SIZE, "definition %d" % index,
                   region_end)
            (dtype, size, unknown08, type_hash, name_id, reserved, flags,
             element_hash, unknown58, count) = struct.unpack_from("<10I", doc, start)
            cursor = start + DEFINITION_RECORD_SIZE
            if dtype not in TYPE_NAMES:
                raise AdfError("definition %d at %d has unknown type %d"
                               % (index, start, dtype))
            if reserved:
                raise AdfError("definition %d at %d has a non-zero reserved word"
                               % (index, start))
            name = self.name_of(name_id)
            # The field count word is only meaningful for structures; a Pointer
            # definition stores 16 there and arrays/defaulted natives store 0.
            field_count = count if dtype == TYPE_STRUCTURE else 0
            fields = []
            for position in range(field_count):
                _check(doc, cursor, FIELD_RECORD_SIZE,
                       "field %d of %s" % (position, name), region_end)
                (f_name_id, f_reserved, f_type_hash, f_size, f_offset,
                 f_reserved2, f_default, f_reserved3) = struct.unpack_from(
                    "<8I", doc, cursor)
                if f_reserved or f_reserved2 or f_reserved3:
                    raise AdfError("field %d of %s at %d has a non-zero "
                                   "reserved word %r"
                                   % (position, name, cursor,
                                      (f_reserved, f_reserved2, f_reserved3)))
                fields.append(Field(position, f_name_id, self.name_of(f_name_id),
                                    f_type_hash, f_size, f_offset & 0x00FFFFFF,
                                    f_offset, f_default))
                cursor += FIELD_RECORD_SIZE
            definitions.append(Definition(
                index, dtype, size, unknown08, type_hash, name_id, name, flags,
                element_hash, unknown58, field_count, fields, start))
        if cursor != region_end:
            raise AdfError("the definition table tiled %d of %d bytes"
                           % (cursor - self.definitions_offset,
                              region_end - self.definitions_offset))
        return definitions

    def definition(self, type_hash):
        """Return the Definition with this type hash (KeyError if native/absent)."""
        return self.by_hash[type_hash]

    def resolve(self, type_hash):
        """Return ``("definition", Definition)`` or ``("native", (name, size, fmt))``."""
        found = self.by_hash.get(type_hash)
        if found is not None:
            return "definition", found
        native = NATIVE_TYPES.get(type_hash)
        if native is not None:
            return "native", native
        raise AdfError("type hash %08X is neither defined in this document nor "
                       "a known native type" % type_hash)

    # -- instance table -------------------------------------------------
    def _parse_instances(self):
        gap = self.definitions_offset - self.instances_offset
        if gap <= 0 or gap % INSTANCE_RECORD_SIZE:
            raise AdfError("the instance table (%d..%d) is not a whole number of "
                           "%d byte records" % (self.instances_offset,
                                                self.definitions_offset,
                                                INSTANCE_RECORD_SIZE))
        entries = []
        for index in range(gap // INSTANCE_RECORD_SIZE):
            offset = self.instances_offset + index * INSTANCE_RECORD_SIZE
            name_hash, type_hash, obj_offset, obj_size, pad1, pad2 = \
                struct.unpack_from("<6I", self._doc, offset)
            if pad1 or pad2:
                raise AdfError("instance %d at %d has a non-zero reserved word"
                               % (index, offset))
            if obj_offset + obj_size > self.instances_offset:
                raise AdfError("instance %d (offset %d, size %d) does not fit in "
                               "the data region (ends %d)"
                               % (index, obj_offset, obj_size,
                                  self.instances_offset))
            entries.append(Instance(index, name_hash, type_hash, obj_offset,
                                    obj_size))
        if not entries:
            raise AdfError("the document has no instance table entry")
        kind, info = self.resolve(entries[0].type_hash)
        if kind != "definition":
            raise AdfError("the root instance type %08X is a native type"
                           % entries[0].type_hash)
        return entries

    # -- value layer ----------------------------------------------------
    @property
    def root(self):
        """The document's root instance."""
        return self.entries[0]

    def root_definition(self):
        """Return ``(Definition, offset)`` for the root object."""
        entry = self.entries[0]
        return self.by_hash[entry.type_hash], entry.offset

    def parse_entry(self, index=0):
        """Parse instance ``index`` into plain dicts / lists / scalars."""
        if not 0 <= index < len(self.entries):
            raise AdfError("no instance %d (the document holds %d)"
                           % (index, len(self.entries)))
        entry = self.entries[index]
        kind, definition = self.resolve(entry.type_hash)
        if definition.type != TYPE_STRUCTURE:
            raise AdfError("instance %d type %08X (%s) is not a structure"
                           % (index, entry.type_hash, definition.type_name))
        return self._read_structure(definition, entry.offset, 0, entry.offset)

    def parse_document(self):
        """Alias for :meth:`parse_entry` with index 0."""
        return self.parse_entry(0)

    def _read_native(self, type_hash, offset):
        name, size, fmt = NATIVE_TYPES[type_hash]
        if size is None:
            rel, length = struct.unpack_from("<2I", self._doc, offset)
            start = self.base + rel
            _check(self.payload, start, length, "string value")
            return self.payload[start:start + length].decode("latin-1")
        _check(self._doc, offset, size, "native %s" % name)
        return struct.unpack_from(fmt, self._doc, offset)[0]

    def _read_slot(self, offset):
        """Read the 16 byte array/pointer slot: (offset, capacity, count, 0)."""
        _check(self._doc, offset, ARRAY_SLOT_SIZE, "array slot")
        rel, capacity, count, reserved = struct.unpack_from("<4I", self._doc,
                                                            offset)
        return rel, capacity, count

    def _read_array(self, element_hash, count, offset, instance_base, label):
        if count == 0:
            return []
        kind, info = self.resolve(element_hash)
        if kind == "native":
            name, size, fmt = info
            if size is None:
                raise AdfError("%s: arrays of %s are not supported" % (label, name))
            _check(self._doc, offset, size * count, label)
            return list(struct.unpack_from("<%d%s" % (count, fmt[1]),
                                           self._doc, offset))
        stride = info.size
        if stride <= 0:
            raise AdfError("%s: element type %s has size %d"
                           % (label, info.name or hex(element_hash), stride))
        _check(self._doc, offset, stride * count, label)
        values = []
        for index in range(count):
            here = offset + index * stride
            if info.type == TYPE_STRUCTURE:
                values.append(self._read_structure(info, here, 0, instance_base))
            elif info.type in (TYPE_NATIVE, TYPE_DEFAULTED_NATIVE):
                values.append(self._read_native(info.type_hash, here))
            else:
                values.append({"type": info.type_name, "offset": here,
                               "size": stride})
        return values

    def _read_structure(self, definition, offset, depth, instance_base):
        if depth > MAX_DEPTH:
            raise AdfError("structure nesting deeper than %d (%s)"
                           % (MAX_DEPTH, definition.name))
        out = {}
        unnamed = 0
        for field in definition.fields:
            here = offset + field.offset
            key = field.name
            if not key:
                key = "<unnamed %d>" % unnamed
                unnamed += 1
            kind, info = self.resolve(field.type_hash)
            if kind == "native":
                out[key] = self._read_native(field.type_hash, here)
                continue
            dtype = info.type
            if dtype == TYPE_STRUCTURE:
                out[key] = self._read_structure(info, here, depth + 1,
                                                instance_base)
            elif dtype in (TYPE_ARRAY, TYPE_POINTER):
                rel, _capacity, count = self._read_slot(here)
                if count == 0:
                    out[key] = []
                else:
                    target = instance_base + rel
                    try:
                        out[key] = self._read_array(
                            info.element_type_hash, count, target, instance_base,
                            "%s.%s" % (definition.name, key))
                    except AdfError:
                        if dtype == TYPE_ARRAY:
                            raise
                        # Pointer types point at runtime structures; keep the raw
                        # slot when the target is not a flat ADF array.
                        out[key] = {"kind": "pointer", "offset": rel,
                                    "count": count}
            elif dtype == TYPE_INLINE_ARRAY:
                out[key] = self._read_array(
                    info.element_type_hash, info.unknown58, here, instance_base,
                    "%s.%s (inline)" % (definition.name, key))
            else:
                out[key] = {"type": info.type_name, "offset": here,
                            "size": info.size}
        return out

    # -- convenience ----------------------------------------------------
    def iter_animals(self):
        """Yield one flattened dict per animal in a population document.

        This is the shape the UI layer consumes; it is a convenience wrapper
        over :meth:`parse_entry`, nothing here is format critical.
        """
        root = self.parse_entry(0)
        for population in root.get("Populations", []):
            species_hash = population.get("NameHashId")
            for group_index, group in enumerate(population.get("Groups", [])):
                spawn_area = group.get("SpawnAreadId")
                for animal in group.get("Animals", []):
                    position = animal.get("MapPosition") or {}
                    if not isinstance(position, dict):
                        position = {}
                    x = position.get("X")
                    y = position.get("Y")
                    # MapPosition is present in the schema but the game always
                    # writes (0.0, 0.0) -- it never persists animal positions.
                    # Report None rather than a fake coordinate at the origin.
                    if not x and not y:
                        x = y = None
                    yield {
                        "id": animal.get("Id"),
                        "species_hash": species_hash,
                        "gender": animal.get("Gender"),
                        "weight": animal.get("Weight"),
                        "score": animal.get("Score"),
                        "feature_modifiers": animal.get("FeatureModifiers"),
                        "is_scripted": animal.get("IsScripted"),
                        "visual_variation_seed": animal.get("VisualVariationSeed"),
                        "flags": animal.get("Flags"),
                        "x": x,
                        "y": y,
                        "group": group_index,
                        "spawn_area": spawn_area,
                    }

    def describe(self):
        """Human readable schema dump, useful when exploring a new document."""
        lines = ["ADF v%d  %d bytes  %r  base=%d"
                 % (self.version, self.total_size, self.header_string, self.base),
                 "%d definitions, %d name pool slots, %d instance(s)"
                 % (len(self.definitions), len(self.names), len(self.entries))]
        for entry in self.entries:
            lines.append("  instance %d: type %08X offset %d size %d"
                         % (entry.index, entry.type_hash, entry.offset,
                            entry.size))
        for definition in self.definitions:
            lines.append("  [%2d] %-14s %-42s size=%-5d hash=%08X flags=%08X%s"
                         % (definition.index, definition.type_name,
                            definition.name or "<unnamed>", definition.size,
                            definition.type_hash, definition.flags,
                            (" elem=%08X" % definition.element_type_hash)
                            if definition.element_type_hash else ""))
            for field in definition.fields:
                lines.append("        +%-5d %-30s %08X size=%-4d"
                             % (field.offset, field.name or "<unnamed>",
                                field.type_hash, field.size))
        return "\n".join(lines)

    def __repr__(self):
        return "<Adf v%d definitions=%d names=%d entries=%d>" % (
            self.version, len(self.definitions), len(self.names),
            len(self.entries))


def parse_document(payload):
    """Parse a decompressed SAVE payload (or a bare ADF document)."""
    return Adf(payload)
