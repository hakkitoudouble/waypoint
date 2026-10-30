#!/usr/bin/env python3
"""Self-checking verification of cotw/adf.py against ground truth.

Runs the ADF v4 parser over the real COTW save files and asserts the grammar
facts that were established by disassembling AnimalPopulationScanner.exe and
cross-calibrating the three reference documents:

  * the SAVE/zlib container unwraps to the size promised at offset 8, and the
    ADF document starts 5 bytes into the payload
  * the header, the shared name pool and the definition table are exact: the
    definition region must tile with zero residue, the name pool must consume
    the region exactly, and every definition/field name id must resolve
  * achievements_adf: root AchievementsManagerData_1, two fields, exact values
  * settings_adf:     root SettingsManagerData_1, UInt8 + 239 element Int32 array
  * animal_population_16: root AnimalPopulationReserveData_9, the full animal
    schema, 14 populations each starting with a species hash, and the 65536
    byte hunting pressure map that proves where array payloads live
  * the whole 68 document save corpus parses and satisfies the invariants

Usage:  python tools/verify_adf.py [-v]

Exit status is 0 only when every check passes.
"""

from __future__ import annotations

import argparse
import glob
import os
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from cotw.adf import (  # noqa: E402
    Adf,
    AdfError,
    NATIVE_BY_NAME,
    TYPE_ARRAY,
    TYPE_INLINE_ARRAY,
    TYPE_POINTER,
    TYPE_STRUCTURE,
    TYPE_DEFAULTED_NATIVE,
    open_save,
)

SAVE_ROOT = os.path.join(os.path.expanduser("~"), "Documents",
                         "Avalanche Studios", "COTW", "Saves")
ACCOUNT = "76561199084637132"

ACHIEVEMENTS = "achievements_adf"
SETTINGS = "settings_adf"
POPULATION = "animal_population_16"

U8 = NATIVE_BY_NAME["UInt8"][0]
U32 = NATIVE_BY_NAME["UInt32"][0]
I32 = NATIVE_BY_NAME["Int32"][0]
F32 = NATIVE_BY_NAME["Float"][0]

RESULTS = []


def check(label, fn):
    """Run one check; ``fn`` returns a detail string or raises."""
    try:
        detail = fn()
    except AssertionError as exc:
        RESULTS.append((label, False, str(exc) or "assertion failed"))
        return False
    except Exception as exc:  # noqa: BLE001 - report, never crash the report
        RESULTS.append((label, False, "%s: %s" % (type(exc).__name__, exc)))
        return False
    RESULTS.append((label, True, detail or ""))
    return True


def eq(actual, expected, what):
    assert actual == expected, "%s is %r, expected %r" % (what, actual, expected)
    return actual


def save_path(name):
    path = os.path.join(SAVE_ROOT, ACCOUNT, name)
    assert os.path.isfile(path), "missing ground truth file %s" % path
    return path


_POPULATION_DOC = None


def population_doc():
    """Parse animal_population_16 once and reuse it across checks."""
    global _POPULATION_DOC
    if _POPULATION_DOC is None:
        _POPULATION_DOC = Adf(open_save(save_path(POPULATION)))
    return _POPULATION_DOC


# --------------------------------------------------------------------------
# container, wrapper, base
# --------------------------------------------------------------------------
def check_container():
    raw = open(save_path(ACHIEVEMENTS), "rb").read()
    payload = open_save(save_path(ACHIEVEMENTS))
    eq(raw[:4], b"SAVE", "container magic")
    eq(raw[0x10:0x14], b"COMP", "container block tag")
    declared = struct.unpack_from("<I", raw, 8)[0]
    eq(len(payload), declared, "decompressed size vs header size")
    eq(payload[:5], b"\x01\x01\x00\x00\x00", "payload wrapper prefix")
    doc = Adf(payload)
    eq(doc.base, 5, "ADF base inside the payload")
    eq(doc.version, 4, "ADF version")
    eq(doc.magic, 0x41444620, "ADF magic")
    eq(doc.declared_size, len(payload) - 5, "header total_size")
    # a bare document must parse to exactly the same values
    bare = Adf(payload[5:])
    eq(bare.base, 0, "ADF base for a bare document")
    eq(bare.parse_entry(0), doc.parse_entry(0), "bare vs wrapped parse")
    return "payload %d bytes, declared %d" % (len(payload), declared)


