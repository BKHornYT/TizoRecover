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


# --------------------------------------------------------------------------
# JPEG
# --------------------------------------------------------------------------


def _jpeg_walk(src: ByteSource, off: int, limit: int) -> Extent | None:
    """Walk JPEG segments to the start of scan, then to the EOI marker."""
    end = min(limit, src.size)
    pos = off + 2
    reached_scan = False
    while pos + 1 < end:
        if src.at(pos, 1) != b"\xff":
            pos += 1
            continue
        while src.at(pos, 1) == b"\xff":
            pos += 1
        marker = src.at(pos, 1)
        if not marker:
            return None
        pos += 1
        code = marker[0]
        if code == 0xD9:
            return Extent(pos - off, Verdict.VALID, ["ends at EOI"])
        if code == 0x01 or 0xD0 <= code <= 0xD7:
            continue
        seg_len = _u16be(src, pos)
        if seg_len < 2 or pos + seg_len > src.size:
            return None
        pos += seg_len
        if code == 0xDA:
            reached_scan = True
            break
    if not reached_scan:
        return None
    window = src.at(pos, min(8 * MIB, src.size - pos))
    idx = window.find(b"\xff\xd9")
    if idx == -1:
        tail = min(src.size, pos + 8 * MIB)
        return Extent(tail - off, Verdict.PARTIAL, ["entropy data truncated"], False)
    return Extent(pos + idx + 2 - off, Verdict.VALID, ["ends at EOI after scan data"])


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


def _isobmff_walk(src: ByteSource, off: int, limit: int) -> Extent | None:
    """Follow the top-level box chain; the file ends where the chain breaks."""
    pos = off
    boxes = 0
    last = b""
    while pos + 8 <= src.size:
        size = _u32be(src, pos)
        btype = src.at(pos + 4, 4)
        header = 8
        if size == 1:
            if not _need(src, pos + 8, 8):
                break
            size = _u64be(src, pos + 8)
            header = 16
        elif size == 0:
            if boxes == 0:
                return None
            return Extent(src.size - off, Verdict.SUSPECT, ["open-ended final box"], False)
        if not _printable(btype, 0.9):
            break
        if size < header or pos + size > src.size:
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


# --------------------------------------------------------------------------
# ZIP and its many disguises (docx/xlsx/pptx/odt/jar/apk)
# --------------------------------------------------------------------------


_ZIP_END = (b"PK\x05\x06", b"PK\x07\x08")


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
            method = _u16le(src, pos + 8)
            comp = _u32le(src, pos + 18)
            nlen = _u16le(src, pos + 26)
            elen = _u16le(src, pos + 28)
            name = src.at(pos + 30, nlen)
            if nlen == 0 or not _printable(name, 0.8):
                return None
            if method not in (0, 8, 9, 12, 14, 93, 95, 98):
                return None
            data_off = pos + 30 + nlen + elen
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


def _pdf_walk(src: ByteSource, off: int, limit: int) -> Extent | None:
    header = src.at(off, 8)
    if not header.startswith(b"%PDF-"):
        return None
    version = header[5:8].decode("ascii", "replace")
    if not version[0].isdigit():
        return None
    window = src.at(off, min(limit - off, 8 * MIB))
    eof = window.rfind(b"%%EOF")
    if eof < 0:
        return None
    end = off + eof + 5
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


def _ico_walk(src: ByteSource, off: int, limit: int) -> Extent | None:
    head = src.at(off, 6)
    if len(head) < 6 or head[:4] != b"\x00\x00\x01\x00":
        return None
    count = _u16le(src, off + 4)
    if count == 0 or count > 64 or not _need(src, off + 6, count * 16):
        return None
    end = off + 6 + count * 16
    for i in range(count):
        base = off + 6 + i * 16
        planes = _u16le(src, base + 4)
        bits = _u16le(src, base + 6)
        if planes not in (0, 1) or bits not in (1, 4, 8, 16, 24, 32):
            return None
        size = _u32le(src, base + 8)
        data_off = _u32le(src, base + 12)
        if data_off and size and data_off + size <= src.size:
            end = max(end, off + data_off + size)
    if end - off > 16 * MIB:
        return None
    return Extent(end - off, Verdict.VALID, [f"{count} icon entries"])


# --------------------------------------------------------------------------
# Audio: MP3, FLAC, OGG
# --------------------------------------------------------------------------


def _mp3_walk(src: ByteSource, off: int, limit: int) -> Extent | None:
    head = src.at(off, 3)
    pos = off
    if head[:3] == b"ID3":
        size = 0
        for b in src.at(off + 6, 4):
            size = (size << 7) | (b & 0x7F)
        pos = off + 10 + size
        if src.at(pos, 1) != b"\xff":
            return None
    head = src.at(pos, 4)
    if len(head) < 2 or head[0] != 0xFF or (head[1] & 0xE0) != 0xE0:
        return None
    window = src.at(pos, min(2 * MIB, src.size - pos))
    tail = src.rfind(b"TAG")
    end = pos + len(window) - 1
    if tail > 0x32:
        end = pos + tail
    if window.rfind(b"\xff\xfb") > 0x1000 and window.rfind(b"\xff\xfb") < end - pos:
        end = pos + window.rfind(b"\xff\xfb")
    return Extent(max(end - off, 4096), Verdict.SUSPECT,
                  ["no reliable MP3 end marker; sized to next frame or ID3v1"])


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
            return Extent(src.size - off, Verdict.SUSPECT, ["audio frames have no end marker"])
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


