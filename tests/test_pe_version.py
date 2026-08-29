"""Tests for services/pe_version.py — Windows FileVersion out of a PE file.

The DLLs are synthesised rather than mocked: :func:`write_fake_dll` builds a
structurally valid PE (both PE32 and PE32+) carrying a real RT_VERSION
resource, so the parser is exercised against actual bytes. Shared with
``test_nina_plugin_install.py``, which imports the builder from here.
"""
import os
import struct

import pytest

from services import pe_version
from services.pe_version import read_file_version


# ---------------------------------------------------------------------------
# Synthetic PE with a version resource
# ---------------------------------------------------------------------------

_RSRC_RVA = 0x1000
_RAW_PTR = 0x200


def _version_resource(version):
    major, minor, build, revision = version
    fixed = struct.pack(
        "<13I",
        0xFEEF04BD, 0x00010000,
        (major << 16) | minor, (build << 16) | revision,
        (major << 16) | minor, (build << 16) | revision,
        0x3F, 0, 4, 1, 0, 0, 0,
    )
    key = "VS_VERSION_INFO\0".encode("utf-16-le")
    header = struct.pack("<HHH", 6 + len(key) + len(fixed), 52, 0) + key
    header += b"\x00" * ((4 - len(header) % 4) % 4)
    return header + fixed


def _resource_section(blob):
    def dir_header(id_count):
        return struct.pack("<IIHHHH", 0, 0, 0, 0, 0, id_count)

    root = dir_header(1) + struct.pack("<II", pe_version._RT_VERSION, 0x80000000 | 24)
    name_dir = dir_header(1) + struct.pack("<II", 1, 0x80000000 | 48)
    lang_dir = dir_header(1) + struct.pack("<II", 1033, 72)
    data_entry = struct.pack("<IIII", _RSRC_RVA + 88, len(blob), 0, 0)
    return root + name_dir + lang_dir + data_entry + blob


def write_fake_dll(path, version=(1, 0, 0, 0), filler=b"", magic=0x20B):
    """Write a minimal DLL whose FileVersion is ``version``.

    ``magic`` selects PE32+ (0x20B) or PE32 (0x10B). Both matter: a .NET
    AnyCPU plugin — which is what NINA loads — is PE32.
    """
    rsrc = _resource_section(_version_resource(version)) + filler
    raw_size = (len(rsrc) + 0x1FF) & ~0x1FF

    dos = bytearray(0x80)
    dos[0:2] = b"MZ"
    struct.pack_into("<I", dos, 0x3C, 0x80)

    if magic == 0x10B:
        opt_size, count_at, dir_at = 224, 92, 96
    else:
        opt_size, count_at, dir_at = 240, 108, 112

    coff = struct.pack("<HHIIIHH", 0x8664, 1, 0, 0, 0, opt_size, 0x2022)

    opt = bytearray(opt_size)
    struct.pack_into("<H", opt, 0, magic)
    struct.pack_into("<I", opt, count_at, 16)      # NumberOfRvaAndSizes
    struct.pack_into("<II", opt, dir_at + 16, _RSRC_RVA, len(rsrc))

    section = struct.pack(
        "<8sIIIIIIHHI", b".rsrc", len(rsrc), _RSRC_RVA,
        raw_size, _RAW_PTR, 0, 0, 0, 0, 0x40000040,
    )

    head = bytes(dos) + b"PE\0\0" + coff + bytes(opt) + section
    body = head + b"\x00" * (_RAW_PTR - len(head)) + rsrc
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as handle:
        handle.write(body)
    return path


# ---------------------------------------------------------------------------
# Reading versions
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("magic", [0x20B, 0x10B], ids=["pe32plus", "pe32"])
def test_reads_file_version_from_pe(tmp_path, magic):
    path = write_fake_dll(str(tmp_path / f"a{magic}.dll"), (3, 2, 0, 9001), magic=magic)
    assert read_file_version(path) == "3.2.0.9001"


def test_file_version_none_when_no_resource_directory(tmp_path):
    """A DLL whose data-directory table is too short to hold entry 2."""
    path = write_fake_dll(str(tmp_path / "short.dll"), (1, 0, 0, 0))
    data = bytearray(open(path, "rb").read())
    struct.pack_into("<I", data, 0x80 + 4 + 20 + 108, 2)  # NumberOfRvaAndSizes
    trimmed = tmp_path / "trimmed.dll"
    trimmed.write_bytes(bytes(data))
    assert read_file_version(str(trimmed)) is None


def test_file_version_none_for_non_pe(tmp_path):
    path = tmp_path / "junk.dll"
    path.write_bytes(b"this is not a PE file at all")
    assert read_file_version(str(path)) is None


def test_file_version_none_for_missing_file(tmp_path):
    assert read_file_version(str(tmp_path / "absent.dll")) is None


def test_file_version_none_for_truncated_pe(tmp_path):
    full = write_fake_dll(str(tmp_path / "a.dll"), (1, 0, 0, 0))
    data = open(full, "rb").read()
    truncated = tmp_path / "cut.dll"
    truncated.write_bytes(data[:100])
    assert read_file_version(str(truncated)) is None
