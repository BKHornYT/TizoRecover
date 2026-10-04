"""What the bytes look like: signatures, extents, and integrity checks.

Each format answers three questions:

* where does a file of this type start (``magics``)?
* how long is it once you have found the start (``resolve``)?
* is what we found actually intact (``validate``)?

``resolve`` and ``validate`` read through a :class:`ByteSource`, so they
can walk structures (PNG chunks, MP4 boxes, SQLite pages) without the
caller having to hold a large window in memory.
"""

from __future__ import annotations

import struct
import zlib
from dataclasses import dataclass, field
from typing import Callable, Protocol

from tizorecover.engine.results import Verdict

KIB = 1024
MIB = 1024 * 1024
MIN_EXTENT = 32


class ByteSource(Protocol):
    size: int

    def at(self, offset: int, length: int) -> bytes: ...


@dataclass
class Extent:
    """How far a file of this type runs, and what we think of it."""

    size: int
    verdict: Verdict = Verdict.SUSPECT
    notes: list[str] = field(default_factory=list)
    complete: bool = True


class ByteSourceView:
    """Adapts a :class:`~recover.blockdev.BlockReader` to ``ByteSource``."""

    def __init__(self, reader) -> None:
        self._reader = reader
        self.size = reader.size

    def at(self, offset: int, length: int) -> bytes:
        if offset < 0 or length <= 0 or offset >= self.size:
            return b""
        return self._reader.read_at(offset, min(length, self.size - offset))


@dataclass(eq=False)
class Format:
    name: str
    ext: str
    magics: tuple[bytes, ...]
    max_size: int = 64 * MIB
    footer: bytes | None = None
    resolve: Callable[[ByteSource, int, int], Extent | None] | None = None
    validate: Callable[[ByteSource, int, int], tuple[Verdict, list[str]]] | None = None
    category: str = "document"
    confidence: float = 0.5
    back: int = 0
    # Cheap test on the bytes already in memory (``buf`` holds the hit at
    # ``i``). False rejects without touching the disk; whatever it cannot see
    # (the header runs past ``buf``) must answer True and leave it to resolve.
    quick: Callable[[bytes, int], bool] | None = None


def _s8(src: ByteSource, off: int, n: int) -> bytes:
    return src.at(off, n)


def _u8(src: ByteSource, off: int) -> int:
    b = src.at(off, 1)
    return b[0] if b else 0


def _need(src: ByteSource, off: int, n: int) -> bool:
    return off >= 0 and len(src.at(off, n)) == n


def _u16le(src: ByteSource, off: int) -> int:
    b = src.at(off, 2)
    return struct.unpack("<H", b)[0] if len(b) == 2 else 0


def _u16be(src: ByteSource, off: int) -> int:
    b = src.at(off, 2)
    return struct.unpack(">H", b)[0] if len(b) == 2 else 0


def _u32le(src: ByteSource, off: int) -> int:
    b = src.at(off, 4)
    return struct.unpack("<I", b)[0] if len(b) == 4 else 0


def _u32be(src: ByteSource, off: int) -> int:
    b = src.at(off, 4)
    return struct.unpack(">I", b)[0] if len(b) == 4 else 0


def _u64le(src: ByteSource, off: int) -> int:
    b = src.at(off, 8)
    return struct.unpack("<Q", b)[0] if len(b) == 8 else 0


def _u64be(src: ByteSource, off: int) -> int:
    b = src.at(off, 8)
    return struct.unpack(">Q", b)[0] if len(b) == 8 else 0


def _printable(data: bytes, ratio: float = 0.85) -> bool:
    if not data:
        return False
    ok = sum(1 for b in data if 32 <= b < 127 or b in (9, 10, 13))
    return ok / len(data) >= ratio


BLANK_BLOCK = 4096
_ZERO_BLOCK = b"\x00" * BLANK_BLOCK


def _until_blank(src: ByteSource, off: int, limit: int, cap: int) -> int:
    """Where data that has no length field most likely ends.

    Compressed media never holds 4 KiB of zeros, but the free space after a
    deleted file usually does, so the first zero block (or ``limit``, or
    ``cap``) is the best end there is. Returns an absolute offset.
    """
    end = min(limit, src.size, off + cap)
    pos = off
    step = 1 * MIB
    while pos < end:
        window = src.at(pos, min(step + BLANK_BLOCK, end - pos))
        if not window:
            break
        idx = window.find(_ZERO_BLOCK)
        if idx >= 0:
            return pos + idx
        if len(window) <= BLANK_BLOCK:
            break
        pos += len(window) - BLANK_BLOCK
    return end


def _have(buf: bytes, i: int, n: int) -> bool:
    return i >= 0 and i + n <= len(buf)


# --------------------------------------------------------------------------
# JPEG
# --------------------------------------------------------------------------


# Markers that may follow SOI directly: APPn, DQT, DHT, SOFn, DRI, COM.
_JPEG_FIRST = frozenset(range(0xE0, 0xF0)) | {0xDB, 0xC4, 0xC0, 0xC1, 0xC2, 0xDD, 0xFE}
JPEG_MAX = 64 * MIB


def _jpeg_quick(buf: bytes, i: int) -> bool:
    if not _have(buf, i, 6):
        return True
    if buf[i + 3] not in _JPEG_FIRST:
        return False
    seg = int.from_bytes(buf[i + 4:i + 6], "big")
    if seg < 2:
        return False
    nxt = i + 4 + seg
    return not _have(buf, nxt, 1) or buf[nxt] == 0xFF


