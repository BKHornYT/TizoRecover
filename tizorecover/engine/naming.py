"""Names for files found by content, from what the files say about themselves.

A carved file has no name: the file table that held it is gone. But most files
carry their own description -- a photo's EXIF block knows when and with which
camera it was taken, an MP3's ID3 tag its artist and title, a video its
creation time, a PDF or Office document its title. That turns
``recovered_0000007a0_ok.jpg`` into ``Photo 2024-05-01 14.32.10 (Canon EOS R6).jpg``
and gives the file a date, so "newest first" means something for carved files.

Every reader here works on a ``read(offset, length) -> bytes`` function over the
carved file, reads little (the first 128 KB, a few box headers, or a small
Office file whole), and returns nothing rather than raising on a damaged file.
"""

from __future__ import annotations

import calendar
import io
import re
import struct
import zipfile
from typing import Callable

HEAD = 128 << 10
OFFICE_MAX = 16 << 20
MAX_NAME = 90
Reader = Callable[[int, int], bytes]

TIFF_RAW = {"cr2", "nef", "nrw", "arw", "srf", "sr2", "dng", "orf", "rw2", "pef", "srw", "tif", "tiff", "3fr", "erf", "kdc", "mos", "mrw"}
BMFF_VIDEO = {"mp4", "m4v", "mov", "3gp", "3g2"}
BMFF_AUDIO = {"m4a", "m4b", "aac"}
OFFICE = {"docx": "Document", "xlsx": "Spreadsheet", "pptx": "Presentation",
          "odt": "Document", "ods": "Spreadsheet", "odp": "Presentation"}


def _clean(text: str) -> str:
    text = re.sub(r'[\x00-\x1f\\/:*?"<>|]+', " ", text or "")
    text = re.sub(r"\s+", " ", text).strip(" .")
    return text[:MAX_NAME].rstrip(" .")


def _stamp(year, month, day, hour=0, minute=0, second=0) -> float | None:
    try:
        if not (1980 <= year <= 2100 and 1 <= month <= 12 and 1 <= day <= 31):
            return None
        return float(calendar.timegm((year, month, day, hour, minute, second, 0, 0, 0)))
    except (ValueError, OverflowError):
        return None


def _fmt(ts: float) -> str:
    import time
    return time.strftime("%Y-%m-%d %H.%M.%S", time.gmtime(ts))


# ------------------------------------------------------------------ EXIF / TIFF

def _tiff(buf: bytes, base: int) -> dict:
    """Make, Model and the original date from a TIFF structure starting at ``base``."""
    out: dict = {}
    if base + 8 > len(buf):
        return out
    order = buf[base:base + 2]
    if order == b"II":
        e = "<"
    elif order == b"MM":
        e = ">"
    else:
        return out

    def u16(o):
        return struct.unpack_from(e + "H", buf, base + o)[0]

    def u32(o):
        return struct.unpack_from(e + "I", buf, base + o)[0]

    def ifd(off, depth=0):
        if depth > 2 or off <= 0 or base + off + 2 > len(buf):
            return
        n = u16(off)
        if n > 400:
            return
        for k in range(n):
            ent = off + 2 + k * 12
            if base + ent + 12 > len(buf):
                return
            tag, typ, count = u16(ent), u16(ent + 2), u32(ent + 4)
            if typ == 2 and 0 < count < 256:          # ASCII
                voff = ent + 8 if count <= 4 else u32(ent + 8)
                raw = buf[base + voff:base + voff + count]
                text = raw.split(b"\x00", 1)[0].decode("latin-1", "replace").strip()
                if tag == 0x010F:
                    out["make"] = text
                elif tag == 0x0110:
                    out["model"] = text
                elif tag == 0x9003:
                    out["original"] = text
                elif tag == 0x0132:
                    out.setdefault("datetime", text)
            elif tag == 0x8769 and typ in (4, 13):    # Exif sub-IFD
                ifd(u32(ent + 8), depth + 1)

    try:
        if u16(2) not in (42, 0x4F52, 0x55):           # TIFF, ORF ("RO"), RW2 (0x55)
            return out
        ifd(u32(4))
    except struct.error:
        pass
    return out


def _exif_date(text: str) -> float | None:
    m = re.match(r"(\d{4}):(\d\d):(\d\d)[ T](\d\d):(\d\d):(\d\d)", text or "")
    return _stamp(*map(int, m.groups())) if m else None


