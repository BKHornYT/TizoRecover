"""More file types for the content search (0.7.0, after PhotoRec's list).

Each one is a type whose files say where they end -- a length field, a chain
of sized blocks, or a compressed stream that knows its own end -- so the
carved file comes back exactly, not "up to the next zeros". Owner asked for
.ts (already in formats.py) and .m1v; the rest are PhotoRec types that people
actually lose: CCTV recordings (.dav), phone voice memos (.amr), MPEG video
from old cameras and DVDs (.mpg/.vob/.m1v/.m2v), and so on.
"""

from __future__ import annotations

import bz2
import lzma
import zlib

from tizorecover.engine.formats_base import MIB, Extent, Format, _until_blank
from tizorecover.engine.results import Verdict

VALID, SUSPECT, PARTIAL = Verdict.VALID, Verdict.SUSPECT, Verdict.PARTIAL


def _end(src, limit: int, off: int, cap: int) -> int:
    return min(limit, src.size, off + cap)


# --------------------------------------------------------------- MPEG-1/2 program stream (.mpg, .vob)

def _mpeg_ps_walk(src, off: int, limit: int) -> Extent | None:
    end = _end(src, limit, off, 8192 * MIB)
    pos, packs, private, mpeg2, ended = off, 0, False, False, False
    while pos + 4 <= end:
        h = src.at(pos, 14)
        if len(h) < 4 or h[:3] != b"\x00\x00\x01":
            break
        sid = h[3]
        if sid == 0xBA:
            if len(h) < 14:
                break
            if h[4] & 0xC0 == 0x40:
                mpeg2, ln = True, 14 + (h[13] & 7)
            elif h[4] & 0xF0 == 0x20:
                ln = 12
            else:
                break
            packs += 1
            pos += ln
        elif sid == 0xB9:
            pos += 4
            ended = True
            break
        elif sid >= 0xBB:
            if len(h) < 6:
                break
            private = private or sid == 0xBD
            pos += 6 + int.from_bytes(h[4:6], "big")
        else:
            break
    if packs < 2:
        return None
    return Extent(min(pos, end) - off, VALID if packs >= 20 or ended else SUSPECT,
                  [f"{packs} MPEG packs" + (", program end code" if ended else "")],
                  ext="vob" if mpeg2 and private else "mpg")


def _mpeg_ps_quick(buf: bytes, i: int) -> bool:
    if i + 5 > len(buf):
        return True
    b = buf[i + 4]
    return (b & 0xC0) == 0x40 or (b & 0xF0) == 0x20


# --------------------------------------------------------------- MPEG-1/2 video elementary stream (.m1v, .m2v)

_ES_OK = set(range(0x00, 0xB0)) | {0xB2, 0xB3, 0xB5, 0xB7, 0xB8}


def _mpeg_es_quick(buf: bytes, i: int) -> bool:
    if i + 8 > len(buf):
        return True
    w = (buf[i + 4] << 4) | (buf[i + 5] >> 4)
    h = ((buf[i + 5] & 0x0F) << 8) | buf[i + 6]
    return 16 <= w <= 4096 and 16 <= h <= 4096 and 1 <= (buf[i + 7] & 0x0F) <= 8 and (buf[i + 7] >> 4) != 0