def _jpeg_walk(src: ByteSource, off: int, limit: int) -> Extent | None:
    """Walk JPEG segments to the start of scan, then to the EOI marker.

    Segments follow each other with no gap (only 0xFF fill bytes may sit
    between them), so the walk is strict: random bytes that happen to start
    with FF D8 FF fail within a marker or two instead of passing as a photo.
    """
    end = min(limit, src.size)
    pos = off + 2
    reached_scan = False
    first = True
    while pos + 4 <= end:
        head = src.at(pos, 4)
        if len(head) < 4 or head[0] != 0xFF:
            return None
        while head[1] == 0xFF:                       # fill bytes
            pos += 1
            head = src.at(pos, 4)
            if len(head) < 4:
                return None
        code = head[1]
        if first and code not in _JPEG_FIRST:
            return None
        first = False
        pos += 2
        if code == 0xD9:
            return Extent(pos - off, Verdict.VALID, ["ends at EOI"])
        if code in (0x00, 0x01) or 0xD0 <= code <= 0xD8:
            return None                              # not allowed between segments
        seg_len = int.from_bytes(head[2:4], "big")
        if seg_len < 2 or pos + seg_len > src.size:
            return None
        pos += seg_len
        if code == 0xDA:
            reached_scan = True
            break
    if not reached_scan:
        return None
    # FF D9 cannot occur inside entropy-coded data (a data FF is followed by
    # 00), so the first one is the end. Search in steps: most photos are a
    # few MB, and reading a fixed 8 MB per photo doubled the I/O of a scan.
    scan_from = pos
    stop = min(end, off + JPEG_MAX)
    step = 1 * MIB
    while pos < stop:
        window = src.at(pos, min(step + 1, stop - pos))
        if not window:
            break
        idx = window.find(b"\xff\xd9")
        if idx >= 0:
            return Extent(pos + idx + 2 - off, Verdict.VALID, ["ends at EOI after scan data"])
        if len(window) <= 1:
            break
        pos += len(window) - 1
    tail = _until_blank(src, scan_from, limit, JPEG_MAX)
    return Extent(max(tail, scan_from) - off, Verdict.PARTIAL, ["entropy data truncated"], False)


def _jpeg_validate(src: ByteSource, off: int, size: int) -> tuple[Verdict, list[str]]:
    reasons: list[str] = []
    if not src.at(off, 3).startswith(b"\xff\xd8\xff"):
        return Verdict.INVALID, ["no SOI marker"]
    end = off + size
    if src.at(end - 2, 2) == b"\xff\xd9":
        reasons.append("EOI at expected end")
        return Verdict.VALID, reasons
    reasons.append("no EOI at end; entropy data may be truncated")
    return Verdict.PARTIAL, reasons


# --------------------------------------------------------------------------
# PNG
# --------------------------------------------------------------------------


def _png_walk(src: ByteSource, off: int, limit: int) -> Extent | None:
    pos = off + 8
    saw_ihdr = False
    saw_idat = False
    while pos + 8 <= limit and pos + 8 <= src.size:
        length = _u32be(src, pos)
        ctype = src.at(pos + 4, 4)
        if length > 512 * MIB or pos + 12 + length > src.size:
            break
        if ctype == b"IHDR":
            saw_ihdr = True
        elif ctype == b"IDAT":
            saw_idat = True
        elif ctype == b"IEND":
            if not (saw_ihdr and saw_idat):
                return None
            return Extent(pos + 12 - off, Verdict.VALID, ["ends at IEND"])
        pos += 12 + length
    if saw_ihdr and saw_idat:
        return Extent(pos - off, Verdict.PARTIAL, ["data ends mid-chunk; true size unknown"], False)
    return None


def _png_validate(src: ByteSource, off: int, size: int) -> tuple[Verdict, list[str]]:
    reasons: list[str] = []
    pos = off + 8
    bad_crc = 0
    chunks = 0
    saw_iend = False
    while pos + 8 <= off + size:
        length = _u32be(src, pos)
        ctype = src.at(pos + 4, 4)
        if pos + 12 + length > off + size:
            break
        if ctype not in (b"IDAT", b"IEND"):
            body = src.at(pos + 4, 4 + length)
            stored = _u32be(src, pos + 8 + length)
            if zlib.crc32(body) & 0xFFFFFFFF != stored:
                bad_crc += 1
        chunks += 1
        if ctype == b"IEND":
            saw_iend = True
            break
        pos += 12 + length
    if not chunks:
        return Verdict.INVALID, ["no parseable chunks"]
    if bad_crc:
        return Verdict.SUSPECT, [f"{bad_crc} chunk CRC mismatch"]
    if saw_iend:
        reasons.append(f"{chunks} chunks, all CRC valid, ends at IEND")
        return Verdict.VALID, reasons
    return Verdict.PARTIAL, reasons + [f"{chunks} chunks, missing IEND"]


# --------------------------------------------------------------------------
# GIF
# --------------------------------------------------------------------------


def _gif_walk(src: ByteSource, off: int, limit: int) -> Extent | None:
    head = src.at(off, 13)
    if len(head) < 13:
        return None
    if head[:6] in (b"GIF87a", b"GIF89a"):
        packed = head[10]
        pos = off + 13
        if packed & 0x80:
            pos += 3 * (2 ** ((packed & 0x07) + 1))
    elif head[:11] == b"NETSCAPE2.0":
        pos = off + 16
    else:
        return None
    while pos < limit and pos < src.size:
        block = src.at(pos, 1)
        if not block:
            return None
        if block == b"\x3b":
            return Extent(pos + 1 - off, Verdict.VALID, ["ends at trailer"])
        if block == b"\x21":
            pos += 2
            while pos < src.size:
                n = _u8(src, pos)
                pos += 1 + n
                if n == 0:
                    break
            continue
        if block == b"\x2c":
            packed = _u8(src, pos + 9)
            pos += 10
            if packed & 0x80:
                pos += 3 * (2 ** ((packed & 0x07) + 1))
            pos += 1
            while pos < src.size:
                n = _u8(src, pos)
                pos += 1 + n
                if n == 0:
                    break
            continue
        return None
    return None


def _u8(src: ByteSource, off: int) -> int:
    b = src.at(off, 1)
    return b[0] if b else 0


# --------------------------------------------------------------------------
# RIFF containers: WAV, AVI, WebP
# --------------------------------------------------------------------------


def _riff_walk(src: ByteSource, off: int, limit: int) -> Extent | None:
    riff = src.at(off, 4)
    size = _u32le(src, off + 4)
    if size < 4 or size > 2 * 1024 * MIB:
        return None
    total = size + 8
    if off + total > src.size:
        return Extent(src.size - off, Verdict.PARTIAL, ["declared RIFF size exceeds data"], False)
    kind = riff
    return Extent(total, Verdict.VALID, [f"RIFF size field exact, form {kind.decode('ascii', 'replace')}"])


def _riff_validate(src: ByteSource, off: int, size: int) -> tuple[Verdict, list[str]]:
    declared = _u32le(src, off + 4) + 8
    if declared == size:
        return Verdict.VALID, ["RIFF size field matches recovered length"]
    if size < declared:
        return Verdict.PARTIAL, [f"RIFF wants {declared} bytes, recovered {size}"]
    return Verdict.SUSPECT, ["RIFF size field smaller than recovered length"]