def check_errors():
    payload = bytearray(open_save(save_path(ACHIEVEMENTS)))
    cases = (
        (lambda b: b.__setitem__(slice(5, 9), b"NOPE"), "bad magic"),
        (lambda b: b.__setitem__(slice(9, 13), struct.pack("<I", 3)), "version 3"),
        (lambda b: b.__delitem__(slice(200, None)), "truncated document"),
        (lambda b: b.__setitem__(slice(0x24, 0x28), struct.pack("<I", 0xFFFFFF)),
         "names offset out of range"),
        (lambda b: b.__setitem__(slice(0x10, 0x14), struct.pack("<I", 99)),
         "definition count too large"),
    )
    for mutate, label in cases:
        broken = bytearray(payload)
        mutate(broken)
        try:
            Adf(bytes(broken))
        except AdfError:
            continue
        raise AssertionError("%s was accepted instead of raising AdfError" % label)
    try:
        open_save(os.path.join(SAVE_ROOT, ACCOUNT, "steam_autocloud.vdf"))
    except AdfError:
        pass
    else:
        raise AssertionError("a non-SAVE file was accepted")
    return "%d corruptions + 1 foreign file rejected" % len(cases)


# --------------------------------------------------------------------------
# achievements_adf
# --------------------------------------------------------------------------
def check_achievements():
    doc = Adf(open_save(save_path(ACHIEVEMENTS)))
    eq(doc.definition_count, 1, "definition count")
    eq(len(doc.definitions), 1, "parsed definitions")
    eq(len(doc.names), 4, "name pool slots")
    eq(doc.definitions_offset, 136, "definitions offset")
    eq(doc.names_offset, 240, "names offset")
    eq(doc.names_offset - doc.definitions_offset, 40 + 2 * 32,
       "definition region size (40 byte header + 2 * 32 byte fields)")

    root = doc.definitions[0]
    eq(root.type, TYPE_STRUCTURE, "root type")
    eq(root.name, "AchievementsManagerData_1", "root name")
    eq(root.size, 8, "root size")
    eq(root.type_hash, 0xF612943C, "root type hash")
    eq(root.field_count, 2, "root field_count word")
    eq([f.name for f in root.fields],
       ["AlreadyConverted", "DistanceTravelled"], "root field names")
    eq([(f.type_hash, f.size, f.offset) for f in root.fields],
       [(U8, 1, 0), (F32, 4, 4)], "root field (hash, size, offset)")

    entry = doc.root
    eq((entry.offset, entry.size), (100, 8), "instance offset/size")

    values = doc.parse_entry(0)
    eq(values["AlreadyConverted"], 1, "AlreadyConverted")
    distance = values["DistanceTravelled"]
    assert 1.4e6 < distance < 1.6e6, \
        "DistanceTravelled is %r, expected ~1.48e6" % (distance,)
    return "AlreadyConverted=1, DistanceTravelled=%.2f" % distance