def _camera(tags: dict) -> str:
    make, model = (tags.get("make") or "").strip(), (tags.get("model") or "").strip()
    if not model:
        return make
    first = make.split()[0].lower() if make else ""
    return model if not first or model.lower().startswith(first) else f"{make.split()[0].title()} {model}"


def _jpeg_exif(buf: bytes) -> dict:
    pos = 2
    while pos + 4 <= len(buf):
        if buf[pos] != 0xFF:
            return {}
        marker = buf[pos + 1]
        if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:
            pos += 2
            continue
        if marker == 0xDA:
            return {}
        length = struct.unpack_from(">H", buf, pos + 2)[0]
        if marker == 0xE1 and buf[pos + 4:pos + 10] == b"Exif\x00\x00":
            return _tiff(buf, pos + 10)
        pos += 2 + length
    return {}


def _photo(tags: dict) -> tuple[str | None, float | None]:
    ts = _exif_date(tags.get("original") or tags.get("datetime") or "")
    cam = _clean(_camera(tags))
    if ts is None:
        return None, None
    return (f"Photo {_fmt(ts)}" + (f" ({cam})" if cam else "")), ts


# ------------------------------------------------------------------ ISO BMFF (MP4 / MOV / M4A)

def _bmff(read: Reader, size: int, kind: str) -> tuple[str | None, float | None]:
    pos, steps = 0, 0
    while pos + 8 <= size and steps < 64:
        steps += 1
        head = read(pos, 16)
        if len(head) < 8:
            break
        box_size, box = struct.unpack_from(">I4s", head)
        if box_size == 1 and len(head) >= 16:
            box_size = struct.unpack_from(">Q", head, 8)[0]
        elif box_size == 0:
            box_size = size - pos
        if box_size < 8:
            break
        if box == b"moov":
            moov = read(pos, min(box_size, 4 << 20))
            i = moov.find(b"mvhd")
            if i < 4:
                break
            ver = moov[i + 4] if i + 5 <= len(moov) else 0
            try:
                created = struct.unpack_from(">Q", moov, i + 8)[0] if ver == 1 else struct.unpack_from(">I", moov, i + 8)[0]
            except struct.error:
                break
            title = None
            j = moov.find(b"\xa9nam")
            if j > 0 and moov[j + 8:j + 12] == b"data":
                n = struct.unpack_from(">I", moov, j + 4)[0]
                title = _clean(moov[j + 20:j + 4 + n].decode("utf-8", "replace"))
            ts = created - 2082844800 if created > 2082844800 else None
            if ts is not None and not (315532800 <= ts <= 4102444800):
                ts = None
            if title:
                return title, ts
            if ts is None:
                return None, None
            return f"{kind} {_fmt(ts)}", ts
        pos += box_size
    return None, None


# ------------------------------------------------------------------ ID3

def _id3_text(frame: bytes) -> str:
    if not frame:
        return ""
    enc, body = frame[0], frame[1:]
    try:
        if enc == 0:
            text = body.decode("latin-1")
        elif enc == 1:
            text = body.decode("utf-16")
        elif enc == 2:
            text = body.decode("utf-16-be")
        else:
            text = body.decode("utf-8")
    except UnicodeDecodeError:
        return ""
    return text.split("\x00")[0].strip()


def _mp3(buf: bytes) -> tuple[str | None, float | None]:
    if buf[:3] != b"ID3" or len(buf) < 10:
        return None, None
    ver = buf[3]
    end = 10 + ((buf[6] & 0x7F) << 21 | (buf[7] & 0x7F) << 14 | (buf[8] & 0x7F) << 7 | (buf[9] & 0x7F))
    pos, tags = 10, {}
    while pos + 10 <= min(end, len(buf)):
        fid = buf[pos:pos + 4]
        if not fid.strip(b"\x00"):
            break
        raw = buf[pos + 4:pos + 8]
        n = (raw[0] << 21 | raw[1] << 14 | raw[2] << 7 | raw[3]) if ver == 4 else struct.unpack(">I", raw)[0]
        if n <= 0 or n > 1 << 20:
            break
        if fid in (b"TIT2", b"TPE1", b"TALB"):
            tags[fid] = _clean(_id3_text(buf[pos + 10:pos + 10 + n]))
        pos += 10 + n
    title, artist = tags.get(b"TIT2"), tags.get(b"TPE1")
    if title and artist:
        return f"{artist} - {title}", None
    return (title or None), None