# --------------------------------------------------------------------------
# ISO base media (MP4 / MOV / 3GP / HEIC)
# --------------------------------------------------------------------------


ISO_BRANDS: dict[str, tuple[bytes, ...]] = {
    "heic": (b"heic", b"heix", b"hevc", b"heim", b"heis", b"mif1", b"msf1", b"avif"),
    "mov": (b"qt  ",),
    "mp4": (b"isom", b"iso2", b"iso4", b"iso5", b"iso6", b"mp41", b"mp42",
            b"avc1", b"dash", b"M4V ", b"M4A ", b"M4B ", b"mmp4",
            b"3gp4", b"3gp5", b"3g2a", b"3g2b"),
}


def _iso_resolver(brands: tuple[bytes, ...]):
    """Match on the ftyp brand so a .heic is not reported as a .mp4."""

    def resolve(src: ByteSource, off: int, limit: int) -> Extent | None:
        if off < 0 or not _need(src, off, 12):
            return None
        start = off
        box_size = _u32be(src, start)
        if box_size < 12 or box_size > 4096:
            return None
        major = src.at(start + 8, 4)
        compat = src.at(start + 12, min(box_size - 16, 256))
        offered = (major,) + tuple(compat.split())
        if not any(b in brands for b in offered):
            return None
        extent = _isobmff_walk(src, start, limit)
        if extent is not None:
            extent.notes.insert(0, f"brand {major.decode('ascii', 'replace').strip()}")
        return extent

    return resolve


ISO_FINAL_BOXES = (b"mdat", b"moov", b"meta", b"mfra", b"free", b"skip", b"wide")
# Boxes that may sit at the top level of a file. Anything else ends the chain:
# it is the next file, or junk, never more of this one.
ISO_TOP_BOXES = frozenset((b"ftyp", b"moov", b"mdat", b"free", b"skip", b"wide", b"meta", b"mfra",
                           b"uuid", b"pdin", b"moof", b"sidx", b"styp", b"emsg", b"prft", b"ssix",
                           b"jumb", b"junk", b"pnot", b"PICT", b"Xtra", b"idat", b"iinf", b"iloc"))


def _isobmff_walk(src: ByteSource, off: int, limit: int) -> Extent | None:
    """Follow the top-level box chain; the file ends where the chain breaks."""
    pos = off
    boxes = 0
    last = b""
    while pos + 8 <= src.size:
        size = _u32be(src, pos)
        btype = src.at(pos + 4, 4)
        header = 8
        if btype not in ISO_TOP_BOXES or (btype == b"ftyp" and boxes):
            break
        if size == 1:
            if not _need(src, pos + 8, 8):
                break
            size = _u64be(src, pos + 8)
            header = 16
        elif size == 0:
            # "Runs to the end of the file": only a final mdat does that, and
            # the end is where the data stops, not where the drive stops.
            if btype != b"mdat" or boxes == 0:
                break
            end = _until_blank(src, pos + header, limit, 4 * 1024 * MIB)
            return Extent(end - off, Verdict.SUSPECT, ["open-ended mdat, sized to the data"], False)
        if size < header or pos + size > src.size:
            if boxes and btype == b"mdat":
                return Extent(src.size - off, Verdict.PARTIAL, ["mdat runs past the data"], False)
            break
        boxes += 1
        last = btype
        pos += size
    if boxes == 0:
        return None
    name = last.decode("ascii", "replace")
    if last in ISO_FINAL_BOXES:
        return Extent(pos - off, Verdict.VALID, [f"{boxes} top-level boxes, chain ends after {name}"])
    return Extent(pos - off, Verdict.SUSPECT, [f"{boxes} top-level boxes, ends after {name}"])


def _ftyp_quick(buf: bytes, i: int) -> bool:
    if not _have(buf, i, 12):
        return True
    size = int.from_bytes(buf[i:i + 4], "big")
    return 12 <= size <= 4096 and size % 4 == 0 and all(32 <= b < 127 for b in buf[i + 8:i + 12])


# --------------------------------------------------------------------------
# ZIP and its many disguises (docx/xlsx/pptx/odt/jar/apk)
# --------------------------------------------------------------------------


_ZIP_END = (b"PK\x05\x06", b"PK\x07\x08")


def _zip_by_eocd(src: ByteSource, off: int, limit: int) -> Extent | None:
    """Find the end record whose central directory sits exactly before it.

    Exact even for zips written with data descriptors (sizes after the data,
    so walking local headers cannot step over them), which is how browsers,
    Java and Office stream their zips.
    """
    end = min(limit, src.size, off + 64 * MIB)
    pos = off
    step = 4 * MIB
    while pos < end:
        window = src.at(pos, min(step + 22, end - pos))
        if len(window) < 22:
            return None
        idx = window.find(b"PK")
        while idx >= 0:
            at = pos + idx
            rec = src.at(at, 22)
            if len(rec) == 22:
                cd_size = int.from_bytes(rec[12:16], "little")
                cd_off = int.from_bytes(rec[16:20], "little")
                comment = int.from_bytes(rec[20:22], "little")
                entries = int.from_bytes(rec[10:12], "little")
                if off + cd_off + cd_size == at and src.at(off + cd_off, 4) == b"PK":
                    return Extent(at + 22 + comment - off, Verdict.VALID,
                                  [f"{entries} entries, central directory lines up with its end record"])
                if cd_off == 0xFFFFFFFF:          # zip64: trust the walk instead
                    return None
            idx = window.find(b"PK", idx + 1)
        pos += step
    return None


def _zip_name_ok(name: bytes, flags: int) -> bool:
    if flags & 0x800:                                # UTF-8 names
        try:
            text = name.decode("utf-8")
        except UnicodeDecodeError:
            return False
        return all(c.isprintable() for c in text)
    return _printable(name, 0.8)


_ZIP_RECORDS = (b"PK\x07\x08", b"PK\x03\x04", b"PK\x01\x02")
ZIP_ENTRY_MAX = 4096 * MIB