# --------------------------------------------------------------------------
# settings_adf
# --------------------------------------------------------------------------
def check_settings():
    doc = Adf(open_save(save_path(SETTINGS)))
    eq(doc.definition_count, 2, "definition count")
    eq([d.name for d in doc.definitions],
       ["SettingsManagerData_1", "A[int32]"], "definition names")
    root = doc.definitions[0]
    eq(root.size, 24, "root size")
    eq(root.type_hash, 0x9BE860F7, "root type hash")
    eq([(f.name, f.type_hash, f.size, f.offset) for f in root.fields],
       [("AlreadyConverted", U8, 1, 0), ("Settings", 0xFB9FD4CC, 8, 8)],
       "root fields")
    array = doc.definitions[1]
    eq(array.type, TYPE_ARRAY, "array definition type")
    eq(array.element_type_hash, I32, "array element hash")
    eq(array.size, 16, "array definition size")
    eq(array.unknown58, 0, "array unknown58")

    values = doc.parse_entry(0)
    # AlreadyConverted is the schema-migration flag: it is 1 in
    # achievements_adf and 0 here, so the *schema* is what this check pins.
    eq(values["AlreadyConverted"], 0, "settings AlreadyConverted")
    data = values["Settings"]
    eq(len(data), 239, "Settings element count")
    eq(data[:6], [0, 0, 16, 3, 1, 3], "Settings first values")
    assert all(isinstance(v, int) and -1 <= v <= 65536 for v in data), \
        "Settings is not a run of small Int32 values: %r" % (data[:16],)
    eq(min(data), -1, "Settings minimum (a signed Int32)")
    eq(max(data), 3840, "Settings maximum")
    return "239 Int32 values, first %r" % (data[:6],)


# --------------------------------------------------------------------------
# animal_population_16
# --------------------------------------------------------------------------
ANIMAL_FIELDS = [
    ("Gender", U8, 1, 0),
    ("Weight", F32, 4, 4),
    ("Score", F32, 4, 8),
    ("FeatureModifiers", 0x8CEF8F02, 1, 12),
    ("IsScripted", U8, 1, 13),
    ("VisualVariationSeed", U32, 4, 16),
]


def check_population_schema():
    doc = population_doc()
    eq(len(doc.definitions), 14, "definition count")
    eq(len(doc.names), 43, "name pool slots")
    root = doc.definitions[0]
    eq(root.name, "AnimalPopulationReserveData_9", "root name")
    eq(root.type_hash, 0x480C5171, "root type hash")
    eq(root.size, 48, "root size")
    eq([f.name for f in root.fields],
       ["AlreadyConverted", "Populations", "HuntingPressureMap", "ReserveSeed",
        "AtypicalsCooldownTime"], "root field names")
    eq([f.offset for f in root.fields], [0, 8, 24, 40, 44], "root field offsets")
    eq([f.size for f in root.fields], [1, 8, 8, 4, 2], "root field sizes")

    by_name = {d.name: d for d in doc.definitions}
    pop = by_name["AnimalPopulationData_8"]
    eq(pop.size, 96, "AnimalPopulationData_8 size")
    eq([f.name for f in pop.fields],
       ["NameHashId", "Groups", "RepopulateData", "InitialTotalScore",
        "InitialNumAnimals", "Revision", "GroupToWarrenId",
        "RepopulationSkipCounter", "ConditionsFulfilled"],
       "population field names")
    eq(pop.fields[0].offset, 0, "NameHashId offset")
    eq(pop.fields[0].type_hash, U32, "NameHashId is a UInt32 species hash")

    group = by_name["AnimalGroupData_5"]
    eq(group.size, 48, "AnimalGroupData_5 size")
    eq([f.name for f in group.fields],
       ["SpawnAreadId", "NeedZonePathGuids", "Animals", "Id"],
       "group field names")

    animal = by_name["AnimalData_5"]
    eq(animal.size, 32, "AnimalData_5 size")
    eq([(f.name, f.type_hash, f.size, f.offset) for f in animal.fields][:6],
       ANIMAL_FIELDS, "animal field layout (name, hash, size, offset)")
    eq([f.name for f in animal.fields],
       ["Gender", "Weight", "Score", "FeatureModifiers", "IsScripted",
        "VisualVariationSeed", "Id", "MapPosition"], "animal field names")
    position = animal.field("MapPosition")
    eq(position.offset, 24, "MapPosition offset")
    eq(position.type_hash, by_name["Vector2_1"].type_hash, "MapPosition type")
    eq([f.name for f in by_name["Vector2_1"].fields], ["X", "Y"],
       "Vector2_1 fields")
    return "%d definitions, %d name slots" % (len(doc.definitions), len(doc.names))


