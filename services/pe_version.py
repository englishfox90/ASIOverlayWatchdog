"""Read a Windows PE file's FileVersion without a third-party dependency.

Pure-Python walk of the PE structures — DOS header -> PE header -> resource
data directory -> ``RT_VERSION`` -> ``VS_FIXEDFILEINFO`` — so nothing here
needs ``pefile`` or ``pywin32``, both of which would be new runtime
dependencies for a single field.

Extracted from ``nina_plugin_install`` (which compares a bundled DLL against
an installed one) because it is a distinct, independently testable concern
that knows nothing about NINA.

Handles both PE32 (``0x10B`` — .NET AnyCPU assemblies, which is what NINA
plugins are) and PE32+ (``0x20B``). Anything malformed returns ``None``
rather than raising; callers are expected to have a fallback.
"""
from __future__ import annotations

import struct


_RT_VERSION = 16
_FIXEDFILEINFO_SIGNATURE = b"\xbd\x04\xef\xfe"  # 0xFEEF04BD little-endian


def _rva_to_offset(sections, rva: int):
    for virt_addr, virt_size, raw_size, raw_ptr in sections:
        span = max(virt_size, raw_size)
        if virt_addr <= rva < virt_addr + span:
            return raw_ptr + (rva - virt_addr)
    return None


def _first_resource_entry(data: bytes, dir_offset: int, want_id=None):
    """Return the OffsetToData word of the first (or matching) directory entry."""
    named, ids = struct.unpack_from("<HH", data, dir_offset + 12)
    base = dir_offset + 16
    for index in range(named + ids):
        entry_id, offset_to_data = struct.unpack_from("<II", data, base + index * 8)
        if want_id is None or (not entry_id & 0x80000000 and entry_id == want_id):
            return offset_to_data
    return None


def read_file_version(path: str):
    """Windows FileVersion of a PE file as ``"1.2.3.4"``, or ``None``.

    Pure-Python PE walk (no pefile/pywin32 dependency): DOS header -> PE header
    -> resource data directory -> RT_VERSION -> VS_FIXEDFILEINFO. Anything
    unexpected returns ``None`` and callers fall back to a byte comparison.
    """
    try:
        with open(path, "rb") as handle:
            data = handle.read()
    except OSError:
        return None

    try:
        if data[:2] != b"MZ":
            return None
        pe_offset = struct.unpack_from("<I", data, 0x3C)[0]
        if data[pe_offset:pe_offset + 4] != b"PE\0\0":
            return None

        coff = pe_offset + 4
        num_sections = struct.unpack_from("<H", data, coff + 2)[0]
        opt_size = struct.unpack_from("<H", data, coff + 16)[0]
        opt = coff + 20
        magic = struct.unpack_from("<H", data, opt)[0]
        if magic == 0x20B:        # PE32+
            dir_start, count_at = opt + 112, opt + 108
        elif magic == 0x10B:      # PE32 — .NET AnyCPU builds land here
            dir_start, count_at = opt + 96, opt + 92
        else:
            return None

        # Entry 2 is the resource directory; a short table means no resources.
        if struct.unpack_from("<I", data, count_at)[0] < 3:
            return None

        rsrc_rva = struct.unpack_from("<I", data, dir_start + 16)[0]
        if not rsrc_rva:
            return None

        sections = []
        table = opt + opt_size
        for index in range(num_sections):
            entry = table + index * 40
            virt_size, virt_addr, raw_size, raw_ptr = struct.unpack_from("<IIII", data, entry + 8)
            sections.append((virt_addr, virt_size, raw_size, raw_ptr))

        rsrc_offset = _rva_to_offset(sections, rsrc_rva)
        if rsrc_offset is None:
            return None

        type_entry = _first_resource_entry(data, rsrc_offset, _RT_VERSION)
        if type_entry is None or not type_entry & 0x80000000:
            return None
        name_dir = rsrc_offset + (type_entry & 0x7FFFFFFF)

        name_entry = _first_resource_entry(data, name_dir)
        if name_entry is None or not name_entry & 0x80000000:
            return None
        lang_dir = rsrc_offset + (name_entry & 0x7FFFFFFF)

        lang_entry = _first_resource_entry(data, lang_dir)
        if lang_entry is None or lang_entry & 0x80000000:
            return None
        data_entry = rsrc_offset + lang_entry

        blob_rva, blob_size = struct.unpack_from("<II", data, data_entry)
        blob_offset = _rva_to_offset(sections, blob_rva)
        if blob_offset is None:
            return None
        blob = data[blob_offset:blob_offset + blob_size]

        sig = blob.find(_FIXEDFILEINFO_SIGNATURE)
        if sig < 0:
            return None
        version_ms, version_ls = struct.unpack_from("<II", blob, sig + 8)
        return "{}.{}.{}.{}".format(
            version_ms >> 16, version_ms & 0xFFFF,
            version_ls >> 16, version_ls & 0xFFFF,
        )
    except (struct.error, IndexError):
        return None