def _mpeg_es_walk(src, off: int, limit: int) -> Extent | None:
    end = _end(src, limit, off, 4096 * MIB)
    pos, last, pictures, mpeg2, closed = off, off, 0, False, False
    step = 1 * MIB
    while pos < end and not closed:
        window = src.at(pos, min(step + 3, end - pos))
        if len(window) < 4:
            break
        k = window.find(b"\x00\x00\x01", 1 if pos == off else 0)
        if k < 0:
            if pos + len(window) - last > 2 * MIB:     # no start code for 2 MB: the stream is over
                break
            pos += len(window) - 3
            continue
        while k >= 0 and k + 3 < len(window):
            code = window[k + 3]
            at = pos + k
            if code not in _ES_OK:
                closed = True
                end = at
                break
            if code == 0x00:
                pictures += 1
            elif code == 0xB5 and k + 4 < len(window) and window[k + 4] >> 4 == 1:
                mpeg2 = True
            elif code == 0xB7:
                closed = True
                end = at + 4
                break
            last = at
            k = window.find(b"\x00\x00\x01", k + 3)
        if not closed:
            pos += max(1, len(window) - 3)
        if pictures == 0 and pos - off > 64 * 1024:
            return None                               # a header with no pictures after it: not a video
    if pictures == 0:
        return None
    stop = end if closed else _until_blank(src, last, limit, 64 * MIB)
    return Extent(stop - off, VALID if closed or pictures >= 10 else SUSPECT,
                  [f"{pictures} pictures" + (", sequence end code" if closed and src.at(stop - 4, 4) == b"\x00\x00\x01\xb7" else "")],
                  ext="m2v" if mpeg2 else "m1v")


# --------------------------------------------------------------- Dahua/Amcrest CCTV recordings (.dav)

def _dav_walk(src, off: int, limit: int) -> Extent | None:
    end = _end(src, limit, off, 16384 * MIB)
    pos, frames = off, 0
    while pos + 24 <= end:
        h = src.at(pos, 16)
        if h[:4] != b"DHAV":
            break
        size = int.from_bytes(h[12:16], "little")
        if size < 32 or pos + size > end or src.at(pos + size - 8, 4) != b"dhav":
            break
        frames += 1
        pos += size
    if frames < 2:
        return None
    return Extent(pos - off, VALID if frames >= 10 else SUSPECT, [f"{frames} DHAV frames"], ext="dav")


# --------------------------------------------------------------- RealMedia (.rm, .rmvb)

_RM_CHUNKS = {b".RMF", b"PROP", b"MDPR", b"CONT", b"DATA", b"INDX", b"RMMD", b"RJMD", b"RMJE"}


def _rm_walk(src, off: int, limit: int) -> Extent | None:
    end = _end(src, limit, off, 8192 * MIB)
    pos, chunks, data, rv40 = off, 0, False, False
    while pos + 10 <= end:
        h = src.at(pos, 8)
        cid, size = h[:4], int.from_bytes(h[4:8], "big")
        if cid not in _RM_CHUNKS or size < 8 or pos + size > end:
            break
        if cid == b"MDPR" and b"RV40" in src.at(pos, min(size, 512)):
            rv40 = True
        data = data or cid == b"DATA"
        chunks += 1
        pos += size
    if chunks < 3 or not data:
        return None
    return Extent(pos - off, VALID, [f"{chunks} RealMedia chunks"], ext="rmvb" if rv40 else "rm")


# --------------------------------------------------------------- Flash (.swf)

def _swf_quick(buf: bytes, i: int) -> bool:
    if i + 10 > len(buf):
        return True
    if not 1 <= buf[i + 3] <= 50:
        return False
    total = int.from_bytes(buf[i + 4:i + 8], "little")
    if not 21 <= total <= 512 * MIB:
        return False
    if buf[i] == 0x43:                                   # CWS: a zlib header must follow
        cmf, flg = buf[i + 8], buf[i + 9]
        return cmf & 0x0F == 8 and (cmf * 256 + flg) % 31 == 0
    return True


def _ape_quick(buf: bytes, i: int) -> bool:
    return i + 12 > len(buf) or (3980 <= int.from_bytes(buf[i + 4:i + 6], "little") <= 4100
                                 and 52 <= int.from_bytes(buf[i + 8:i + 12], "little") <= 1024)


def _au_quick(buf: bytes, i: int) -> bool:
    return i + 16 > len(buf) or (24 <= int.from_bytes(buf[i + 4:i + 8], "big") <= 4096
                                 and 1 <= int.from_bytes(buf[i + 12:i + 16], "big") <= 27)