def check_population_slots():
    """The array slot is 16 bytes: (offset, capacity, count, 0)."""
    doc = population_doc()
    entry = doc.root
    eq(entry.offset, 104, "root instance offset")
    eq(entry.size, 306528, "root instance size")

    slot = struct.unpack_from("<4I", doc._doc, entry.offset + 8)
    eq(slot, (48, 16, 14, 0), "Populations slot (offset, capacity, count, pad)")
    eq(entry.offset + slot[0], 152, "Populations array offset")

    root = doc.parse_entry(0)
    populations = root["Populations"]
    eq(len(populations), slot[2], "parsed populations vs the slot's count word")
    eq(len(populations), 14, "Populations count is 14, not the capacity of 16")
    eq(len({p["NameHashId"] for p in populations}), 14, "distinct species hashes")
    for index, population in enumerate(populations):
        assert population["NameHashId"], \
            "population %d has no species hash at +0" % index

    # The capacity is *not* the count: element 14 would start at
    # 152 + 14 * 96 = 1496, which is exactly where population 0's group array
    # begins, i.e. the 15th/16th "populations" would be AnimalGroupData_5
    # records parsed as populations.
    end_of_array = 152 + slot[2] * 96
    groups_rel = struct.unpack_from("<I", doc._doc, entry.offset + slot[0] + 8)[0]
    groups_start = entry.offset + groups_rel
    eq(end_of_array, groups_start,
       "end of the population array vs start of population 0's groups")
    eq(len(populations[0]["Groups"]), 199, "population 0 group count")
    return "slot=(48,16,14,0); 14 populations end exactly at %d" % end_of_array


def check_population_values():
    doc = population_doc()
    populations = doc.parse_entry(0)["Populations"]
    total = 0
    for population in populations:
        for group in population["Groups"]:
            for animal in group["Animals"]:
                total += 1
                gender = animal["Gender"]
                assert gender in (0, 1, 2), "Gender %r out of range" % (gender,)
                weight = animal["Weight"]
                assert 0.0 <= weight <= 2000.0, "Weight %r out of range" % (weight,)
                score = animal["Score"]
                assert 0.0 <= score <= 1000.0, "Score %r out of range" % (score,)
                modifiers = animal["FeatureModifiers"]
                assert isinstance(modifiers, dict), \
                    "FeatureModifiers did not resolve to a structure"
                assert modifiers["Flags"] in (0, 1, 2, 3), \
                    "FeatureModifiers.Flags is %r" % (modifiers,)
    eq(total, 4004, "total animal count")

    # Layout-sensitive anchors: any drift in the record grammar moves the array
    # bases and changes these numbers.
    eq([len(p["Groups"]) for p in populations],
       [199, 98, 84, 48, 107, 56, 199, 144, 37, 150, 39, 32, 91, 108],
       "groups per population")
    eq([sum(len(g["Animals"]) for g in p["Groups"]) for p in populations],
       [248, 299, 302, 192, 792, 308, 249, 347, 146, 150, 201, 237, 288, 245],
       "animals per population")
    eq([p["NameHashId"] for p in populations],
       [0x0068A2CA, 0x08D561A7, 0x1998199C, 0x2D774864, 0x5A6BDC6E,
        0x739A4F18, 0x8527AFD1, 0x8FF3825F, 0xA46DF63D, 0xBA302E00,
        0xC1784891, 0xC7863902, 0xCB0DA701, 0xD0BAD3B3],
       "species hashes in definition order")
    return "%d animals over %d populations" % (total, len(populations))


def check_pressure_map():
    doc = population_doc()
    entry = doc.root
    slot = struct.unpack_from("<4I", doc._doc, entry.offset + 24)
    offset, capacity, count, _pad = slot
    eq(capacity, 32, "HuntingPressureMap capacity")
    eq(count, 65536, "HuntingPressureMap element count (256*256)")
    eq(entry.offset + offset, entry.offset + entry.size - 65536,
       "the pressure map is the last 64 KiB of the instance")
    values = doc.parse_entry(0)["HuntingPressureMap"]
    eq(len(values), 65536, "parsed pressure map length")
    eq(len(set(values)), 14, "distinct pressure levels")
    eq(values[:8], [0] * 8, "the pressure map starts empty")
    return "65536 bytes at instance_end-65536, %d levels" % len(set(values))