# ------------------------------------------------------------------ PDF / Office

def _pdf_string(raw: bytes) -> str:
    raw = raw.strip()
    if raw.startswith(b"<") and raw.endswith(b">"):
        try:
            data = bytes.fromhex(raw[1:-1].decode("ascii"))
        except ValueError:
            return ""
        return data[2:].decode("utf-16-be", "replace") if data[:2] == b"\xfe\xff" else data.decode("latin-1")
    if raw.startswith(b"(") and raw.endswith(b")"):
        data = re.sub(rb"\\(.)", rb"\1", raw[1:-1])
        return data[2:].decode("utf-16-be", "replace") if data[:2] == b"\xfe\xff" else data.decode("latin-1", "replace")
    return ""


def _pdf(read: Reader, size: int) -> tuple[str | None, float | None]:
    head = read(0, min(size, HEAD))
    tail = read(max(0, size - (64 << 10)), min(size, 64 << 10)) if size > HEAD else b""
    title, ts = "", None
    for blob in (tail, head):
        m = re.search(rb"<dc:title>.*?<rdf:li[^>]*>([^<]{1,300})</rdf:li>", blob, re.S)
        if m and not title:
            title = m.group(1).decode("utf-8", "replace")
        m = re.search(rb"/Title\s*(\((?:\\.|[^\\)]){1,400}\)|<[0-9A-Fa-f\s]{2,800}>)", blob)
        if m and not title:
            title = _pdf_string(m.group(1))
        m = re.search(rb"/CreationDate\s*\(D:(\d{4})(\d\d)(\d\d)(\d\d)?(\d\d)?(\d\d)?", blob)
        if m and ts is None:
            ts = _stamp(*[int(g) if g else 0 for g in m.groups()])
    title = _clean(title)
    if title.lower() in ("untitled", "microsoft word - document1", "") or len(title) < 3:
        return None, ts
    return re.sub(r"^Microsoft (Word|PowerPoint|Excel) - ", "", title), ts


def _office(read: Reader, size: int, ext: str) -> tuple[str | None, float | None]:
    if size > OFFICE_MAX:
        return None, None
    try:
        z = zipfile.ZipFile(io.BytesIO(read(0, size)))
        name = "docProps/core.xml" if ext in ("docx", "xlsx", "pptx") else "meta.xml"
        xml = z.read(name).decode("utf-8", "replace")
    except (zipfile.BadZipFile, KeyError, OSError, ValueError, EOFError, RuntimeError, NotImplementedError):
        return None, None
    m = re.search(r"<dc:title>([^<]{1,300})</dc:title>", xml)
    title = _clean(m.group(1)) if m else ""
    m = re.search(r"<(?:dcterms:modified|dc:date)[^>]*>(\d{4})-(\d\d)-(\d\d)T(\d\d):(\d\d):(\d\d)", xml)
    ts = _stamp(*map(int, m.groups())) if m else None
    if title:
        return title, ts
    if ts is not None:
        return f"{OFFICE.get(ext, 'Document')} {_fmt(ts)}", ts
    return None, None


# ------------------------------------------------------------------ entry point

def describe(read: Reader, size: int, ext: str) -> tuple[str | None, float | None]:
    """(name without extension, modified time) for a carved file, or (None, None)."""
    ext = (ext or "").lower()
    try:
        if ext in ("jpg", "jpeg"):
            return _photo(_jpeg_exif(read(0, min(size, HEAD))))
        if ext in TIFF_RAW:
            return _photo(_tiff(read(0, min(size, HEAD)), 0))
        if ext in BMFF_VIDEO:
            return _bmff(read, size, "Video")
        if ext in BMFF_AUDIO:
            return _bmff(read, size, "Recording")
        if ext == "mp3":
            return _mp3(read(0, min(size, HEAD)))
        if ext == "pdf":
            return _pdf(read, size)
        if ext in OFFICE:
            return _office(read, size, ext)
    except (OSError, ValueError, struct.error, IndexError, UnicodeDecodeError):
        return None, None
    return None, None