def _swf_walk(src, off: int, limit: int) -> Extent | None:
    h = src.at(off, 8)
    if len(h) < 8 or not 1 <= h[3] <= 50:
        return None
    total = int.from_bytes(h[4:8], "little")
    if h[:3] == b"FWS":
        if not 21 <= total <= 512 * MIB or off + total > min(limit, src.size):
            return None
        return Extent(total, VALID, ["uncompressed SWF, length from its header"], ext="swf")
    d = zlib.decompressobj()
    pos, end, out = off + 8, min(limit, src.size, off + 256 * MIB), 0
    step = 4096                                          # small first: random data fails in the first block
    while pos < end and not d.eof:
        chunk = src.at(pos, min(step, end - pos))
        step = min(step * 4, 256 * 1024)
        try:
            out += len(d.decompress(chunk, max(0, total - out + 1024)))
        except zlib.error:
            return None
        pos += len(chunk) - len(d.unconsumed_tail) - len(d.unused_data)
        if d.unconsumed_tail:
            continue
    if not d.eof:
        return None
    return Extent(pos - off, VALID if out + 8 == total else PARTIAL, ["zlib-compressed SWF, ends where its stream ends"],
                  ext="swf")


# --------------------------------------------------------------- MXF (broadcast cameras)

def _mxf_walk(src, off: int, limit: int) -> Extent | None:
    end = _end(src, limit, off, 32768 * MIB)
    pos, klvs = off, 0
    while pos + 17 <= end:
        h = src.at(pos, 25)
        if h[:4] != b"\x06\x0e\x2b\x34":
            break
        b = h[16]
        if b < 0x80:
            length, hl = b, 17
        else:
            n = b & 0x7F
            if not 1 <= n <= 8 or len(h) < 17 + n:
                break
            length, hl = int.from_bytes(h[17:17 + n], "big"), 17 + n
        if pos + hl + length > end:
            break
        klvs += 1
        pos += hl + length
    if klvs < 3:
        return None
    return Extent(pos - off, VALID if klvs >= 10 else SUSPECT, [f"{klvs} KLV packets"], ext="mxf")


# --------------------------------------------------------------- AMR voice memos (.amr)

_AMR_NB = [13, 14, 16, 18, 20, 21, 27, 32, 6, 0, 0, 0, 0, 0, 0, 1]
_AMR_WB = [18, 24, 33, 37, 41, 47, 51, 59, 61, 6, 0, 0, 0, 0, 1, 1]


def _amr_walk(src, off: int, limit: int) -> Extent | None:
    head = src.at(off, 9)
    if head.startswith(b"#!AMR-WB\n"):
        sizes, pos = _AMR_WB, off + 9
    elif head.startswith(b"#!AMR\n"):
        sizes, pos = _AMR_NB, off + 6
    else:
        return None
    end = _end(src, limit, off, 256 * MIB)
    frames, last_mode = 0, -1
    while pos < end:
        window = src.at(pos, min(64 * 1024, end - pos))
        if not window:
            break
        k = 0
        while k < len(window):
            b = window[k]
            size = sizes[(b >> 3) & 0x0F]
            if b & 0x83 or size == 0 or k + size > len(window):
                break
            if b == 0 and not any(window[k:k + size]):    # an all-zero "frame" is blank space, not audio
                k = -k - 1
                break
            mode = (b >> 3) & 0x0F
            if frames and mode != last_mode and k + size < len(window):
                nb = window[k + size]                     # a new bit-rate must be followed by another frame
                if nb & 0x83 or sizes[(nb >> 3) & 0x0F] == 0:
                    k = -k - 1
                    break
            last_mode = mode
            frames += 1
            k += size
        if k < 0:                                     # hit blank space: the file ended here
            pos += -k - 1
            break
        pos += k
        if k == 0 or (k < len(window) and window[k] & 0x83) or (k < len(window) and sizes[(window[k] >> 3) & 0x0F] == 0):
            break
        if pos + 32 > end and k < len(window):
            break
    if frames < 10:
        return None
    return Extent(pos - off, VALID if frames >= 50 else SUSPECT, [f"{frames} AMR frames"], ext="amr")