def _zip_next_record(src: ByteSource, data_off: int, end: int) -> int | None:
    """Offset of the record after an entry whose sizes are in a data descriptor."""
    pos = data_off
    stop = min(end, data_off + ZIP_ENTRY_MAX)
    step = 1 * MIB
    while pos < stop:
        window = src.at(pos, min(step + 3, stop - pos))
        if len(window) < 4:
            return None
        hits = [i for i in (window.find(sig) for sig in _ZIP_RECORDS) if i >= 0]
        if hits:
            at = pos + min(hits)
            if src.at(at, 4) == b"PK\x07\x08":
                comp = _u32le(src, at + 8)
                if comp == at - data_off:
                    return at + 16
                comp64 = _u64le(src, at + 8)
                if comp64 == at - data_off:
                    return at + 24
                pos = at + 1                         # a PK\x07\x08 inside the data
                continue
            return at
        pos += len(window) - 3
    return None


def _zip_walk(src: ByteSource, off: int, limit: int) -> Extent | None:
    """Walk local headers, then the central directory, to the EOCD."""
    pos = off
    entries = 0
    central = 0
    while pos + 4 <= src.size:
        sig = src.at(pos, 4)
        if sig == b"PK\x03\x04":
            if pos + 30 > src.size:
                break
            flags = _u16le(src, pos + 6)
            method = _u16le(src, pos + 8)
            comp = _u32le(src, pos + 18)
            nlen = _u16le(src, pos + 26)
            elen = _u16le(src, pos + 28)
            name = src.at(pos + 30, nlen)
            if nlen == 0 or not _zip_name_ok(name, flags):
                return None
            if method not in (0, 8, 9, 12, 14, 93, 95, 98):
                return None
            data_off = pos + 30 + nlen + elen
            if flags & 0x08 and comp in (0, 0xFFFFFFFF):
                # Sizes come after the data (a data descriptor): find where
                # the next record starts instead.
                nxt = _zip_next_record(src, data_off, min(limit, src.size))
                if nxt is None:
                    if entries == 0:
                        return None
                    return Extent(src.size - off, Verdict.PARTIAL, ["last entry truncated"], False)
                entries += 1
                pos = nxt
                continue
            if data_off + comp > src.size:
                if entries == 0:
                    return None
                return Extent(src.size - off, Verdict.PARTIAL, ["last entry truncated"], False)
            entries += 1
            pos = data_off + comp
            continue
        if sig == b"PK\x01\x02":
            if pos + 46 > src.size:
                break
            nlen = _u16le(src, pos + 28)
            elen = _u16le(src, pos + 30)
            clen = _u16le(src, pos + 32)
            step = 46 + nlen + elen + clen
            if step <= 0 or pos + step > src.size:
                break
            central += 1
            pos += step
            continue
        if sig == b"PK\x05\x05":
            step = 6 + _u32le(src, pos + 4)
            if step <= 0 or pos + step > src.size:
                break
            pos += step
            continue
        if sig == b"PK\x05\x06":
            if entries == 0:
                return None
            comment_len = _u16le(src, pos + 20)
            return Extent(pos + 22 + comment_len - off, Verdict.VALID,
                          [f"{entries} entries, {central} central records, ends at EOCD"])
        break
    if entries and central:
        return Extent(pos - off, Verdict.SUSPECT, ["no EOCD; stopped after central directory"])
    return None


def _zip_validate(src: ByteSource, off: int, size: int) -> tuple[Verdict, list[str]]:
    reasons: list[str] = []
    head = src.at(off, min(size, 4 * 1024 * 1024))
    lfh = head.find(b"PK\x03\x04")
    eocd = head.rfind(b"PK\x05\x06")
    if lfh < 0:
        return Verdict.SUSPECT, ["central directory only, no local header in range"]
    reasons.append(f"{head.count(b'PK' + bytes([3, 4]))} local headers")
    if eocd >= 0:
        reasons.append("EOCD present")
        return Verdict.VALID, reasons
    reasons.append("no end-of-central-directory in range")
    return Verdict.PARTIAL, reasons


# --------------------------------------------------------------------------
# PDF
# --------------------------------------------------------------------------


PDF_MAX = 512 * MIB
PDF_TAIL = 2 * MIB


def _pdf_walk(src: ByteSource, off: int, limit: int) -> Extent | None:
    header = src.at(off, 8)
    if not header.startswith(b"%PDF-"):
        return None
    version = header[5:8].decode("ascii", "replace")
    if not version[0].isdigit():
        return None
    # Read forward a step at a time. A PDF may carry several %%EOF (one per
    # incremental save); the last one before the next PDF starts, or before
    # a stretch with no further %%EOF, is the end.
    window = b""
    stop = min(limit, src.size, off + PDF_MAX)
    eof = -1
    pos = off
    while pos < stop:
        part = src.at(pos, min(1 * MIB, stop - pos))
        if not part:
            break
        window += part
        pos += len(part)
        nxt = window.find(b"%PDF-", 5)
        if nxt > 0:
            window = window[:nxt]
            eof = window.rfind(b"%%EOF")
            break
        last = window.rfind(b"%%EOF")
        if last >= 0 and len(window) - last > PDF_TAIL:
            eof = last
            break
        eof = last
    if eof < 0:
        return None
    end = off + eof + 5
    for eol in (b"\r\n", b"\n", b"\r"):
        if window[eof + 5:eof + 5 + len(eol)] == eol:
            end += len(eol)
            break
    reasons = [f"PDF {version}"]
    if b"startxref" in window:
        reasons.append("has xref table")
    else:
        reasons.append("xref-only-increment, may be linearized fragment")
    return Extent(end - off, Verdict.VALID if b"startxref" in window else Verdict.SUSPECT, reasons)


# --------------------------------------------------------------------------
# SQLite
# --------------------------------------------------------------------------


def _sqlite_walk(src: ByteSource, off: int, limit: int) -> Extent | None:
    header = src.at(off, 100)
    if not header.startswith(b"SQLite format 3\x00"):
        return None
    page_size = _u16be(src, off + 16)
    if page_size == 1:
        page_size = 65536
    if page_size < 512 or (page_size & (page_size - 1)) != 0:
        return None
    page_count = _u32be(src, off + 28)
    write_ver = _u8(src, off + 18)
    if page_count == 0:
        return None
    total = page_count * page_size
    if total > 64 * 1024 * MIB:
        return None
    if off + total > src.size:
        return Extent(src.size - off, Verdict.PARTIAL, [f"header wants {total} bytes"], False)
    return Extent(total, Verdict.VALID,
                  [f"page_size={page_size} page_count={page_count} write_ver={write_ver}"])