def check_positions_not_persisted():
    """MapPosition/Id exist in the schema but the game always writes zero."""
    total = 0
    non_zero = 0
    for name in sorted(glob.glob(os.path.join(SAVE_ROOT, ACCOUNT,
                                              "animal_population_*"))):
        doc = Adf(open_save(name))
        for population in doc.parse_entry(0).get("Populations", []):
            for group in population.get("Groups", []):
                for animal in group.get("Animals", []):
                    total += 1
                    if animal["MapPosition"]["X"] or animal["MapPosition"]["Y"] \
                            or animal["Id"]:
                        non_zero += 1
    eq(non_zero, 0, "animals with a non-zero MapPosition/Id")
    assert total > 9000, "only %d animals scanned" % total
    return "%d animals, every MapPosition=(0.0, 0.0)" % total


# --------------------------------------------------------------------------
# whole-corpus invariants
# --------------------------------------------------------------------------
def check_whole_corpus():
    files = [p for p in sorted(glob.glob(os.path.join(SAVE_ROOT, ACCOUNT, "*")))
             if os.path.isfile(p) and not p.endswith(".vdf")]
    assert len(files) >= 60, "only %d save files found" % len(files)
    for path in files:
        name = os.path.basename(path)
        doc = Adf(open_save(path))
        eq(len(doc.definitions), doc.definition_count, "%s: definition count" % name)
        tiled = doc.definitions_offset + sum(
            40 + (d.field_count * 32 if d.type == TYPE_STRUCTURE else 0)
            for d in doc.definitions)
        eq(tiled, doc.names_offset, "%s: definition region tiling" % name)
        eq(doc.names_offset + doc.name_count
           + sum(len(n) + 1 for n in doc.names), doc.total_size,
           "%s: name pool tiling" % name)
        for definition in doc.definitions:
            assert definition.type in (TYPE_STRUCTURE, TYPE_POINTER, TYPE_ARRAY,
                                       TYPE_INLINE_ARRAY, 5,
                                       TYPE_DEFAULTED_NATIVE), \
                "%s: definition type %d" % (name, definition.type)
            assert not (definition.flags & ~0x00018003), \
                "%s: unexpected flags %08X" % (name, definition.flags)
            for field in definition.fields:
                assert field.name_id == 0 or field.name, "%s: unresolved name" % name
        doc.parse_entry(0)
    return "%d documents: tables tile exactly, every root parsed" % len(files)


CHECKS = [
    ("container, wrapper and ADF base", check_container),
    ("malformed input rejected", check_errors),
    ("achievements_adf ground truth", check_achievements),
    ("settings_adf ground truth", check_settings),
    ("animal_population_16 schema", check_population_schema),
    ("animal_population_16 array slots", check_population_slots),
    ("animal_population_16 values", check_population_values),
    ("animal_population_16 pressure map", check_pressure_map),
    ("animal positions are not persisted", check_positions_not_persisted),
    ("whole save corpus invariants", check_whole_corpus),
]


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Verify the ADF v4 parser against ground truth.")
    parser.add_argument("-v", "--verbose", action="store_true",
                        help="accepted for symmetry; failures always show reasons")
    parser.parse_args(argv)

    print("ADF v4 parser verification")
    print("ground truth: %s" % os.path.join(SAVE_ROOT, ACCOUNT))
    print("=" * 78)
    for label, fn in CHECKS:
        check(label, fn)
    width = max(len(label) for label, _ in CHECKS)
    failed = 0
    for label, ok, detail in RESULTS:
        if not ok:
            failed += 1
        print("%-4s  %-*s  %s" % ("PASS" if ok else "FAIL", width, label,
                                  detail.replace("\n", " ")[:150]))
    print("=" * 78)
    total = len(RESULTS)
    if failed:
        print("RESULT: FAIL  (%d of %d checks failed)" % (failed, total))
        return 1
    print("RESULT: PASS  (%d of %d checks passed)" % (total, total))
    return 0


if __name__ == "__main__":
    sys.exit(main())