# --------------------------------------------------------------- Monkey's Audio (.ape), Sun audio (.au), Apple CAF

def _ape_walk(src, off: int, limit: int) -> Extent | None:
    h = src.at(off, 52)
    if len(h) < 52 or h[:4] != b"MAC " or int.from_bytes(h[4:6], "little") < 3980:
        return None
    f = [int.from_bytes(h[8 + 4 * i:12 + 4 * i], "little") for i in range(7)]
    desc, header, seek, hdata, frames_lo, frames_hi, term = f
    if not 52 <= desc <= 1024 or header > 1024:
        return None
    total = desc + header + seek + hdata + frames_lo + (frames_hi << 32) + term
    if total > min(limit, src.size) - off or total < desc + header:
        return None
    return Extent(total, VALID, ["Monkey's Audio, length from its descriptor"], ext="ape")


def _au_walk(src, off: int, limit: int) -> Extent | None:
    h = src.at(off, 24)
    if len(h) < 24:
        return None
    data_off, data_size, enc, rate, ch = (int.from_bytes(h[i:i + 4], "big") for i in (4, 8, 12, 16, 20))
    if not 24 <= data_off <= 4096 or not 1 <= enc <= 27 or not 1000 <= rate <= 384000 or not 1 <= ch <= 16:
        return None
    if data_size == 0xFFFFFFFF:
        return Extent(_until_blank(src, off + data_off, limit, 512 * MIB) - off, SUSPECT, ["length unknown"], ext="au")
    if off + data_off + data_size > min(limit, src.size):
        return None
    return Extent(data_off + data_size, VALID, ["Sun audio, length from its header"], ext="au")


def _caf_walk(src, off: int, limit: int) -> Extent | None:
    h = src.at(off, 8)
    if h[:4] != b"caff" or h[4:6] != b"\x00\x01":
        return None
    end = _end(src, limit, off, 4096 * MIB)
    pos, chunks, data = off + 8, 0, False
    while pos + 12 <= end:
        c = src.at(pos, 12)
        ctype, size = c[:4], int.from_bytes(c[4:12], "big", signed=True)
        if not all(32 <= x < 127 for x in ctype):
            break
        if chunks == 0 and ctype != b"desc":
            return None
        if size == -1 and ctype == b"data":
            pos = _until_blank(src, pos + 12, limit, 4096 * MIB)
            data = True
            break
        if size < 0 or pos + 12 + size > end:
            break
        data = data or ctype == b"data"
        chunks += 1
        pos += 12 + size
    if not data:
        return None
    return Extent(pos - off, VALID, [f"{chunks} CAF chunks"], ext="caf")


# --------------------------------------------------------------- JPEG 2000 (.jp2) and JPEG XL (.jxl) containers

def _box_walk(ext: str, last_box: bytes):
    def walk(src, off: int, limit: int) -> Extent | None:
        end = _end(src, limit, off, 1024 * MIB)
        pos, boxes, seen_last = off, 0, False
        while pos + 8 <= end:
            h = src.at(pos, 16)
            size, btype = int.from_bytes(h[:4], "big"), h[4:8]
            if not all(32 <= x < 127 for x in btype):
                break
            if size == 1:
                size = int.from_bytes(h[8:16], "big")
            elif size == 0:
                if btype == last_box:
                    stop = src.at(pos, min(end - pos, 64 * MIB)).rfind(b"\xff\xd9") if ext == "jp2" else -1
                    pos = pos + stop + 2 if stop > 0 else _until_blank(src, pos + 8, limit, 1024 * MIB)
                    seen_last = True
                break
            if size < 8 or pos + size > end:
                break
            seen_last = seen_last or btype == last_box
            boxes += 1
            pos += size
        if boxes < 2 or not seen_last:
            return None
        return Extent(pos - off, VALID, [f"{boxes} boxes"], ext=ext)
    return walk


# --------------------------------------------------------------- DjVu, PostScript/EPS, Outlook PST