# --------------------------------------------------------------------------
# BMP, TIFF, ICO
# --------------------------------------------------------------------------


def _bmp_walk(src: ByteSource, off: int, limit: int) -> Extent | None:
    if src.at(off, 2) != b"BM":
        return None
    declared = _u32le(src, off + 2)
    width = struct.unpack("<i", src.at(off + 18, 4))[0]
    height = struct.unpack("<i", src.at(off + 22, 4))[0]
    bpp = _u16le(src, off + 28)
    compression = _u32le(src, off + 30)
    if declared < 14 or width <= 0 or abs(height) > 100000 or bpp not in (1, 4, 8, 16, 24, 32):
        return None
    if declared > 512 * MIB:
        return None
    if off + declared > src.size:
        return Extent(src.size - off, Verdict.PARTIAL, ["size field exceeds data"], False)
    return Extent(declared, Verdict.VALID,
                  [f"size field exact, {width}x{abs(height)} {bpp}bpp compression={compression}"])


def _tiff_walk(src: ByteSource, off: int, limit: int) -> Extent | None:
    bom = src.at(off, 4)
    if bom == b"II\x2a\x00":
        end = "<"
    elif bom == b"MM\x00\x2a":
        end = ">"
    else:
        return None
    ifd_off = struct.unpack(end + "I", src.at(off + 4, 4))[0]
    if ifd_off < 8 or ifd_off > 4 * MIB:
        return None
    count = struct.unpack(end + "H", src.at(off + ifd_off, 2))[0]
    if count == 0 or count > 4096:
        return None
    need = ifd_off + 2 + count * 12 + 4
    return Extent(min(need, limit - off), Verdict.SUSPECT, [f"{count} IFD entries, no reliable length"])


def _ico_entries_ok(head: bytes, count: int) -> bool:
    for k in range(count):
        e = head[6 + k * 16:22 + k * 16]
        planes = int.from_bytes(e[4:6], "little")
        bits = int.from_bytes(e[6:8], "little")
        size = int.from_bytes(e[8:12], "little")
        data_off = int.from_bytes(e[12:16], "little")
        if e[3] != 0 or planes > 1 or bits not in (0, 1, 4, 8, 16, 24, 32):
            return False
        if size < 40 or size > 4 * MIB or data_off < 6 + 16 * count:
            return False
    return True


def _ico_quick(buf: bytes, i: int) -> bool:
    if not _have(buf, i, 22):
        return True
    count = int.from_bytes(buf[i + 4:i + 6], "little")
    if not 1 <= count <= 64:
        return False
    if not _have(buf, i, 6 + count * 16):
        return True
    return _ico_entries_ok(buf[i:i + 6 + count * 16], count)


def _ico_walk(src: ByteSource, off: int, limit: int) -> Extent | None:
    head = src.at(off, 6)
    if len(head) < 6 or head[:4] != b"\x00\x00\x01\x00":
        return None
    count = _u16le(src, off + 4)
    if count == 0 or count > 64:
        return None
    head = src.at(off, 6 + count * 16)
    if len(head) < 6 + count * 16 or not _ico_entries_ok(head, count):
        return None
    end = off + 6 + count * 16
    for k in range(count):
        e = head[6 + k * 16:22 + k * 16]
        size = int.from_bytes(e[8:12], "little")
        data_off = int.from_bytes(e[12:16], "little")
        image = src.at(off + data_off, 8)
        # Every icon image is a PNG or a BITMAPINFOHEADER (its size, 40, first).
        if not (image == b"\x89PNG\r\n\x1a\n" or image[:4] == b"\x28\x00\x00\x00"):
            return None
        end = max(end, off + data_off + size)
    if end - off > 16 * MIB or end > min(limit, src.size):
        return None
    return Extent(end - off, Verdict.VALID, [f"{count} icon entries, image headers check out"])


def _bmp_quick(buf: bytes, i: int) -> bool:
    if not _have(buf, i, 30):
        return True
    if buf[i + 6:i + 10] != b"\x00\x00\x00\x00":
        return False
    pixels_at = int.from_bytes(buf[i + 10:i + 14], "little")
    dib = int.from_bytes(buf[i + 14:i + 18], "little")
    planes = int.from_bytes(buf[i + 26:i + 28], "little")
    bpp = int.from_bytes(buf[i + 28:i + 30], "little")
    return (dib in (12, 40, 52, 56, 64, 108, 124) and planes == 1 and bpp in (1, 4, 8, 16, 24, 32)
            and 14 + dib <= pixels_at < 64 * KIB)


def _tiff_quick(buf: bytes, i: int) -> bool:
    if not _have(buf, i, 8):
        return True
    order = "little" if buf[i] == 0x49 else "big"
    ifd = int.from_bytes(buf[i + 4:i + 8], order)
    if not 8 <= ifd <= 4 * MIB:
        return False
    if _have(buf, i + ifd, 2):
        return 0 < int.from_bytes(buf[i + ifd:i + ifd + 2], order) <= 512
    return True


# --------------------------------------------------------------------------
# Audio: MP3, FLAC, OGG
# --------------------------------------------------------------------------


_MP3_BITRATES = {
    (3, 3): (0, 32, 64, 96, 128, 160, 192, 224, 256, 288, 320, 352, 384, 416, 448),
    (3, 2): (0, 32, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320, 384),
    (3, 1): (0, 32, 40, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320),
    (2, 3): (0, 32, 48, 56, 64, 80, 96, 112, 128, 144, 160, 176, 192, 224, 256),
    (2, 2): (0, 8, 16, 24, 32, 40, 48, 56, 64, 80, 96, 112, 128, 144, 160),
    (2, 1): (0, 8, 16, 24, 32, 40, 48, 56, 64, 80, 96, 112, 128, 144, 160),
}
_MP3_RATES = {3: (44100, 48000, 32000), 2: (22050, 24000, 16000), 0: (11025, 12000, 8000)}
MP3_MIN_FRAMES = 6