def _gzip_walk(src: ByteSource, off: int, limit: int) -> Extent | None:
    if not src.at(off, 3).startswith(_GZIP_MAGICS):
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
    probe_len = min(16 * MIB, src.size - pos)
    probe = src.at(pos, probe_len)
    decomp = zlib.decompressobj(-zlib.MAX_WBITS)
    fed = 0
    try:
        while fed < len(probe):
            chunk = probe[fed:fed + 128 * KIB]
            if not chunk:
                break
            decomp.decompress(chunk)
            fed += len(chunk)
            if decomp.eof:
                used = fed - len(decomp.unused_data)
                return Extent(pos + used + 8 - off, Verdict.VALID,
                              ["deflate stream ends cleanly, CRC and length trailer in range"])
    except zlib.error:
        pass
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
    return Extent(min(limit - off, 16 * MIB), Verdict.SUSPECT, ["no section table; using max size"])


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
    sec_table = coff + 20 + opt_size
    end = src.size - off
    for i in range(sections):
        base = sec_table + i * 40
        raw_ptr = _u32le(src, base + 20)
        raw_size = _u32le(src, base + 16)
        end = max(end, raw_ptr + raw_size)
    if off + end > src.size:
        return Extent(src.size - off, Verdict.PARTIAL, [f"{sections} sections, data truncated"], False)
    return Extent(end, Verdict.VALID, [f"{sections} sections, last section ends at {end:#x}"])


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
           _jpeg_walk, _jpeg_validate, "image", 0.9),
    Format("png", "png", (b"\x89PNG\r\n\x1a\n",), 64 * MIB, b"IEND",
           _png_walk, _png_validate, "image", 0.9),
    Format("gif", "gif", (b"GIF87a", b"GIF89a"), 32 * MIB, b"\x3b",
           _gif_walk, None, "image", 0.7),
    Format("bmp", "bmp", (b"BM",), 128 * MIB, None,
           _bmp_walk, None, "image", 0.75),
    Format("ico", "ico", (b"\x00\x00\x01\x00",), 8 * MIB, None,
           _ico_walk, None, "image", 0.6),
    Format("tiff", "tif", (b"II\x2a\x00", b"MM\x00\x2a"), 128 * MIB, None,
           _tiff_walk, None, "image", 0.6),
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
           _iso_resolver(ISO_BRANDS["mp4"]), None, "video", 0.85, back=4),
    Format("mov", "mov", (b"ftyp",), 4 * 1024 * MIB, None,
           _iso_resolver(ISO_BRANDS["mov"]), None, "video", 0.8, back=4),
    Format("heic", "heic", (b"ftyp",), 512 * MIB, None,
           _iso_resolver(ISO_BRANDS["heic"]), None, "image", 0.85, back=4),
    Format("zip", "zip", (b"PK\x03\x04",), 2048 * MIB, b"PK\x05\x06",
           _zip_walk, _zip_validate, "archive", 0.85),
    Format("pdf", "pdf", (b"%PDF-",), 512 * MIB, b"%%EOF",
           _pdf_walk, None, "document", 0.8),
    Format("sqlite", "sqlite", (b"SQLite format 3\x00",), 4096 * MIB, None,
           _sqlite_walk, None, "database", 0.9),
    Format("gzip", "gz", _GZIP_MAGICS, 1024 * MIB, None,
           _gzip_walk, None, "archive", 0.7),
    Format("7z", "7z", (b"7z\xbc\xaf\x27\x1c",), 1024 * MIB, None,
           _7z_walk, None, "archive", 0.85),
    Format("rar", "rar", (b"Rar!\x1a\x07",), 1024 * MIB, None,
           _rar_walk, None, "archive", 0.7),
    Format("ole2", "doc", (_OLE_MAGIC,), 1024 * MIB, None,
           _ole_walk, None, "document", 0.7),
    Format("elf", "elf", (b"\x7fELF",), 512 * MIB, None,
           _elf_walk, None, "executable", 0.7),
    Format("pe", "exe", (b"MZ",), 2048 * MIB, None,
           _pe_walk, None, "executable", 0.5),
    Format("flac", "flac", (b"fLaC",), 512 * MIB, None,
           _flac_walk, None, "audio", 0.75),
    Format("ogg", "ogg", (b"OggS",), 512 * MIB, None,
           _ogg_walk, None, "audio", 0.75),
    Format("svg", "svg", (b"<svg", b"<?xml"), 32 * MIB, None,
           _xml_walk, None, "image", 0.5),
    Format("mp3", "mp3", (b"ID3", b"\xff\xfb", b"\xff\xf3", b"\xff\xf2"), 64 * MIB, None,
           _mp3_walk, None, "audio", 0.55),
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