def _djvu_walk(src, off: int, limit: int) -> Extent | None:
    h = src.at(off, 16)
    if len(h) < 16 or h[12:16] not in (b"DJVU", b"DJVM", b"DJVI"):
        return None
    total = 12 + int.from_bytes(h[8:12], "big")
    if off + total > min(limit, src.size):
        return None
    return Extent(total, VALID, ["DjVu, length from its FORM chunk"], ext="djvu")


def _ps_walk(src, off: int, limit: int) -> Extent | None:
    end = _end(src, limit, off, 256 * MIB)
    pos = off
    while pos < end:
        window = src.at(pos, min(4 * MIB, end - pos))
        if not window:
            break
        k = window.find(b"%%EOF")
        if k >= 0:
            stop = pos + k + 5
            tail = src.at(stop, 2)
            stop += 2 if tail == b"\r\n" else 1 if tail[:1] in (b"\n", b"\r") else 0
            eps = b"EPSF" in src.at(off, 40)
            return Extent(stop - off, VALID, ["PostScript up to %%EOF"], ext="eps" if eps else "ps")
        if b"\x00" * 64 in window:
            return None
        pos += len(window) - 4
    return None


def _eps_bin_walk(src, off: int, limit: int) -> Extent | None:
    h = src.at(off, 30)
    if len(h) < 30:
        return None
    parts = [(int.from_bytes(h[i:i + 4], "little"), int.from_bytes(h[i + 4:i + 8], "little")) for i in (4, 12, 20)]
    ps_off, ps_len = parts[0]
    if ps_off < 30 or ps_len == 0 or src.at(off + ps_off, 2) != b"%!":
        return None
    total = max(o + n for o, n in parts if o)
    if off + total > min(limit, src.size):
        return None
    return Extent(total, VALID, ["EPS with a preview, length from its header"], ext="eps")


def _pst_walk(src, off: int, limit: int) -> Extent | None:
    h = src.at(off, 0xC0)
    if len(h) < 0xC0 or h[8:10] not in (b"SM", b"SO"):
        return None
    ver = int.from_bytes(h[10:12], "little")
    if ver >= 23:
        total = int.from_bytes(h[0xB8:0xC0], "little")
    elif ver in (14, 15):
        total = int.from_bytes(h[0xA8:0xAC], "little")
    else:
        return None
    if total < 0x200 or off + total > min(limit, src.size):
        return None
    return Extent(total, VALID, ["Outlook data file, length from its header"], ext="ost" if h[8:10] == b"SO" else "pst")


# --------------------------------------------------------------- bzip2, xz (a decoder finds the exact end), CAB

def _stream_end(make, ext: str, cap: int):
    def walk(src, off: int, limit: int) -> Extent | None:
        d = make()
        end = min(limit, src.size, off + cap)
        pos = off
        while pos < end and not d.eof:
            chunk = src.at(pos, min(1 * MIB, end - pos))
            if not chunk:
                break
            try:
                d.decompress(chunk, 1 * MIB)
                while not d.eof and getattr(d, "needs_input", True) is False:
                    d.decompress(b"", 1 * MIB)
            except (OSError, EOFError, ValueError, lzma.LZMAError):
                return None
            pos += len(chunk)
        if not d.eof:
            return None
        size = pos - off - len(d.unused_data)
        return Extent(size, VALID, ["compressed stream decoded to its end"], ext=ext)
    return walk


def _cab_walk(src, off: int, limit: int) -> Extent | None:
    h = src.at(off, 36)
    if len(h) < 36 or h[24] != 3 or h[25] != 1:
        return None
    total = int.from_bytes(h[8:12], "little")
    if total < 36 or off + total > min(limit, src.size):
        return None
    return Extent(total, VALID, ["cabinet, length from its header"], ext="cab")


# --------------------------------------------------------------- Android .dex