def _mp3_frame_len(h: bytes) -> int:
    """Length of the MPEG audio frame whose 4-byte header is ``h``, or 0."""
    if len(h) < 4 or h[0] != 0xFF or (h[1] & 0xE0) != 0xE0:
        return 0
    version = (h[1] >> 3) & 3
    layer = (h[1] >> 1) & 3
    br_idx = h[2] >> 4
    sr_idx = (h[2] >> 2) & 3
    if version == 1 or layer == 0 or br_idx in (0, 15) or sr_idx == 3 or (h[3] & 3) == 2:
        return 0
    rate = _MP3_RATES[version][sr_idx]
    kbps = _MP3_BITRATES[(3 if version == 3 else 2, layer)][br_idx]
    pad = (h[2] >> 1) & 1
    if layer == 3:                                    # layer I
        return (12 * kbps * 1000 // rate + pad) * 4
    if layer == 1 and version != 3:                   # layer III, MPEG-2/2.5
        return 72 * kbps * 1000 // rate + pad
    return 144 * kbps * 1000 // rate + pad


def _mp3_quick(buf: bytes, i: int) -> bool:
    if buf[i:i + 3] == b"ID3":
        return _have(buf, i, 10) and buf[i + 3] in (2, 3, 4) and all(b < 0x80 for b in buf[i + 6:i + 10])
    n = _mp3_frame_len(buf[i:i + 4])
    if not n:
        return False
    nxt = buf[i + n:i + n + 4]
    return len(nxt) < 4 or _mp3_frame_len(nxt) > 0


def _mp3_walk(src: ByteSource, off: int, limit: int) -> Extent | None:
    """Step frame by frame; the file ends where the frames stop."""
    end = min(limit, src.size)
    pos = off
    tagged = False
    if src.at(off, 3) == b"ID3":
        size = 0
        for b in src.at(off + 6, 4):
            size = (size << 7) | (b & 0x7F)
        pos = off + 10 + size
        tagged = True
    frames = 0
    window_at, window = pos, src.at(pos, min(1 * MIB, max(0, end - pos)))
    while pos + 4 <= end:
        rel = pos - window_at
        if rel + 4 > len(window):
            window_at, window = pos, src.at(pos, min(1 * MIB, end - pos))
            rel = 0
            if len(window) < 4:
                break
        n = _mp3_frame_len(window[rel:rel + 4])
        if not n:
            break
        frames += 1
        pos += n
    if frames < (2 if tagged else MP3_MIN_FRAMES):
        return None
    pos = min(pos, end)
    if src.at(pos, 3) == b"TAG" and pos + 128 <= end:
        pos += 128
    verdict = Verdict.VALID if frames >= 30 else Verdict.SUSPECT
    return Extent(pos - off, verdict, [f"{frames} MPEG audio frames"])


def _flac_walk(src: ByteSource, off: int, limit: int) -> Extent | None:
    if src.at(off, 4) != b"fLaC":
        return None
    pos = off + 4
    while pos < src.size:
        header = _u8(src, pos)
        last = bool(header & 0x80)
        btype = header & 0x7F
        length = 0
        for i in range(4):
            length = (length << 8) | _u8(src, pos + 1 + i)
        pos += 5 + length
        if btype == 127:
            return None
        if last:
            end = _until_blank(src, pos, limit, 512 * MIB)
            return Extent(end - off, Verdict.SUSPECT, ["audio frames have no end marker; sized to the data"])
    return None


def _ogg_walk(src: ByteSource, off: int, limit: int) -> Extent | None:
    if src.at(off, 4) != b"OggS":
        return None
    pos = off
    pages = 0
    while pos + 27 <= src.size:
        if src.at(pos, 4) != b"OggS":
            break
        segs = _u8(src, pos + 26)
        if pos + 27 + segs > src.size:
            break
        body = sum(src.at(pos + 27 + i, 1)[0] for i in range(segs))
        pos += 27 + segs + body
        pages += 1
    if pages < 2:
        return None
    return Extent(pos - off, Verdict.VALID if pos == src.size else Verdict.SUSPECT, [f"{pages} Ogg pages"])


# --------------------------------------------------------------------------
# Archives: 7z, RAR, gzip, tar-ish
# --------------------------------------------------------------------------

_GZIP_MAGICS = (b"\x1f\x8b\x08",)
GZIP_PROBE = 64 * MIB


def _gzip_quick(buf: bytes, i: int) -> bool:
    if not _have(buf, i, 10):
        return True
    return buf[i + 3] & 0xE0 == 0 and buf[i + 8] in (0, 2, 4) and (buf[i + 9] <= 13 or buf[i + 9] == 255)


def _gzip_walk(src: ByteSource, off: int, limit: int) -> Extent | None:
    head = src.at(off, 10)
    if not head.startswith(_GZIP_MAGICS) or not _gzip_quick(head, 0):
        return None
    flg = _u8(src, off + 3)
    pos = off + 10
    if flg & 0x04:
        pos += 2 + _u16le(src, pos)
    for bit in (0x08, 0x10):
        if flg & bit:
            while pos < src.size and _u8(src, pos):
                pos += 1
            pos += 1
    if flg & 0x02:
        pos += 2
    if pos >= src.size:
        return None
    # Feed the stream a step at a time: most .gz files are small, and reading
    # a fixed 16 MB per hit made a folder of them crawl on a real drive.
    stop = min(src.size, limit, pos + GZIP_PROBE)
    decomp = zlib.decompressobj(-zlib.MAX_WBITS)
    fed = 0
    step = 64 * KIB
    try:
        while pos + fed < stop:
            chunk = src.at(pos + fed, min(step, stop - pos - fed))
            if not chunk:
                break
            decomp.decompress(chunk, 1 * MIB)
            fed += len(chunk)
            if decomp.eof:
                used = fed - len(decomp.unused_data)
                return Extent(pos + used + 8 - off, Verdict.VALID,
                              ["deflate stream ends cleanly, CRC and length trailer in range"])
            step = min(step * 2, 1 * MIB)
    except zlib.error:
        return None
    if fed < 64 * KIB:
        return None
    used = fed - len(decomp.unused_data)
    return Extent(max(pos + used - off, MIN_EXTENT), Verdict.PARTIAL,
                  ["deflate stream truncated"], False)


def _7z_walk(src: ByteSource, off: int, limit: int) -> Extent | None:
    if src.at(off, 6) != b"7z\xbc\xaf\x27\x1c":
        return None
    major, minor = _u8(src, off + 6), _u8(src, off + 7)
    next_off = _u64le(src, off + 12)
    next_size = _u64le(src, off + 20)
    if next_off == 0xFFFFFFFFFFFFFFFF:
        return None
    total = 32 + next_off + next_size
    if off + total > src.size:
        return Extent(src.size - off, Verdict.PARTIAL, ["next header truncated"], False)
    return Extent(total, Verdict.VALID, [f"7z {major}.{minor}, next header offset exact"])


def _rar_walk(src: ByteSource, off: int, limit: int) -> Extent | None:
    head = src.at(off, 8)
    if head.startswith(b"Rar!\x1a\x07\x00"):
        crc = src.at(off + 8, 8)
        if any(crc[:i] == b"\x00" * i for i in range(1, 8)):
            return None
        return None
    if head.startswith(b"Rar!\x1a\x07\x01\x00"):
        pos = off + 8
        while pos + 8 <= src.size:
            hlen = int.from_bytes(src.at(pos, 4), "little")
            if hlen == 0:
                return None
            body = src.at(pos + 8, hlen - 8)
            if not body:
                return None
            data_len = int.from_bytes(body[4:8], "little")
            pos += hlen + data_len
            if body[:4] == b"\xc4\x3d\x7b\x00":
                return Extent(pos - off, Verdict.VALID, ["ends at RAR5 end-of-archive"])
        return None
    return None


# --------------------------------------------------------------------------
# OLE2 compound files (legacy .doc/.xls/.ppt)
# --------------------------------------------------------------------------

_OLE_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"


def _ole_walk(src: ByteSource, off: int, limit: int) -> Extent | None:
    if src.at(off, 8) != _OLE_MAGIC:
        return None
    sector_power = _u16le(src, off + 30)
    mini_shift = _u16le(src, off + 32)
    num_fat = _u32le(src, off + 44)
    dir_start = _u32le(src, off + 48)
    if not 7 <= sector_power <= 20 or not 2 <= mini_shift <= 12:
        return None
    sector = 1 << sector_power
    if num_fat == 0 or dir_start >= 0xFFFFFFFA:
        return None
    per_sector = sector // 4
    fat_sectors = [int.from_bytes(src.at(off + 512 + s * sector, sector), "little")
                   for s in range(min(num_fat, per_sector))]
    if not fat_sectors or fat_sectors[0] >= 0xFFFFFFFA:
        return None
    seen: set[int] = set()
    highest = 0
    for fs in fat_sectors:
        chain = fs
        steps = 0
        while chain < 0xFFFFFFFA and chain not in seen and steps < num_fat + 8:
            seen.add(chain)
            highest = max(highest, chain)
            entry = src.at(off + 512 + chain * sector, 4)
            chain = int.from_bytes(entry, "little")
            steps += 1
    total = 512 + (highest + 1) * sector
    if off + total > src.size:
        return Extent(src.size - off, Verdict.PARTIAL, ["FAT chain exceeds data"], False)
    return Extent(total, Verdict.VALID,
                  [f"sector={sector}B mini_shift={mini_shift} FAT sectors followed={len(seen)}"])


# --------------------------------------------------------------------------
# ELF / PE
# --------------------------------------------------------------------------


def _elf_walk(src: ByteSource, off: int, limit: int) -> Extent | None:
    head = src.at(off, 64)
    if not head.startswith(b"\x7fELF"):
        return None
    is64 = head[4] == 2
    little = head[5] == 1
    end = "<" if little else ">"
    if is64:
        e_shoff = struct.unpack(end + "Q", head[40:48])[0]
        e_shentsize = struct.unpack(end + "H", head[58:60])[0]
        e_shnum = struct.unpack(end + "H", head[60:62])[0]
    else:
        e_shoff = struct.unpack(end + "I", head[32:36])[0]
        e_shentsize = struct.unpack(end + "H", head[46:48])[0]
        e_shnum = struct.unpack(end + "H", head[48:50])[0]
    if e_shoff and e_shnum and e_shentsize:
        total = e_shoff + e_shentsize * e_shnum
        if off + total <= src.size and total < 512 * MIB:
            return Extent(total, Verdict.VALID, ["length from section header table"])
    end = _until_blank(src, off, limit, 16 * MIB)
    return Extent(end - off, Verdict.SUSPECT, ["no section table; sized to the data"])


def _pe_quick(buf: bytes, i: int) -> bool:
    if not _have(buf, i, 0x40):
        return True
    pe_off = int.from_bytes(buf[i + 0x3C:i + 0x40], "little")
    if not 0x40 <= pe_off < 64 * KIB:
        return False
    return not _have(buf, i + pe_off, 4) or buf[i + pe_off:i + pe_off + 4] == b"PE\x00\x00"


def _pe_walk(src: ByteSource, off: int, limit: int) -> Extent | None:
    if src.at(off, 2) != b"MZ":
        return None
    pe_off = struct.unpack("<I", src.at(off + 0x3C, 4))[0]
    if not 0 < pe_off < 1 * MIB or src.at(off + pe_off, 4) != b"PE\x00\x00":
        return None
    coff = off + pe_off + 4
    sections = _u16le(src, coff + 2)
    opt_size = _u16le(src, coff + 16)
    if sections == 0 or sections > 96:
        return None
    opt = coff + 20
    magic = _u16le(src, opt)
    if magic not in (0x10B, 0x20B):
        return None
    end = _u32le(src, opt + 60)                       # SizeOfHeaders
    table = src.at(opt + opt_size, sections * 40)
    if len(table) < sections * 40:
        return None
    for k in range(sections):
        raw_size = int.from_bytes(table[k * 40 + 16:k * 40 + 20], "little")
        raw_ptr = int.from_bytes(table[k * 40 + 20:k * 40 + 24], "little")
        if raw_size:
            end = max(end, raw_ptr + raw_size)
    notes = [f"{sections} sections"]
    # A signed file carries its certificate after the last section.
    dirs_at = 96 if magic == 0x10B else 112
    if opt_size >= dirs_at + 5 * 8:
        cert_off, cert_size = _u32le(src, opt + dirs_at + 32), _u32le(src, opt + dirs_at + 36)
        if cert_off and cert_size and cert_off >= end and cert_off + cert_size < 1024 * MIB:
            end = cert_off + cert_size
            notes.append("signature included")
    if end <= 0 or end > 2048 * MIB:
        return None
    if off + end > src.size:
        return Extent(src.size - off, Verdict.PARTIAL, notes + ["data truncated"], False)
    return Extent(end, Verdict.VALID, notes + [f"ends at {end:#x}"])


# --------------------------------------------------------------------------
# Plain text formats: locate the next plausible restart
# --------------------------------------------------------------------------

_XML_HEADS = (b"<?xml", b"<svg", b"<html", b"<HTML", b"<!DOCTYPE", b"<?XML")


def _trailing_ws(window: bytes, end: int) -> int:
    """Index just past trailing whitespace, so real files keep their newline."""
    n = 0
    while end + n < len(window) and window[end + n] in b"\r\n\t ":
        n += 1
    return end + n


def _xml_walk(src: ByteSource, off: int, limit: int) -> Extent | None:
    head = src.at(off, 8)
    if not any(head.startswith(h) for h in _XML_HEADS):
        return None
    window = src.at(off, min(2 * MIB, src.size - off))
    close = window.rfind(b"</svg>")
    if close > 0:
        return Extent(_trailing_ws(window, close + 6), Verdict.VALID, ["ends at </svg>"])
    if b"</html>" in window:
        return Extent(window.rfind(b"</html>") + 7, Verdict.VALID, ["ends at </html>"])
    if b"?>" in window and b"\x00" in window:
        return None
    return None


FORMATS: tuple[Format, ...] = (
    Format("jpeg", "jpg", (b"\xff\xd8\xff",), 64 * MIB, b"\xff\xd9",
           _jpeg_walk, _jpeg_validate, "image", 0.9, quick=_jpeg_quick),
    Format("png", "png", (b"\x89PNG\r\n\x1a\n",), 64 * MIB, b"IEND",
           _png_walk, _png_validate, "image", 0.9),
    Format("gif", "gif", (b"GIF87a", b"GIF89a"), 32 * MIB, b"\x3b",
           _gif_walk, None, "image", 0.7),
    Format("bmp", "bmp", (b"BM",), 128 * MIB, None,
           _bmp_walk, None, "image", 0.75, quick=_bmp_quick),
    Format("ico", "ico", (b"\x00\x00\x01\x00",), 8 * MIB, None,
           _ico_walk, None, "image", 0.6, quick=_ico_quick),
    Format("tiff", "tif", (b"II\x2a\x00", b"MM\x00\x2a"), 128 * MIB, None,
           _tiff_walk, None, "image", 0.6, quick=_tiff_quick),
    Format("webp", "webp", (b"RIFF",), 64 * MIB, None,
           lambda s, o, l: _riff_walk(s, o, l) if s.at(o + 8, 4) == b"WEBP" else None,
           _riff_validate, "image", 0.85),
    Format("wav", "wav", (b"RIFF",), 512 * MIB, None,
           lambda s, o, l: _riff_walk(s, o, l) if s.at(o + 8, 4) == b"WAVE" else None,
           _riff_validate, "audio", 0.85),
    Format("avi", "avi", (b"RIFF",), 2 * 1024 * MIB, None,
           lambda s, o, l: _riff_walk(s, o, l) if s.at(o + 8, 4) == b"AVI " else None,
           _riff_validate, "video", 0.85),
    Format("mp4", "mp4", (b"ftyp",), 4 * 1024 * MIB, None,
           _iso_resolver(ISO_BRANDS["mp4"]), None, "video", 0.85, back=4, quick=_ftyp_quick),
    Format("mov", "mov", (b"ftyp",), 4 * 1024 * MIB, None,
           _iso_resolver(ISO_BRANDS["mov"]), None, "video", 0.8, back=4, quick=_ftyp_quick),
    Format("heic", "heic", (b"ftyp",), 512 * MIB, None,
           _iso_resolver(ISO_BRANDS["heic"]), None, "image", 0.85, back=4, quick=_ftyp_quick),
    Format("zip", "zip", (b"PK\x03\x04",), 2048 * MIB, b"PK\x05\x06",
           lambda s, o, l: _zip_walk(s, o, l) or _zip_by_eocd(s, o, l), _zip_validate, "archive", 0.85),
    Format("pdf", "pdf", (b"%PDF-",), 512 * MIB, b"%%EOF",
           _pdf_walk, None, "document", 0.8),
    Format("sqlite", "sqlite", (b"SQLite format 3\x00",), 4096 * MIB, None,
           _sqlite_walk, None, "database", 0.9),
    Format("gzip", "gz", _GZIP_MAGICS, 1024 * MIB, None,
           _gzip_walk, None, "archive", 0.7, quick=_gzip_quick),
    Format("7z", "7z", (b"7z\xbc\xaf\x27\x1c",), 1024 * MIB, None,
           _7z_walk, None, "archive", 0.85),
    Format("rar", "rar", (b"Rar!\x1a\x07",), 1024 * MIB, None,
           _rar_walk, None, "archive", 0.7),
    Format("ole2", "doc", (_OLE_MAGIC,), 1024 * MIB, None,
           _ole_walk, None, "document", 0.7),
    Format("elf", "elf", (b"\x7fELF",), 512 * MIB, None,
           _elf_walk, None, "executable", 0.7),
    Format("pe", "exe", (b"MZ",), 2048 * MIB, None,
           _pe_walk, None, "executable", 0.5, quick=_pe_quick),
    Format("flac", "flac", (b"fLaC",), 512 * MIB, None,
           _flac_walk, None, "audio", 0.75),
    Format("ogg", "ogg", (b"OggS",), 512 * MIB, None,
           _ogg_walk, None, "audio", 0.75),
    Format("svg", "svg", (b"<svg", b"<?xml"), 32 * MIB, None,
           _xml_walk, None, "image", 0.5),
    Format("mp3", "mp3", (b"ID3", b"\xff\xfb", b"\xff\xfa", b"\xff\xf3", b"\xff\xf2"), 64 * MIB,
           None, _mp3_walk, None, "audio", 0.55, quick=_mp3_quick),
)

BY_MAGIC: dict[bytes, list[Format]] = {}
for _fmt in FORMATS:
    for _magic in _fmt.magics:
        BY_MAGIC.setdefault(_magic, []).append(_fmt)

MAX_MAGIC = max(len(m) for m in BY_MAGIC)

EXT_FORMATS: dict[str, Format] = {}
for _fmt in FORMATS:
    EXT_FORMATS.setdefault(_fmt.ext, _fmt)

FOOTER_FORMATS = tuple(f for f in FORMATS if f.footer)