def _dex_walk(src, off: int, limit: int) -> Extent | None:
    h = src.at(off, 0x2C)
    if len(h) < 0x2C or h[7] != 0 or not h[4:7].isdigit():
        return None
    total = int.from_bytes(h[0x20:0x24], "little")
    if int.from_bytes(h[0x24:0x28], "little") != 0x70 or int.from_bytes(h[0x28:0x2C], "little") != 0x12345678:
        return None
    if total < 0x70 or off + total > min(limit, src.size):
        return None
    return Extent(total, VALID, ["Dalvik executable, length from its header"], ext="dex")


def extra_formats() -> tuple[Format, ...]:
    return (
        Format("mpeg-ps", "mpg", (b"\x00\x00\x01\xba",), 8192 * MIB, None, _mpeg_ps_walk, None, "video", 0.7,
               quick=_mpeg_ps_quick),
        Format("mpeg-es", "m1v", (b"\x00\x00\x01\xb3",), 4096 * MIB, None, _mpeg_es_walk, None, "video", 0.6,
               quick=_mpeg_es_quick),
        Format("dav", "dav", (b"DHAV",), 16384 * MIB, None, _dav_walk, None, "video", 0.8),
        Format("rm", "rm", (b".RMF\x00\x00\x00",), 8192 * MIB, None, _rm_walk, None, "video", 0.75),
        Format("swf", "swf", (b"FWS", b"CWS"), 512 * MIB, None, _swf_walk, None, "video", 0.6, quick=_swf_quick),
        Format("mxf", "mxf", (b"\x06\x0e\x2b\x34\x02\x05\x01\x01\x0d\x01\x02\x01\x01\x02",), 32768 * MIB, None,
               _mxf_walk, None, "video", 0.8),
        Format("amr", "amr", (b"#!AMR",), 256 * MIB, None, _amr_walk, None, "audio", 0.75),
        Format("ape", "ape", (b"MAC ",), 4096 * MIB, None, _ape_walk, None, "audio", 0.75, quick=_ape_quick),
        Format("au", "au", (b".snd",), 512 * MIB, None, _au_walk, None, "audio", 0.6, quick=_au_quick),
        Format("caf", "caf", (b"caff\x00\x01",), 4096 * MIB, None, _caf_walk, None, "audio", 0.75),
        Format("jp2", "jp2", (b"\x00\x00\x00\x0cjP  \r\n\x87\n",), 1024 * MIB, None, _box_walk("jp2", b"jp2c"), None,
               "image", 0.85),
        Format("jxl", "jxl", (b"\x00\x00\x00\x0cJXL \r\n\x87\n",), 1024 * MIB, None, _box_walk("jxl", b"jxlc"), None,
               "image", 0.85),
        Format("djvu", "djvu", (b"AT&TFORM",), 1024 * MIB, None, _djvu_walk, None, "document", 0.85),
        Format("ps", "ps", (b"%!PS-Adobe",), 256 * MIB, None, _ps_walk, None, "document", 0.7),
        Format("eps-bin", "eps", (b"\xc5\xd0\xd3\xc6",), 256 * MIB, None, _eps_bin_walk, None, "document", 0.75),
        Format("pst", "pst", (b"!BDN",), 51200 * MIB, None, _pst_walk, None, "document", 0.8),
        Format("bzip2", "bz2", (b"BZh",), 4096 * MIB, None, _stream_end(bz2.BZ2Decompressor, "bz2", 4096 * MIB), None,
               "archive", 0.75, quick=lambda buf, i: i + 10 > len(buf) or (buf[i + 3] in b"123456789"
                                                                            and buf[i + 4:i + 10] == b"1AY&SY")),
        Format("xz", "xz", (b"\xfd7zXZ\x00",), 4096 * MIB, None,
               _stream_end(lambda: lzma.LZMADecompressor(lzma.FORMAT_XZ), "xz", 4096 * MIB), None, "archive", 0.85),
        Format("cab", "cab", (b"MSCF\x00\x00\x00\x00",), 2048 * MIB, None, _cab_walk, None, "archive", 0.8),
        Format("dex", "dex", (b"dex\n03",), 512 * MIB, None, _dex_walk, None, "program", 0.85),
    )
